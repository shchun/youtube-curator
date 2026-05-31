"""설정(config.yaml) 로딩 및 검증."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PlaylistConfig:
    name: str = "Work Focus"
    privacy: str = "unlisted"
    description: str = ""
    max_size: int = 0  # 0 = 무제한


@dataclass
class RunConfig:
    max_additions: int = 5
    candidates_per_query: int = 15


@dataclass
class FilterConfig:
    min_duration_seconds: int = 1200
    max_duration_seconds: int = 21600
    allowed_category_ids: list[str] = field(default_factory=list)
    prefer_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    min_score: int = 2


@dataclass
class Config:
    playlist: PlaylistConfig
    run: RunConfig
    queries: list[str]
    filters: FilterConfig

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {path}")
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        queries = data.get("queries") or []
        if not queries:
            raise ValueError("config.yaml 에 'queries' 가 비어 있습니다.")

        return cls(
            playlist=PlaylistConfig(**(data.get("playlist") or {})),
            run=RunConfig(**(data.get("run") or {})),
            queries=list(queries),
            filters=FilterConfig(**(data.get("filters") or {})),
        )
