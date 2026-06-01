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
class Job:
    """플레이리스트 1개에 대한 큐레이션 작업 (대상 + 검색어 + 필터)."""

    playlist: PlaylistConfig
    run: RunConfig
    queries: list[str]
    filters: FilterConfig


def _parse_job(item: dict[str, Any]) -> Job:
    """playlists 항목 1개를 Job 으로 변환.

    playlist 관련 필드(name/privacy/description/max_size)는 항목 최상위에
    평평하게 두거나 'playlist:' 하위에 둘 수 있다. 둘 다 지원한다.
    """
    queries = item.get("queries") or []
    name = (item.get("playlist") or {}).get("name") or item.get("name") or "(이름 없음)"
    if not queries:
        raise ValueError(f"플레이리스트 '{name}' 에 'queries' 가 비어 있습니다.")

    nested = item.get("playlist")
    if nested:
        playlist_data = nested
    else:
        playlist_data = {
            k: item[k]
            for k in ("name", "privacy", "description", "max_size")
            if k in item
        }

    return Job(
        playlist=PlaylistConfig(**playlist_data),
        run=RunConfig(**(item.get("run") or {})),
        queries=list(queries),
        filters=FilterConfig(**(item.get("filters") or {})),
    )


@dataclass
class Config:
    jobs: list[Job]

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {path}")
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        if data.get("playlists"):
            # 신규 형식: 여러 플레이리스트
            jobs = [_parse_job(item) for item in data["playlists"]]
        else:
            # 구 형식: 단일 플레이리스트 (하위 호환)
            jobs = [_parse_job(data)]

        if not jobs:
            raise ValueError("config.yaml 에 큐레이션할 플레이리스트가 없습니다.")
        return cls(jobs=jobs)
