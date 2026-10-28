"""생성 단계별 시스템 프롬프트, 입력 구성, 출력 스키마.

프롬프트나 스키마를 바꾸면 PROMPT_VERSION을 올린다. 생성 결과에 버전이 기록되므로
나중에 옛 버전으로 만든 항목만 골라 다시 생성할 수 있다.
"""

from __future__ import annotations

PROMPT_VERSION = 1

COMMIT_SYSTEM = """\
당신은 리눅스 커널 UFS(Universal Flash Storage) 드라이버를 잘 아는 커널 개발자다.
메인라인에 머지된 패치 하나를 다른 커널 개발자가 읽을 한국어 요약과 해설로 정리한다.

입력은 커밋 메타데이터, 원문 커밋 메시지, 변경 파일 목록, 그리고 UFS 관련 경로로 제한한 diff다.

원칙
- 근거는 입력의 커밋 메시지와 diff뿐이다. 입력에 없는 사실(성능 수치, 하드웨어 내부 동작,
  이후에 나온 패치 등)은 추측해서 쓰지 않는다. 변경 이유가 메시지와 diff에서 드러나지 않으면
  그렇다고 밝힌다.
- 기술 용어(MCQ, WriteBooster, UIC, UPIU, hibern8, clock scaling, ICE 등)와 함수, 구조체, 매크로,
  파일 이름은 번역하지 않고 원문 그대로 쓰며 코드 표기(`...`)한다.
- 문체는 간결한 평서문(~한다, ~했다)이다.
- 여러 서브시스템에 걸친 트리 전반 변경이면 UFS 쪽에 해당하는 부분만 다룬다.

출력 필드
- summary_ko: 무엇을 왜 바꿨는지 1~2문장. 커밋 제목을 그대로 옮기지 말고 의미를 풀어 쓴다.
- change_type: 가장 가까운 하나.
  fix(버그 수정), feature(새 기능), hardware(새 SoC/디바이스 지원이나 quirk), performance(성능),
  cleanup(정리, 리팩터링, 경고 수정), docs(문서, DT binding 설명), treewide(트리 전반 기계적 변경)
- importance:
  high = 동작이 바뀌는 새 기능, 크래시, hang, 데이터 손상, 보안 문제 수정, 새 하드웨어 지원
  medium = 일반 버그 수정, 동작이 바뀌는 개선
  low = 정리, 리팩터링, 빌드 경고, 기계적 변경
- explanation_ko: 마크다운. 아래 세 소제목을 이 순서로 쓴다.
  ### 배경  — 어떤 문제나 필요가 있었는지
  ### 변경 내용  — 코드 수준 핵심 (어느 함수에서 무엇이 어떻게 바뀌었는지)
  ### 영향  — 동작 변화, 영향받는 플랫폼이나 설정, Fixes 대상과 stable 백포트 여부
  입력의 mode가 summary-only이면 빈 문자열로 둔다.
- keywords: 검색용 기술 키워드 3~8개 (원어 그대로).
"""

COMMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary_ko": {"type": "string"},
        "change_type": {
            "type": "string",
            "enum": ["fix", "feature", "hardware", "performance", "cleanup", "docs", "treewide"],
        },
        "importance": {"type": "string", "enum": ["high", "medium", "low"]},
        "explanation_ko": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary_ko", "change_type", "importance", "explanation_ko", "keywords"],
    "additionalProperties": False,
}

SERIES_SYSTEM = """\
당신은 리눅스 커널 UFS 드라이버를 잘 아는 커널 개발자다.
하나의 패치 시리즈를 이루는 커밋들의 제목과 한국어 요약을 받아, 시리즈 전체를 한국어로 정리한다.

원칙
- 근거는 입력뿐이다. 개별 요약을 나열하지 말고, 시리즈가 전체로서 무엇을 이루는지 쓴다.
- 기술 용어와 식별자는 원문 그대로 코드 표기(`...`)한다. 문체는 간결한 평서문이다.

출력 필드
- title_ko: 시리즈를 대표하는 짧은 한국어 제목 (40자 안팎)
- summary_ko: 2~4문장. 목적, 주요 변경, 영향 순서로.
"""

SERIES_SCHEMA = {
    "type": "object",
    "properties": {
        "title_ko": {"type": "string"},
        "summary_ko": {"type": "string"},
    },
    "required": ["title_ko", "summary_ko"],
    "additionalProperties": False,
}

