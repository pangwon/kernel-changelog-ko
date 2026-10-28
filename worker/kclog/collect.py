"""한 릴리스 구간의 트랙 커밋을 수집해 data/<track>/<tag>/ 아래에 저장한다."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .gitrepo import NULL_OID, RawCommit, Repo
from .series import message_id, series_key
from .track import Track
from .trailers import is_cc_stable, parse_fixes, parse_trailers

# fs/ufs는 BSD Unix File System이라 Universal Flash Storage와 무관하다.
_UFS_WORD = re.compile(r"\bufs(?:hcd|hc)?\b", re.IGNORECASE)
_UNRELATED_UFS = ("fs/ufs/", "Documentation/filesystems/ufs")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def _primary(weights: Counter, order: list[str]) -> str | None:
    """변경 줄 수가 가장 많은 값. 동점이면 order에서 앞선 값."""
    if not weights:
        return None
    rank = {v: i for i, v in enumerate(order)}
    return max(weights, key=lambda v: (weights[v], -rank.get(v, len(rank))))


class Collector:
    def __init__(self, repo: Repo, track: Track, data_dir: Path):
        self.repo = repo
        self.track = track
        self.data_dir = data_dir
        self._introduced: dict[str, str | None] = {}

    def collect(self, tag: str, prev_tag: str, date: str) -> dict:
        rng = f"{prev_tag}..{tag}"
        specs = self.track.pathspecs
        raw = self.repo.log(rng, specs)

        self.repo.prefetch_blobs({
            oid for c in raw for f in c.files
            if self.track.in_track(f.path) and not f.is_submodule
            for oid in (f.old_oid, f.new_oid)
        })
        numstat = self.repo.numstat(rng, specs)
        patches = self.repo.patches(rng, specs)

        out_dir = self.data_dir / tag
        commits = [self._commit(c, tag, numstat.get(c.sha, {})) for c in raw]
        self._resolve_fixes(commits)

        for c in commits:
            patch = patches.get(c["sha"], "")
            rel = f"patches/{c['sha'][:12]}.diff"
            (out_dir / "patches").mkdir(parents=True, exist_ok=True)
            with (out_dir / rel).open("w", encoding="utf-8", newline="\n") as f:
                f.write(patch + "\n")
            c["patch"] = rel
            c["patch_bytes"] = len(patch.encode("utf-8"))

        series = self._series(commits)
        candidates = self._candidates(rng, {c["sha"] for c in commits})

        write_json(out_dir / "commits.json", commits)
        write_json(out_dir / "series.json", series)
        write_json(out_dir / "candidates.json", candidates)

        return {
            "tag": tag,
            "prev_tag": prev_tag,
            "date": date,
            "commit_count": len(commits),
            "series_count": len(series),
            "candidate_count": len(candidates),
            "areas": dict(Counter(c["area"] for c in commits).most_common()),
            "vendors": dict(Counter(c["vendor"] or "-" for c in commits).most_common()),
            "patch_bytes": sum(c["patch_bytes"] for c in commits),
            "highlights_ko": None,
        }

    def _commit(self, c: RawCommit, tag: str, stats: dict[str, tuple[int, int]]) -> dict:
        trailers = parse_trailers(c.trailers)
        files = []
        area_w: Counter = Counter()
        vendor_w: Counter = Counter()
        for f in c.files:
            in_track = self.track.in_track(f.path)
            entry = {"path": f.path, "status": f.status, "in_track": in_track}
            if in_track:
                added, deleted = stats.get(f.path, (0, 0))
                area = self.track.area_of(f.path)
                vendor = self.track.vendor_of(f.path)
                entry.update(added=added, deleted=deleted, area=area, vendor=vendor)
                # 줄 수가 0인 변경(모드 변경, 바이너리)도 1로 쳐서 분류에 반영
                weight = max(added + deleted, 1)
                area_w[area] += weight
                if vendor:
                    vendor_w[vendor] += weight
            files.append(entry)

        msgid = message_id(trailers.get("link", []))
        key, index = series_key(msgid) if msgid else (c.sha, None)
        area_order = [a for a, _ in self.track.areas] + ["other"]
        return {
            "sha": c.sha,
            "release": tag,
            "author": {"name": c.author_name, "email": c.author_email},
            "author_date": c.author_date,
            "commit_date": c.commit_date,
            "subject": c.subject,
            "body": c.body,
            "trailers": trailers,
            "fixes": parse_fixes(trailers.get("fixes", [])),
            "cc_stable": is_cc_stable(trailers),
            "message_id": msgid,
            "series_id": key,
            "series_index": index,
            "files": files,
            "area": _primary(area_w, area_order) or "other",
            "vendor": _primary(vendor_w, sorted(vendor_w)),
            "vendors": sorted(vendor_w),
            "summary_ko": None,
            "explanation_ko": None,
        }

    def _resolve_fixes(self, commits: list[dict]) -> None:
        abbrevs = sorted({f["abbrev"] for c in commits for f in c["fixes"]})
        full = self.repo.resolve(abbrevs)
        for c in commits:
            for f in c["fixes"]:
                sha = full.get(f["abbrev"])
                f["sha"] = sha
                if sha and sha not in self._introduced:
                    self._introduced[sha] = self.repo.first_release_containing(sha)
                f["introduced_in"] = self._introduced.get(sha) if sha else None

    def _series(self, commits: list[dict]) -> list[dict]:
        groups: dict[str, list[dict]] = {}
        for c in commits:
            groups.setdefault(c["series_id"], []).append(c)
        series = []
        for key, members in groups.items():
            members.sort(key=lambda c: (c["series_index"] or 0, c["commit_date"]))
            series.append({
                "id": key,
                # 커버 레터 제목은 Phase 2에서 lore로 보강. 지금은 첫 패치 제목.
                "title": members[0]["subject"],
                "commits": [c["sha"] for c in members],
                "authors": sorted({c["author"]["name"] for c in members}),
                "areas": sorted({c["area"] for c in members}),
                "summary_ko": None,
            })
        return series

    def _candidates(self, rng: str, collected: set[str]) -> list[dict]:
        """트랙 경로 밖이지만 메시지에서 UFS를 언급하는 커밋 (사람이 검토할 후보)."""
        out = []
        for c in self.repo.grep_log(rng, "ufs"):
            if c.sha in collected:
                continue
            paths = [f.path for f in c.files]
            if paths and all(p.startswith(_UNRELATED_UFS) for p in paths):
                continue
            if not _UFS_WORD.search(c.subject + "\n" + c.body):
                continue
            out.append({"sha": c.sha, "subject": c.subject, "files": paths})
        return out
