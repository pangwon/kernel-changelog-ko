"""커밋 트레일러 파싱. 입력은 git의 %(trailers:only,unfold) 출력이다."""

from __future__ import annotations

import re

_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]*):\s*(.*)$")
_FIXES = re.compile(r'^([0-9a-fA-F]{7,40})\b\s*(?:\("(.*)"\))?')
_STABLE = re.compile(r"stable@(?:vger\.)?kernel\.org", re.IGNORECASE)


def parse_trailers(text: str) -> dict[str, list[str]]:
    """'Key: value' 줄들을 {key: [values]}로 모은다. 키는 소문자, '-'는 '_'로 바꾼다."""
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        key = m.group(1).lower().replace("-", "_")
        out.setdefault(key, []).append(m.group(2).strip())
    return out


def parse_fixes(values: list[str]) -> list[dict]:
    """'Fixes: 1234567890ab ("subject")' → {"abbrev": ..., "subject": ...}"""
    fixes = []
    for v in values:
        m = _FIXES.match(v)
        if m:
            fixes.append({"abbrev": m.group(1).lower(), "subject": m.group(2)})
    return fixes


def is_cc_stable(trailers: dict[str, list[str]]) -> bool:
    return any(_STABLE.search(v) for v in trailers.get("cc", []))
