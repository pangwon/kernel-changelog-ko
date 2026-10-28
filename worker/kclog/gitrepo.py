"""linux.git 부분 clone(--filter=blob:none)을 다루는 얇은 git CLI 래퍼."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

UPSTREAM = os.environ.get(
    "KCLOG_UPSTREAM", "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git")
RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)$")
ANY_TAG = re.compile(r"^v(\d+)\.(\d+)(?:-rc(\d+))?$")
NULL_OID = "0" * 40

# 필드 구분 \x1f, 레코드 구분 \x1e
_LOG_FORMAT = "%x1e%H%x1f%an%x1f%ae%x1f%aI%x1f%cI%x1f%s%x1f%b%x1f%(trailers:only,unfold)%x1f"


def version_key(tag: str) -> tuple[int, int, int]:
    """v6.3-rc2 < v6.3. rc가 없는 정식 릴리스는 같은 X.Y의 모든 rc보다 뒤."""
    m = ANY_TAG.match(tag)
    if not m:
        raise ValueError(tag)
    rc = int(m.group(3)) if m.group(3) else 10**6
    return int(m.group(1)), int(m.group(2)), rc


def remote_releases(url: str = UPSTREAM) -> list[str]:
    """clone 없이 원격의 정식 릴리스 태그(vX.Y)만 오래된 순으로."""
    proc = subprocess.run(["git", "ls-remote", "--tags", "--refs", url, "v*"],
                          capture_output=True, check=True)
    tags = {line.rsplit("refs/tags/", 1)[1]
            for line in proc.stdout.decode("utf-8", "replace").splitlines() if "refs/tags/" in line}
    return sorted((t for t in tags if RELEASE_TAG.match(t)), key=version_key)


@dataclass
class RawFile:
    path: str
    old_oid: str
    new_oid: str
    status: str
    is_submodule: bool


@dataclass
class RawCommit:
    sha: str
    author_name: str
    author_email: str
    author_date: str
    commit_date: str
    subject: str
    body: str
    trailers: str
    files: list[RawFile] = field(default_factory=list)


def parse_log(out: str) -> list[RawCommit]:
    """_LOG_FORMAT + --raw 출력 파싱."""
    commits = []
    for rec in out.split("\x1e")[1:]:
        parts = rec.split("\x1f")
        sha, an, ae, ad, cd, subject, body, trailers = parts[:8]
        commit = RawCommit(sha, an, ae, ad, cd, subject, body.strip(), trailers.strip())
        for line in parts[8].splitlines() if len(parts) > 8 else []:
            if not line.startswith(":"):
                continue
            meta, path = line.split("\t", 1)
            old_mode, new_mode, old_oid, new_oid, status = meta[1:].split(" ")
            commit.files.append(
                RawFile(path, old_oid, new_oid, status,
                        "160000" in (old_mode, new_mode))
            )
        commits.append(commit)
    return commits


def split_by_commit(out: str) -> dict[str, str]:
    """'%x1e%H' 포맷 뒤에 붙은 커밋별 출력(numstat, patch)을 sha로 나눈다."""
    result = {}
    for rec in out.split("\x1e")[1:]:
        sha, _, rest = rec.partition("\n")
        result[sha.strip()] = rest.strip("\n")
    return result


class Repo:
    def __init__(self, git_dir: Path):
        self.git_dir = git_dir

    def git(self, *args: str, input: str | None = None, no_lazy_fetch: bool = False) -> str:
        env = dict(os.environ)
        if no_lazy_fetch:
            env["GIT_NO_LAZY_FETCH"] = "1"
        # 텍스트 모드는 Windows에서 stdin의 \n을 \r\n으로 바꿔 git이 오작동하므로 바이트로 주고받는다.
        proc = subprocess.run(
            ["git", f"--git-dir={self.git_dir}",
             "-c", "core.quotepath=off", "-c", "i18n.logOutputEncoding=UTF-8", *args],
            input=input.encode("utf-8") if input is not None else None,
            capture_output=True, env=env,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(f"git {' '.join(args[:3])} failed: {stderr}")
        return proc.stdout.decode("utf-8", "replace")

    # --- 저장소 준비 ---------------------------------------------------------

    def ensure(self) -> None:
        """없으면 부분 clone, 있으면 master와 태그를 갱신하고 commit-graph를 다시 쓴다."""
        if not self.git_dir.exists():
            subprocess.run(
                ["git", "clone", "--bare", "--filter=blob:none", UPSTREAM, str(self.git_dir)],
                check=True,
            )
        else:
            # bare clone에는 fetch refspec이 없으므로 명시한다.
            # 부분 clone이면 remote.origin.partialclonefilter가 그대로 적용된다.
            self.git("fetch", "--tags", "origin", "+refs/heads/master:refs/heads/master")
        # changed-path Bloom 필터가 있으면 경로 제한 git log가 크게 빨라진다.
        self.git("commit-graph", "write", "--reachable", "--changed-paths")

    # --- 태그 -------------------------------------------------------------------

    def tags(self) -> dict[str, str]:
        """{tag: creator date(ISO)} — vX.Y와 vX.Y-rcN만."""
        out = self.git("for-each-ref", "--format=%(refname:short)\t%(creatordate:iso-strict)",
                       "refs/tags/v*")
        tags = {}
        for line in out.splitlines():
            name, date = line.split("\t")
            if ANY_TAG.match(name):
                tags[name] = date
        return tags

    def releases(self) -> list[str]:
        return sorted((t for t in self.tags() if RELEASE_TAG.match(t)), key=version_key)

    # --- 커밋 -------------------------------------------------------------------

    def log(self, rev_range: str, pathspecs: list[str]) -> list[RawCommit]:
        """경로에 걸리는 non-merge 커밋. --full-diff로 커밋의 모든 파일을 함께 가져온다.
        --raw는 blob 내용이 필요 없어서 부분 clone에서도 추가 다운로드가 없다."""
        out = self.git("log", "--no-merges", "--full-history", "--full-diff", "--raw",
                       "--no-abbrev", "--no-renames", "--reverse", f"--format={_LOG_FORMAT}",
                       rev_range, "--", *pathspecs)
        return parse_log(out)

    def grep_log(self, rev_range: str, pattern: str) -> list[RawCommit]:
        """메시지에 pattern이 들어 있는 non-merge 커밋 (대소문자 무시)."""
        out = self.git("log", "--no-merges", "-i", f"--grep={pattern}", "--raw", "--no-abbrev",
                       "--no-renames", f"--format={_LOG_FORMAT}", rev_range)
        return parse_log(out)

    @property
    def is_partial(self) -> bool:
        """git.kernel.org는 --filter를 지원하지 않아 그쪽에서 받으면 전체 clone이 된다.
        (GitHub 미러 등 지원하는 서버에서 받으면 부분 clone)"""
        try:
            return bool(self.git("config", "--get", "remote.origin.promisor").strip())
        except RuntimeError:
            return False

    def prefetch_blobs(self, oids: set[str], chunk: int = 2000) -> None:
        """부분 clone이면 diff 계산 전에 필요한 blob을 한 번에 받아 둔다.
        서버가 sha 지정 fetch를 거부하면 git의 지연 다운로드에 맡긴다."""
        if not self.is_partial:
            return
        oids = sorted(o for o in oids if o != NULL_OID)
        for i in range(0, len(oids), chunk):
            try:
                self.git("fetch", "--no-tags", "--no-write-fetch-head",
                         "--recurse-submodules=no", "--filter=blob:none", "--stdin", "origin",
                         input="\n".join(oids[i:i + chunk]) + "\n")
            except RuntimeError as e:
                print(f"  warning: blob prefetch skipped ({e})")
                return

    def numstat(self, rev_range: str, pathspecs: list[str]) -> dict[str, dict[str, tuple[int, int]]]:
        out = self.git("log", "--no-merges", "--full-history", "--no-renames", "--numstat",
                       "--format=%x1e%H", rev_range, "--", *pathspecs)
        result = {}
        for sha, block in split_by_commit(out).items():
            files = {}
            for line in block.splitlines():
                added, deleted, path = line.split("\t", 2)
                # 바이너리 파일은 '-'
                files[path] = (int(added) if added != "-" else 0,
                               int(deleted) if deleted != "-" else 0)
            result[sha] = files
        return result

    def patches(self, rev_range: str, pathspecs: list[str]) -> dict[str, str]:
        out = self.git("log", "--no-merges", "--full-history", "--no-renames", "-p",
                       "--format=%x1e%H", rev_range, "--", *pathspecs)
        return split_by_commit(out)

    def resolve(self, names: list[str]) -> dict[str, str | None]:
        """축약 sha → 전체 sha. 없거나 모호하면 None."""
        if not names:
            return {}
        out = self.git("cat-file", "--batch-check=%(objectname) %(objecttype)",
                       input="\n".join(names) + "\n", no_lazy_fetch=True)
        result = {}
        for name, line in zip(names, out.splitlines()):
            parts = line.split()
            result[name] = parts[0] if len(parts) == 2 and parts[1] == "commit" else None
        return result

    def first_release_containing(self, sha: str) -> str | None:
        """sha가 처음 포함된 정식 릴리스 태그."""
        out = self.git("tag", "--list", "v*", "--contains", sha)
        releases = [t for t in out.split() if RELEASE_TAG.match(t)]
        return min(releases, key=version_key) if releases else None
