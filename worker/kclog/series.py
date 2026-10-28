"""Link: 트레일러의 lore message-id로 같은 패치 시리즈의 커밋을 묶는다."""

from __future__ import annotations

import re
from urllib.parse import unquote

_MSGID_URL = re.compile(
    r"https?://(?:lore\.kernel\.org/(?:r|all|[\w.-]+)|patch\.msgid\.link)/([^/\s>]+)"
)
# git send-email: <YYYYmmddHHMMSS>.<pid>-<n>-<addr>@<domain>
#   한 번 실행할 때 접두어(시각.pid)가 고정되고 n만 증가한다.
_SENDEMAIL = re.compile(r"^(\d{14}\.\d+)-(\d+)-(.+@.+)$")
# b4: <YYYYmmdd>-<topic>-v<rev>-<n>-<hash>@<domain>
_B4 = re.compile(r"^(.+)-(\d+)-([0-9a-f]{6,})@(.+)$")


def message_id(links: list[str]) -> str | None:
    """Link 값들 중 첫 번째 lore/patch.msgid.link의 message-id."""
    for link in links:
        m = _MSGID_URL.search(link)
        if m:
            return unquote(m.group(1))
    return None


def series_key(msgid: str) -> tuple[str, int | None]:
    """(시리즈 키, 시리즈 안의 순번). 형식을 모르면 message-id 자체가 키가 된다."""
    m = _SENDEMAIL.match(msgid)
    if m:
        return f"{m.group(1)}-{m.group(3)}", int(m.group(2))
    m = _B4.match(msgid)
    if m:
        return f"{m.group(1)}-{m.group(3)}@{m.group(4)}", int(m.group(2))
    return msgid, None