RELEASE_SYSTEM = """\
당신은 리눅스 커널 UFS 드라이버를 잘 아는 커널 개발자다.
한 커널 릴리스에 들어간 UFS 관련 변경(패치 시리즈와 개별 커밋의 한국어 요약)을 받아,
커널 개발자가 이 릴리스에서 무엇이 바뀌었는지 빠르게 파악할 수 있도록 정리한다.

원칙
- 근거는 입력뿐이다. 중요도(importance)가 높은 변경과 여러 커밋이 모인 시리즈를 우선한다.
- 기술 용어와 식별자는 원문 그대로 코드 표기(`...`)한다. 문체는 간결한 평서문이다.
- 각 항목의 commits에는 근거가 된 커밋의 12자리 sha를 입력에서 그대로 옮긴다.

출력 필드
- headline_ko: 이 릴리스의 UFS 변경을 한 문장으로.
- highlights: 주요 변경 3~6개. 각 항목은 title_ko(짧은 제목), description_ko(1~3문장), commits.
- area_notes: 입력에 등장한 영역(area)마다 1~2문장 정리. 각 항목은 area, summary_ko.
"""

RELEASE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline_ko": {"type": "string"},
        "highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title_ko": {"type": "string"},
                    "description_ko": {"type": "string"},
                    "commits": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title_ko", "description_ko", "commits"],
                "additionalProperties": False,
            },
        },
        "area_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "area": {"type": "string"},
                    "summary_ko": {"type": "string"},
                },
                "required": ["area", "summary_ko"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline_ko", "highlights", "area_notes"],
    "additionalProperties": False,
}

# 트랙 밖 파일 목록은 맥락용이라 이 개수까지만 보여준다 (diff 자체는 자르지 않는다).
MAX_OTHER_FILES = 20


def commit_input(commit: dict, patch: str, series_subjects: list[str], explain: bool) -> str:
    lines = [
        "<commit>",
        f"release: {commit['release']}",
        f"sha: {commit['sha']}",
        f"author: {commit['author']['name']}",
        f"date: {commit['author_date']}",
        f"subject: {commit['subject']}",
        f"area: {commit['area']}",
        f"vendor: {commit['vendor'] or '-'}",
        f"mode: {'full' if explain else 'summary-only'}",
    ]
    for f in commit["fixes"]:
        introduced = f.get("introduced_in") or "알 수 없음"
        lines.append(f"fixes: {f['abbrev']} (\"{f['subject']}\"), 도입 릴리스 {introduced}")
    if commit["cc_stable"]:
        lines.append("cc_stable: yes")
    if len(series_subjects) > 1:
        lines.append(f"series: {len(series_subjects)}개 패치로 된 시리즈의 일부. 시리즈 패치 제목:")
        lines += [f"  - {s}" for s in series_subjects]

    track_files = [f for f in commit["files"] if f["in_track"]]
    other_files = [f for f in commit["files"] if not f["in_track"]]
    lines.append("files:")
    lines += [f"  {f['status']} {f['path']} (+{f['added']} -{f['deleted']})" for f in track_files]
    if other_files:
        lines.append(f"  (UFS 밖 파일 {len(other_files)}개)")
        lines += [f"  {f['status']} {f['path']}" for f in other_files[:MAX_OTHER_FILES]]
        if len(other_files) > MAX_OTHER_FILES:
            lines.append(f"  ... 외 {len(other_files) - MAX_OTHER_FILES}개")
    lines.append("</commit>")

    message = commit["body"] or "(본문 없음)"
    return "\n".join(lines) + f"\n<message>\n{message}\n</message>\n<diff>\n{patch}\n</diff>"


def series_input(series: dict, commits: dict[str, dict]) -> str:
    lines = [f"<series patches=\"{len(series['commits'])}\">"]
    for i, sha in enumerate(series["commits"], 1):
        c = commits[sha]
        lines.append(f"[{i}] {c['subject']}")
        lines.append(f"    {c['change_type']}, {c['importance']}: {c['summary_ko']}")
    lines.append("</series>")
    return "\n".join(lines)


def release_input(release: dict, series: list[dict], commits: dict[str, dict]) -> str:
    lines = [f"<release tag=\"{release['tag']}\" prev=\"{release['prev_tag']}\" "
             f"commits=\"{release['commit_count']}\">"]
    for s in series:
        members = [commits[sha] for sha in s["commits"]]
        importance = min((c["importance"] for c in members),
                         key=["high", "medium", "low"].index)
        vendors = sorted({v for c in members for v in c["vendors"]}) or ["-"]
        shas = " ".join(sha[:12] for sha in s["commits"])
        title = s.get("title_ko") or members[0]["subject"]
        lines.append(f"- [{importance}] [{', '.join(s['areas'])}] [vendor {', '.join(vendors)}] "
                     f"{title} (패치 {len(members)}개; {shas})")
        lines.append(f"  {s['summary_ko']}")
    lines.append("</release>")
    return "\n".join(lines)
