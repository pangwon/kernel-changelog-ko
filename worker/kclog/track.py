"""트랙 설정(tracks/*.toml) 로딩과 파일 경로 분류."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """git ':(glob)' pathspec을 정규식으로 바꾼다. '*'는 '/'를 넘지 않고 '**'는 넘는다."""
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


@dataclass(frozen=True)
class PathSpec:
    raw: str

    def matches(self, path: str) -> bool:
        if self.raw.startswith(":(glob)"):
            return _glob_to_regex(self.raw[len(":(glob)"):]).match(path) is not None
        spec = self.raw.rstrip("/")
        return path == spec or path.startswith(spec + "/")


@dataclass(frozen=True)
class VendorRule:
    regex: re.Pattern[str]
    vendor: str | None


@dataclass
class Track:
    id: str
    name: str
    since: str
    core: list[PathSpec]
    related: list[PathSpec]
    areas: list[tuple[str, tuple[str, ...]]]
    vendor_rules: list[VendorRule]
    vendor_aliases: dict[str, str]
    policy: dict = field(default_factory=dict)

    @property
    def pathspecs(self) -> list[str]:
        return [p.raw for p in self.core + self.related]

    def in_track(self, path: str) -> bool:
        return any(p.matches(path) for p in self.core + self.related)

    def area_of(self, path: str) -> str:
        for area_id, prefixes in self.areas:
            if any(path == p or path.startswith(p) for p in prefixes):
                return area_id
        return "other"

    def policy_for(self, vendor: str | None) -> dict:
        """[policy.default]에 [policy.vendors.<vendor>]를 덮어쓴 값."""
        merged = dict(self.policy.get("default", {}))
        if vendor:
            merged.update(self.policy.get("vendors", {}).get(vendor, {}))
        return merged

    def vendor_of(self, path: str) -> str | None:
        for rule in self.vendor_rules:
            m = rule.regex.match(path)
            if not m:
                continue
            vendor = rule.vendor or m.group("v")
            return self.vendor_aliases.get(vendor, vendor)
        return None


def load_track(path: Path) -> Track:
    with path.open("rb") as f:
        cfg = tomllib.load(f)
    return Track(
        id=cfg["id"],
        name=cfg["name"],
        since=cfg["since"],
        core=[PathSpec(p) for p in cfg["paths"]["core"]],
        related=[PathSpec(p) for p in cfg["paths"].get("related", [])],
        areas=[(a["id"], tuple(a["prefixes"])) for a in cfg.get("areas", [])],
        vendor_rules=[
            VendorRule(re.compile(v["regex"]), v.get("vendor"))
            for v in cfg.get("vendors", [])
        ],
        vendor_aliases=cfg.get("vendor_aliases", {}),
        policy=cfg.get("policy", {}),
    )
