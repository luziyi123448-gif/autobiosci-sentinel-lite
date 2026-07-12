from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Topic:
    name: str
    query: str
    core_keywords: list[str]
    retmax: int = 30
    days_back: int | None = 30


def load_topics(path: str | Path, retmax_override: int | None = None) -> list[Topic]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    topics = raw.get("topics")
    if not isinstance(topics, list) or not topics:
        raise ValueError("Config must contain a non-empty 'topics' list")

    loaded: list[Topic] = []
    for item in topics:
        if not isinstance(item, dict):
            raise ValueError("Each topic must be a mapping")
        name = str(item.get("name", "")).strip()
        query = str(item.get("query", "")).strip()
        keywords = item.get("core_keywords") or []
        if not name or not query:
            raise ValueError("Each topic must include 'name' and 'query'")
        if not isinstance(keywords, list):
            raise ValueError(f"Topic {name!r} has invalid core_keywords")

        loaded.append(
            Topic(
                name=name,
                query=query,
                core_keywords=[str(k) for k in keywords],
                retmax=int(retmax_override if retmax_override is not None else item.get("retmax", 30)),
                days_back=int(item["days_back"]) if item.get("days_back") is not None else None,
            )
        )
    return loaded
