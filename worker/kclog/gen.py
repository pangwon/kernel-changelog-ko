"""커밋 → 시리즈 → 릴리스 순서의 한국어 요약 생성 작업을 Claude Code와 주고받는다.

export: 생성할 항목마다 입력 파일(<id>.input.md)을 쓰고, 단계별 지침(INSTRUCTIONS.md)을 한 번 쓴다.
Claude Code가 지침과 입력을 읽고 같은 이름의 <id>.json에 결과를 쓴다.
import: 결과를 스키마로 검증한 뒤 data/<track>/<tag>/*.json에 반영하고 작업 파일을 지운다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import prompts
from .collect import write_json
from .track import Track

# UFS 파일 비중이 이보다 낮은 커밋은 트리 전반 변경으로 보고 요약만 만든다.
TREEWIDE_SHARE = 0.5

STAGES = {
    "commits": (prompts.COMMIT_SYSTEM, prompts.COMMIT_SCHEMA),
    "series": (prompts.SERIES_SYSTEM, prompts.SERIES_SCHEMA),
    "release": (prompts.RELEASE_SYSTEM, prompts.RELEASE_SCHEMA),
}


@dataclass
class Job:
    id: str
    user: str
    apply: Callable[[dict, dict], None]  # (생성 결과, gen 메타데이터)


def gen_info(model: str | None) -> dict:
    return {
        "by": "claude-code",
        "model": model,
        "prompt_version": prompts.PROMPT_VERSION,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# --- 스키마 검증 ----------------------------------------------------------------


def validate(schema: dict, value, path: str = "$") -> list[str]:
    """prompts.py의 스키마가 쓰는 범위(object/array/string, enum, required,
    additionalProperties=false)만 검사한다. 오류 메시지 목록을 돌려준다."""
    t = schema["type"]
    if t == "object":
        if not isinstance(value, dict):
            return [f"{path}: object가 아님"]
        errors = [f"{path}.{k}: 누락" for k in schema["required"] if k not in value]
        errors += [f"{path}.{k}: 허용되지 않은 필드" for k in value if k not in schema["properties"]]
        for k, sub in schema["properties"].items():
            if k in value:
                errors += validate(sub, value[k], f"{path}.{k}")
        return errors
    if t == "array":
        if not isinstance(value, list):
            return [f"{path}: array가 아님"]
        return [e for i, v in enumerate(value) for e in validate(schema["items"], v, f"{path}[{i}]")]
    if t == "string":
        if not isinstance(value, str):
            return [f"{path}: string이 아님"]
        if "enum" in schema and value not in schema["enum"]:
            return [f"{path}: {value!r}는 {schema['enum']} 중 하나가 아님"]
        return []
    raise ValueError(f"지원하지 않는 스키마 타입 {t}")


# --- 데이터 ------------------------------------------------------------------


class ReleaseData:
    def __init__(self, data_dir: Path, tag: str):
        self.dir = data_dir / tag
        self.tag = tag
        self.commits: list[dict] = json.loads((self.dir / "commits.json").read_text("utf-8"))
        self.series: list[dict] = json.loads((self.dir / "series.json").read_text("utf-8"))
        self.by_sha = {c["sha"]: c for c in self.commits}

    def patch(self, commit: dict) -> str:
        return (self.dir / commit["patch"]).read_text("utf-8")

    def save(self) -> None:
        write_json(self.dir / "commits.json", self.commits)
        write_json(self.dir / "series.json", self.series)


def is_treewide(commit: dict) -> bool:
    files = commit["files"]
    return bool(files) and sum(f["in_track"] for f in files) / len(files) < TREEWIDE_SHARE


def should_explain(track: Track, commit: dict) -> bool:
    return not is_treewide(commit) and track.policy_for(commit["vendor"]).get("explain", True)


# --- 단계별 Job ---------------------------------------------------------------


def commit_jobs(rd: ReleaseData, track: Track, force: bool,
                shas: list[str] | None = None) -> list[Job]:
    series_of = {sha: s for s in rd.series for sha in s["commits"]}
    jobs = []
    for c in rd.commits:
        if shas and not any(c["sha"].startswith(p) for p in shas):
            continue
        if c.get("summary_ko") and not force:
            continue
        explain = should_explain(track, c)
        subjects = [rd.by_sha[sha]["subject"] for sha in series_of[c["sha"]]["commits"]]

        def apply(out: dict, info: dict, c=c, explain=explain) -> None:
            c["summary_ko"] = out["summary_ko"]
            c["change_type"] = out["change_type"]
            c["importance"] = out["importance"]
            c["explanation_ko"] = out["explanation_ko"] if explain else None
            c["keywords"] = out["keywords"]
            c["gen"] = info

        jobs.append(Job(
            id=f"c-{c['sha']}",
            user=prompts.commit_input(c, rd.patch(c), subjects, explain),
            apply=apply,
        ))
    return jobs


def series_jobs(rd: ReleaseData, force: bool) -> list[Job]:
    jobs = []
    for s in rd.series:
        members = [rd.by_sha[sha] for sha in s["commits"]]
        if any(not c.get("summary_ko") for c in members):
            continue
        if len(members) == 1:
            # 단일 커밋 시리즈는 커밋 요약을 그대로 쓴다 (생성 작업 없음).
            s["title_ko"] = None
            s["summary_ko"] = members[0]["summary_ko"]
            continue
        if s.get("summary_ko") and not force:
            continue

        def apply(out: dict, info: dict, s=s) -> None:
            s["title_ko"] = out["title_ko"]
            s["summary_ko"] = out["summary_ko"]
            s["gen"] = info

        # 한 송신 묶음이 여러 릴리스로 나뉘어 머지되기도 하므로 릴리스까지 넣어 해시한다.
        jobs.append(Job(
            id="s-" + hashlib.sha1(f"{rd.tag}/{s['id']}".encode()).hexdigest()[:40],
            user=prompts.series_input(s, rd.by_sha),
            apply=apply,
        ))
    return jobs


def release_jobs(rd: ReleaseData, release: dict, force: bool) -> list[Job]:
    if release.get("highlights_ko") and not force:
        return []
    if any(not s.get("summary_ko") for s in rd.series):
        return []
    known = {c["sha"][:12] for c in rd.commits}

    def apply(out: dict, info: dict) -> None:
        # 입력에 없는 sha가 적혀 있으면 버린다.
        for h in out["highlights"]:
            h["commits"] = [sha[:12] for sha in h["commits"] if sha[:12] in known]
        release["highlights_ko"] = out
        release["gen"] = info

    return [Job(
        id="r-" + rd.tag.replace(".", "_"),
        user=prompts.release_input(release, rd.series, rd.by_sha),
        apply=apply,
    )]


# --- 작업 파일 주고받기 ----------------------------------------------------------


def instructions(stage: str) -> str:
    system, schema = STAGES[stage]
    return (
        f"{system}\n"
        "작업 방법\n"
        "- 이 폴더의 각 <id>.input.md를 읽고, 결과를 같은 폴더의 <id>.json에 쓴다.\n"
        "- <id>.json은 아래 JSON 스키마를 만족하는 객체 하나다. 다른 텍스트는 넣지 않는다.\n"
        "- 여러 결과를 한 파일에 모으려면 batch-<이름>.json에 {\"<id>\": 결과 객체, ...}로 쓴다.\n\n"
        f"```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```\n"
    )


def export_jobs(stage: str, jobs: list[Job], work_dir: Path) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "INSTRUCTIONS.md").write_text(instructions(stage), encoding="utf-8", newline="\n")
    for job in jobs:
        (work_dir / f"{job.id}.input.md").write_text(job.user, encoding="utf-8", newline="\n")


def import_results(stage: str, jobs: list[Job], work_dir: Path,
                   model: str | None) -> tuple[list[str], list[tuple[str, str]]]:
    """(반영된 id 목록, (id, 오류) 목록). 작업 파일은 데이터를 저장한 뒤
    remove_work_files()로 지운다 (저장 전에 지우면 실패 시 결과를 잃는다)."""
    _, schema = STAGES[stage]
    by_id = {job.id: job for job in jobs}
    if len(by_id) != len(jobs):
        dup = sorted({j.id for j in jobs if sum(k.id == j.id for k in jobs) > 1})
        raise ValueError(f"작업 id가 겹친다 (결과가 엉뚱한 항목에 반영될 수 있음): {dup}")
    applied, failures = [], []

    results: list[tuple[str, object]] = []
    for path in sorted(work_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError as e:
            failures.append((path.stem, f"JSON 파싱 실패: {e}"))
            continue
        if path.stem.startswith("batch-"):
            results += data.items() if isinstance(data, dict) else [(path.stem, None)]
        else:
            results.append((path.stem, data))

    for job_id, out in results:
        job = by_id.get(job_id)
        if job is None:
            failures.append((job_id, "대응하는 작업이 없음 (이미 반영됐거나 데이터가 바뀜)"))
            continue
        errors = validate(schema, out)
        if errors:
            failures.append((job_id, "; ".join(errors[:5])))
            continue
        job.apply(out, gen_info(model))
        applied.append(job_id)
    return applied, failures


def remove_work_files(work_dir: Path, job_ids: list[str]) -> None:
    """반영된 항목의 입력·결과를 지운다. batch 파일에서는 반영된 항목만 빼고 남긴다."""
    done = set(job_ids)
    for job_id in job_ids:
        (work_dir / f"{job_id}.json").unlink(missing_ok=True)
        (work_dir / f"{job_id}.input.md").unlink(missing_ok=True)
    for path in work_dir.glob("batch-*.json"):
        try:
            data = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            continue
        rest = {k: v for k, v in data.items() if k not in done}
        if rest:
            write_json(path, rest)
        else:
            path.unlink()
