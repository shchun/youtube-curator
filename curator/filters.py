"""후보 영상 채점/필터링.

"말 적고, 로우파이이고, 집중력 향상" 기준에 따라 점수를 매기고
제외 조건에 걸리는 영상은 버린다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import FilterConfig

# ISO 8601 duration (PT#H#M#S) 파서
_ISO_DURATION = re.compile(
    r"PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?"
)


def parse_duration_seconds(iso: str) -> int:
    match = _ISO_DURATION.fullmatch(iso or "")
    if not match:
        return 0
    h = int(match.group("h") or 0)
    m = int(match.group("m") or 0)
    s = int(match.group("s") or 0)
    return h * 3600 + m * 60 + s


@dataclass
class ScoredVideo:
    video_id: str
    title: str
    channel: str
    duration_seconds: int
    score: int
    reasons: list[str]

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


def evaluate(video: dict, cfg: FilterConfig) -> ScoredVideo | None:
    """단일 영상을 평가한다. 제외 조건이면 None 반환."""
    snippet = video.get("snippet", {})
    content = video.get("contentDetails", {})
    status = video.get("status", {})

    video_id = video.get("id", "")
    title = snippet.get("title", "")
    description = snippet.get("description", "")
    channel = snippet.get("channelTitle", "")
    category_id = snippet.get("categoryId", "")
    haystack = f"{title}\n{description}".lower()

    # 비공개/임베드 불가 영상은 플레이리스트에 부적합
    if status.get("privacyStatus") == "private":
        return None

    # 제외 키워드
    for kw in cfg.exclude_keywords:
        if kw.lower() in haystack:
            return None

    # 길이 제한
    duration = parse_duration_seconds(content.get("duration", ""))
    if duration < cfg.min_duration_seconds or duration > cfg.max_duration_seconds:
        return None

    score = 0
    reasons: list[str] = []

    # 카테고리 가점 (제한이 설정된 경우, 불일치는 즉시 탈락)
    if cfg.allowed_category_ids:
        if category_id not in cfg.allowed_category_ids:
            return None
        score += 1
        reasons.append(f"category={category_id}")

    # 선호 키워드 가점
    for kw in cfg.prefer_keywords:
        if kw.lower() in haystack:
            score += 1
            reasons.append(f"+{kw}")

    if score < cfg.min_score:
        return None

    return ScoredVideo(
        video_id=video_id,
        title=title,
        channel=channel,
        duration_seconds=duration,
        score=score,
        reasons=reasons,
    )


def rank_candidates(
    videos: list[dict],
    cfg: FilterConfig,
    exclude_ids: set[str],
) -> list[ScoredVideo]:
    """후보를 평가하고 점수 내림차순으로 정렬해 반환한다."""
    seen: set[str] = set()
    scored: list[ScoredVideo] = []
    for video in videos:
        vid = video.get("id", "")
        if not vid or vid in exclude_ids or vid in seen:
            continue
        seen.add(vid)
        result = evaluate(video, cfg)
        if result is not None:
            scored.append(result)
    scored.sort(key=lambda v: v.score, reverse=True)
    return scored
