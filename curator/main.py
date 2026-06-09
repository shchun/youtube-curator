"""엔트리포인트: 검색 -> 채점 -> 플레이리스트에 추가.

실행:
    python -m curator.main --config config.yaml
    python -m curator.main --config config.yaml --dry-run   # 추가하지 않고 결과만 출력
"""

from __future__ import annotations

import argparse
import sys

from googleapiclient.errors import HttpError

# 영상 제목에 이모지/비라틴 문자가 흔해, 콘솔 인코딩(cp949 등)에서도 깨지지 않도록 UTF-8 고정.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from .config import Config, Job
from .filters import ScoredVideo, rank_candidates
from .notify import send_summary
from .youtube_client import MissingCredentials, YouTubeClient


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def run_job(client: YouTubeClient, job: Job, dry_run: bool = False) -> list[ScoredVideo]:
    """플레이리스트 1개에 대한 큐레이션 1회 실행.

    실제로 추가한 영상 목록을 반환한다(dry-run 이거나 추가가 없으면 빈 리스트).
    """
    # 1. 대상 플레이리스트 확보
    playlist_id, created = client.get_or_create_playlist(
        job.playlist.name, job.playlist.description, job.playlist.privacy
    )
    print(
        f"플레이리스트 '{job.playlist.name}' "
        f"({'생성됨' if created else '기존'}) id={playlist_id}"
    )

    # 2. 이미 들어있는 영상 (중복 방지)
    # 방금 생성한 플레이리스트는 비어 있고, API 전파 지연으로 조회 시 404가 날 수 있어 건너뛴다.
    if created:
        existing: set[str] = set()
    else:
        existing = client.existing_video_ids(playlist_id)
    print(f"기존 영상 {len(existing)}개")

    # 3. 검색어별 후보 수집
    candidate_ids: list[str] = []
    for query in job.queries:
        ids = client.search_video_ids(query, job.run.candidates_per_query)
        print(f"  검색 '{query}' -> {len(ids)}개 후보")
        candidate_ids.extend(ids)

    # 중복 ID 제거(순서 유지)
    unique_ids = list(dict.fromkeys(candidate_ids))
    print(f"고유 후보 {len(unique_ids)}개")

    if not unique_ids:
        print("후보가 없습니다.")
        return []

    # 4. 상세 조회 + 채점/필터
    details = client.videos_details(unique_ids)
    ranked = rank_candidates(details, job.filters, exclude_ids=existing)
    print(f"필터 통과 {len(ranked)}개")

    # 5. 상위 N개 선정
    selected: list[ScoredVideo] = ranked[: job.run.max_additions]
    if not selected:
        print("추가할 영상이 없습니다.")
        return []

    print(f"\n추가 대상 {len(selected)}개:")
    for v in selected:
        print(
            f"  [{v.score}] {v.title}  ({_fmt_duration(v.duration_seconds)})"
            f" — {v.channel}\n      {v.url}  {' '.join(v.reasons)}"
        )

    if dry_run:
        print("\n[dry-run] 실제로 추가하지 않았습니다.")
        return []

    # 6. 플레이리스트 앞쪽에 추가
    # position=0 으로 삽입하면 매번 맨 앞에 들어가므로, 점수 낮은 것부터(역순) 넣어야
    # 점수 높은 영상이 최종적으로 맨 위에 온다.
    added = 0
    for v in reversed(selected):
        client.add_to_playlist(playlist_id, v.video_id, position=0)
        added += 1
    print(f"\n{added}개 영상을 '{job.playlist.name}' 앞쪽에 추가했습니다.")

    # 7. 개수 상한 유지 (초과분은 맨 뒤=오래된 영상부터 삭제)
    max_size = job.playlist.max_size
    if max_size and max_size > 0:
        items = client.list_playlist_items(playlist_id)
        overflow = items[max_size:]
        removed = 0
        failed = 0
        for item in overflow:
            # 개별 항목 삭제 실패가 나머지 삭제를 막지 않도록 각각 처리한다.
            # 404(이미 삭제됨)는 remove_playlist_item 이 내부에서 건너뛰고 False 를
            # 반환하므로 실패로 세지 않는다.
            try:
                if client.remove_playlist_item(item["playlist_item_id"]):
                    removed += 1
            except HttpError as exc:
                failed += 1
                print(
                    f"  경고: 항목 {item['playlist_item_id']} 삭제 실패 — {exc}",
                    file=sys.stderr,
                )
        if overflow:
            msg = (
                f"상한({max_size}개) 초과분 {len(overflow)}개 중 "
                f"{removed}개 삭제"
            )
            if failed:
                msg += f", {failed}개 실패"
            msg += f". 현재 {len(items) - removed}개."
            print(msg)

    return selected


def run(config_path: str, dry_run: bool = False) -> int:
    cfg = Config.load(config_path)
    client = YouTubeClient()

    # 플레이리스트별 추가된 영상을 모아 마지막에 메일 1통으로 묶어 발송한다.
    added_by_playlist: dict[str, list[ScoredVideo]] = {}
    for i, job in enumerate(cfg.jobs):
        if i:
            print("\n" + "=" * 60)
        print(f"[{i + 1}/{len(cfg.jobs)}] 플레이리스트 큐레이션 시작")
        added = run_job(client, job, dry_run=dry_run)
        if added:
            added_by_playlist[job.playlist.name] = added

    # dry-run 이 아니고 실제 추가가 있었던 경우에만 요약 메일 발송.
    if not dry_run:
        send_summary(added_by_playlist)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="YouTube Work Focus Playlist Curator")
    parser.add_argument("--config", default="config.yaml", help="설정 파일 경로")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="플레이리스트를 수정하지 않고 선정 결과만 출력",
    )
    args = parser.parse_args(argv)

    try:
        return run(args.config, dry_run=args.dry_run)
    except MissingCredentials as exc:
        print(f"인증 오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
