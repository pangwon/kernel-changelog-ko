"""python -m kclog {fetch,collect,stats}"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

from .collect import Collector, write_json
from .gitrepo import Repo, version_key
from .track import load_track

ROOT = Path(__file__).resolve().parents[2]
GIT_DIR = Path(os.environ.get("KCLOG_GIT_DIR", ROOT / ".cache" / "linux.git"))

# 토큰 수 대략치. 코드/diff는 영어 산문보다 토큰 밀도가 높아 보수적으로 잡는다.
BYTES_PER_TOKEN = 3.5


def cmd_fetch(args) -> None:
    Repo(GIT_DIR).ensure()
    print(f"ok: {GIT_DIR}")


def cmd_collect(args) -> None:
    repo = Repo(GIT_DIR)
    track = load_track(ROOT / "tracks" / f"{args.track}.toml")
    data_dir = ROOT / "data" / track.id
    tags = repo.tags()
    releases = repo.releases()

    since = version_key(track.since)
    targets = [(prev, tag) for prev, tag in zip(releases, releases[1:])
               if version_key(tag) >= since and (not args.release or tag in args.release)]

    index_path = data_dir / "releases.json"
    index = {r["tag"]: r for r in json.loads(index_path.read_text("utf-8"))} \
        if index_path.exists() else {}
    # since를 올렸다면 그보다 오래된 릴리스는 목록에서 뺀다 (data 폴더는 직접 지운다).
    for tag in [t for t in index if version_key(t) < since]:
        print(f"drop {tag} (older than since={track.since})")
        del index[tag]

    collector = Collector(repo, track, data_dir)
    for prev, tag in targets:
        if tag in index and not args.force:
            print(f"skip {tag} (already collected, --force to redo)")
            continue
        print(f"collect {prev}..{tag} ...", flush=True)
        summary = collector.collect(tag, prev, tags[tag])
        index[tag] = summary
        print(f"  {summary['commit_count']} commits, {summary['series_count']} series, "
              f"{summary['candidate_count']} candidates")

    write_json(index_path, sorted(index.values(), key=lambda r: version_key(r["tag"])))


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "-"


def cmd_stats(args) -> None:
    data_dir = ROOT / "data" / args.track
    releases = json.loads((data_dir / "releases.json").read_text("utf-8"))

    print(f"{'release':<8} {'commits':>7} {'series':>6} {'cand':>5} {'other':>6} "
          f"{'qcom':>6} {'patch KB':>9}  top areas")
    all_commits = []
    for r in releases:
        commits = json.loads((data_dir / r["tag"] / "commits.json").read_text("utf-8"))
        all_commits += commits
        n = r["commit_count"]
        top = ", ".join(f"{a}:{c}" for a, c in list(r["areas"].items())[:4])
        print(f"{r['tag']:<8} {n:>7} {r['series_count']:>6} {r['candidate_count']:>5} "
              f"{_pct(r['areas'].get('other', 0), n):>6} "
              f"{_pct(sum(1 for c in commits if 'qcom' in c['vendors']), n):>6} "
              f"{r['patch_bytes'] / 1024:>9.0f}  {top}")

    total = len(all_commits)
    print(f"\n총 {total} 커밋, 릴리스 {len(releases)}개, 릴리스당 평균 {total / max(len(releases), 1):.0f}")

    print("\n[영역]")
    for area, n in Counter(c["area"] for c in all_commits).most_common():
        print(f"  {area:<10} {n:>5}  {_pct(n, total)}")

    print("\n[벤더] (해당 벤더 파일을 건드린 커밋, 중복 집계)")
    for vendor, n in Counter(v for c in all_commits for v in c["vendors"]).most_common():
        print(f"  {vendor:<10} {n:>5}  {_pct(n, total)}")
    print(f"  {'(벤더 없음)':<10} {sum(1 for c in all_commits if not c['vendors']):>5}")

    sizes = sorted(c["patch_bytes"] for c in all_commits)
    if sizes:
        q = statistics.quantiles(sizes, n=100)
        tok = lambda b: f"{b / 1024:7.1f} KB ≈ {b / BYTES_PER_TOKEN / 1000:6.1f}k tok"
        print("\n[diff 크기] (트랙 경로로 제한한 diff 기준, 토큰은 대략치)")
        for label, v in [("p50", q[49]), ("p90", q[89]), ("p99", q[98]), ("max", sizes[-1])]:
            print(f"  {label:<4} {tok(v)}")
        print(f"  합계 {tok(sum(sizes))}")
        big = sum(1 for s in sizes if s / BYTES_PER_TOKEN > 20_000)
        print(f"  20k 토큰 초과: {big}개")

    print("\n[트레일러]")
    print(f"  Fixes 있음:     {sum(1 for c in all_commits if c['fixes']):>5}")
    print(f"  Cc: stable:     {sum(1 for c in all_commits if c['cc_stable']):>5}")
    print(f"  Link 없음:      {sum(1 for c in all_commits if not c['message_id']):>5}")
    unresolved = [f for c in all_commits for f in c["fixes"] if not f.get("sha")]
    print(f"  Fixes 해석 실패: {len(unresolved):>4}")

    print("\n[트랙 밖 동시 수정 파일 Top 15] (related 경로 후보)")
    co = Counter(f["path"] for c in all_commits for f in c["files"] if not f["in_track"])
    for path, n in co.most_common(15):
        print(f"  {n:>4}  {path}")


def cmd_gen(args) -> None:
    from . import gen

    track = load_track(ROOT / "tracks" / f"{args.track}.toml")
    data_dir = ROOT / "data" / track.id
    index_path = data_dir / "releases.json"
    releases = json.loads(index_path.read_text("utf-8"))
    by_tag = {r["tag"]: r for r in releases}
    data = {tag: gen.ReleaseData(data_dir, tag) for tag in args.release or by_tag}
    work_dir = ROOT / ".cache" / "gen" / track.id / args.stage
    # import는 이미 생성된 항목의 재생성 결과도 받아야 하므로 항상 전체 작업 목록과 대조한다.
    force = args.force or args.action == "import"

    jobs = []
    for tag, rd in data.items():
        if args.stage == "commits":
            jobs += gen.commit_jobs(rd, track, force, args.sha)
        elif args.stage == "series":
            jobs += gen.series_jobs(rd, force)
        else:
            jobs += gen.release_jobs(rd, by_tag[tag], force)

    if args.action == "export":
        if args.limit:
            jobs = jobs[:args.limit]
        gen.export_jobs(args.stage, jobs, work_dir)
        est = sum(len(j.user.encode("utf-8")) for j in jobs) / BYTES_PER_TOKEN
        print(f"[{args.stage}] {len(jobs)}개 작업, 입력 약 {est / 1000:.0f}k 토큰 (대략치)")
        print(f"  지침: {work_dir / 'INSTRUCTIONS.md'}")
        if args.stage == "series":
            # 단일 커밋 시리즈는 export 중에 커밋 요약이 바로 채워진다.
            for rd in data.values():
                rd.save()
        return

    applied, failures = gen.import_results(args.stage, jobs, work_dir, args.model)
    for rd in data.values():
        rd.save()
    write_json(index_path, releases)
    gen.remove_work_files(work_dir, applied)
    pending = len(list(work_dir.glob("*.input.md"))) if work_dir.exists() else 0
    print(f"[{args.stage}] 반영 {len(applied)}개, 실패 {len(failures)}개, 결과 대기 {pending}개")
    for job_id, err in failures:
        print(f"  실패 {job_id}: {err}")


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="kclog")
    sub = p.add_subparsers(required=True)

    s = sub.add_parser("fetch", help="linux.git 부분 clone 또는 갱신")
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("collect", help="릴리스별 트랙 커밋 수집")
    s.add_argument("--track", default="ufs")
    s.add_argument("--release", action="append", help="특정 릴리스만 (여러 번 지정 가능)")
    s.add_argument("--force", action="store_true", help="이미 수집한 릴리스도 다시 수집")
    s.set_defaults(func=cmd_collect)

    s = sub.add_parser("stats", help="수집 결과 통계")
    s.add_argument("--track", default="ufs")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("gen", help="Claude Code와 한국어 요약 작업 파일 주고받기")
    s.add_argument("action", choices=["export", "import"],
                   help="export: 작업 파일 생성, import: 결과 검증 후 반영")
    s.add_argument("stage", choices=["commits", "series", "release"])
    s.add_argument("--track", default="ufs")
    s.add_argument("--release", action="append", help="특정 릴리스만 (여러 번 지정 가능)")
    s.add_argument("--sha", action="append", help="commits 단계에서 이 sha 접두어만")
    s.add_argument("--limit", type=int, help="export할 최대 작업 수")
    s.add_argument("--force", action="store_true", help="이미 생성된 항목도 다시 export")
    s.add_argument("--model", help="import 시 기록할 생성 모델 이름 (예: claude-opus-5-5)")
    s.set_defaults(func=cmd_gen)

    args = p.parse_args(argv)
    args.func(args)
