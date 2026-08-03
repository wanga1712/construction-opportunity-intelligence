"""???????????? ???????? ???????? ??? ???????????? ??????.

???????? ?????? ?????? ? CRM ?? ? ??????????? ? ?????????? ???????.
JSON ???????? ?????? ??? ????????? fallback, ???? CRM ??????????.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .crm_taxonomy_loader import load_profiles


DEFAULT_CONFIG_PATH = Path(__file__).with_name("search_profiles.json")


@dataclass(frozen=True)
class SearchProfile:
    code: str
    name: str
    product_groups: tuple[str, ...]
    object_segments: tuple[str, ...]
    sources: tuple[str, ...]
    title_include_any: tuple[str, ...] = ()
    title_exclude_any: tuple[str, ...] = ()
    object_keywords: tuple[str, ...] = ()
    ai_routing_hint: str = ""
    document_search: bool = True
    comment: str = ""

    def candidate_score(self, *, title: str = "", segment: str = "", source: str = "") -> tuple[int, list[str]]:
        haystack = (title or "").lower()
        score = 0
        reasons: list[str] = []

        if source and self.sources and source in self.sources:
            score += 5
            reasons.append(f"source:{source}")
        elif source and self.sources:
            return 0, [f"source_mismatch:{source}"]

        if segment and self.object_segments and segment in self.object_segments:
            score += 12
            reasons.append(f"segment:{segment}")

        excludes = [w for w in self.title_exclude_any if w and w.lower() in haystack]
        includes = [w for w in self.title_include_any if w and w.lower() in haystack]
        object_hits = [w for w in self.object_keywords if w and w.lower() in haystack]
        positive_profile_signal = bool(includes or object_hits)

        if excludes and not positive_profile_signal:
            return 0, [f"excluded:{', '.join(excludes[:3])}"]
        if (self.title_include_any or self.object_keywords) and not positive_profile_signal:
            return 0, ["no_profile_signal"]
        if includes:
            score += 70
            reasons.append(f"title_include:{', '.join(includes[:3])}")
        if object_hits:
            score += 45
            reasons.append(f"object_keyword:{', '.join(object_hits[:3])}")
        if excludes:
            score -= 30
            reasons.append(f"title_exclude:{', '.join(excludes[:3])}")
        return max(0, min(100, score)), reasons


@dataclass(frozen=True)
class SearchProfilesConfig:
    version: str
    physical_daemons_recommended: int
    download_parse_workers: int
    profile_match_workers: int
    total_logical_workers: int
    profiles: tuple[SearchProfile, ...]

    @property
    def active_document_profiles(self) -> tuple[SearchProfile, ...]:
        return tuple(profile for profile in self.profiles if profile.document_search)

    def summary(self) -> str:
        names = ", ".join(profile.name for profile in self.active_document_profiles)
        return (
            f"profiles={len(self.active_document_profiles)} "
            f"logical_workers={self.total_logical_workers} "
            f"download_parse={self.download_parse_workers} "
            f"profile_match={self.profile_match_workers}: {names}"
        )

    def route_object(self, *, title: str = "", segment: str = "", source: str = "", min_score: int = 35) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for profile in self.active_document_profiles:
            score, reasons = profile.candidate_score(title=title, segment=segment, source=source)
            if score >= min_score:
                candidates.append(
                    {
                        "profile_code": profile.code,
                        "profile_name": profile.name,
                        "product_groups": list(profile.product_groups),
                        "score": score,
                        "reasons": reasons,
                    }
                )
        candidates.sort(key=lambda item: int(item["score"]), reverse=True)
        return candidates


def load_search_profiles(path: Path | None = None) -> SearchProfilesConfig:
    db_profiles = _load_from_crm()
    if db_profiles:
        profiles = tuple(_profile_from_dict(item) for item in db_profiles)
        return SearchProfilesConfig(
            version="crm_taxonomy_v1",
            physical_daemons_recommended=2,
            download_parse_workers=1,
            profile_match_workers=max(1, len(profiles)),
            total_logical_workers=1 + len(profiles),
            profiles=profiles,
        )

    config_path = path or DEFAULT_CONFIG_PATH
    raw: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    worker_model = raw.get("worker_model") or {}
    profiles = tuple(_profile_from_dict(item) for item in raw.get("profiles", []))
    return SearchProfilesConfig(
        version=str(raw.get("version") or "json_fallback"),
        physical_daemons_recommended=int(worker_model.get("physical_daemons_recommended") or 1),
        download_parse_workers=int(worker_model.get("download_parse_workers") or 1),
        profile_match_workers=int(worker_model.get("profile_match_workers") or len(profiles) or 1),
        total_logical_workers=int(worker_model.get("total_logical_workers") or (1 + len([p for p in profiles if p.document_search]))),
        profiles=profiles,
    )


def _load_from_crm() -> list[dict[str, Any]]:
    try:
        return load_profiles(contour_code="procurement")
    except Exception:
        return []


def _profile_from_dict(item: dict[str, Any]) -> SearchProfile:
    return SearchProfile(
        code=str(item["code"]),
        name=str(item["name"]),
        product_groups=tuple(item.get("product_groups") or ()),
        object_segments=tuple(item.get("object_segments") or ()),
        sources=tuple(item.get("sources") or ()),
        title_include_any=tuple(item.get("title_include_any") or ()),
        title_exclude_any=tuple(item.get("title_exclude_any") or ()),
        object_keywords=tuple(item.get("object_keywords") or ()),
        ai_routing_hint=str(item.get("ai_routing_hint") or ""),
        document_search=bool(item.get("document_search", True)),
        comment=str(item.get("comment") or ""),
    )
