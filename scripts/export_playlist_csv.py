"""플레이리스트(또는 좋아요/업로드)의 동영상 목록을 CSV 로 내보내는 스크립트.

실행 예:
  python scripts/export_playlist_csv.py --likes -o liked.csv
  python scripts/export_playlist_csv.py --uploads -o uploads.csv
  python scripts/export_playlist_csv.py --id PLZBDMucXmsppNRERgnzyRD-GMKC8T8BMD -o work_focus.csv
  python scripts/export_playlist_csv.py --name "영화" -o movies.csv
  python scripts/export_playlist_csv.py --likes --limit 100 -o liked_top100.csv

-o 를 생략하면 표준출력(stdout)으로 CSV 를 내보낸다.
CSV 는 utf-8-sig(BOM 포함)로 저장해 Excel 에서 한글이 깨지지 않는다.

필요한 환경변수 (.env 또는 셸 환경):
  YOUTUBE_CLIENT_ID
  YOUTUBE_CLIENT_SECRET
  YOUTUBE_REFRESH_TOKEN
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _load_dotenv(path: Path) -> None:
    """단순 .env 로더 (KEY=VALUE). 이미 설정된 환경변수는 덮어쓰지 않는다."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


FIELDS = ["index", "video_id", "title", "channel", "published_at", "position", "url"]


def _fetch_rows(client, playlist_id: str, limit: int = 0) -> list[dict]:
    """플레이리스트 항목을 페이지네이션으로 모두 모아 CSV 행(dict) 리스트로 반환."""
    rows: list[dict] = []
    page_token = None
    while True:
        resp = (
            client.api.playlistItems()
            .list(
                part="snippet,contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )
        for item in resp.get("items", []):
            sn = item["snippet"]
            vid = item["contentDetails"]["videoId"]
            rows.append(
                {
                    "index": len(rows) + 1,
                    "video_id": vid,
                    "title": sn.get("title", ""),
                    "channel": sn.get("videoOwnerChannelTitle") or sn.get("channelTitle", ""),
                    "published_at": item["contentDetails"].get("videoPublishedAt", ""),
                    "position": sn.get("position", ""),
                    "url": f"https://www.youtube.com/watch?v={vid}",
                }
            )
        if limit and len(rows) >= limit:
            return rows[:limit]
        page_token = resp.get("nextPageToken")
        if not page_token:
            return rows


def _write_csv(rows: list[dict], out_path: Path) -> None:
    """utf-8-sig(BOM 포함)로 저장해 Excel 에서 한글이 깨지지 않게 한다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _safe_filename(name: str) -> str:
    """플레이리스트 제목을 파일명으로 안전하게 변환 (윈도/유닉스 금지문자 제거)."""
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad else c for c in name).strip().strip(".")
    return cleaned or "untitled"


def _export_all(client, outdir: Path, limit: int) -> int:
    """내 플레이리스트 전체 + 좋아요 + 업로드를 각각 CSV 파일로 내보낸다."""
    targets: list[tuple[str, str]] = []  # (파일명 stem, playlist_id)

    # 시스템 플레이리스트(좋아요/업로드)
    related = (
        client.api.channels()
        .list(part="contentDetails", mine=True)
        .execute()["items"][0]["contentDetails"]["relatedPlaylists"]
    )
    if related.get("likes"):
        targets.append(("좋아요", related["likes"]))
    if related.get("uploads"):
        targets.append(("업로드", related["uploads"]))

    # 내가 만든 플레이리스트 전체
    page_token = None
    while True:
        resp = (
            client.api.playlists()
            .list(part="snippet", mine=True, maxResults=50, pageToken=page_token)
            .execute()
        )
        for pl in resp.get("items", []):
            targets.append((pl["snippet"]["title"], pl["id"]))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    date = datetime.now().strftime("%Y%m%d")
    print(f"총 {len(targets)}개 플레이리스트를 {outdir} 에 내보냅니다.\n", file=sys.stderr)
    for name, pid in targets:
        rows = _fetch_rows(client, pid, limit)
        out_path = outdir / f"{_safe_filename(name)}_{date}.csv"
        _write_csv(rows, out_path)
        print(f"  {name}: {len(rows)}개 → {out_path}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="플레이리스트 동영상을 CSV 로 내보내기")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--id", help="플레이리스트 ID")
    src.add_argument("--name", help="플레이리스트 이름 (내 채널에서 검색)")
    src.add_argument("--likes", action="store_true", help="좋아요 표시한 동영상")
    src.add_argument("--uploads", action="store_true", help="내가 업로드한 동영상")
    src.add_argument(
        "--all",
        action="store_true",
        help="내 플레이리스트 전체 + 좋아요 + 업로드를 각각 파일로 내보내기",
    )
    parser.add_argument("-o", "--output", help="저장할 CSV 경로 (생략 시 stdout)")
    parser.add_argument(
        "--outdir", default="data", help="--all 일 때 저장 폴더 (기본: data)"
    )
    parser.add_argument("--limit", type=int, default=0, help="개수 제한 (0=전체)")
    args = parser.parse_args(argv)

    _load_dotenv(ROOT / ".env")

    from curator.youtube_client import MissingCredentials, YouTubeClient

    try:
        client = YouTubeClient()
    except MissingCredentials as exc:
        print(f"인증 오류: {exc}", file=sys.stderr)
        return 2

    # --all: 여러 파일로 일괄 내보내고 종료
    if args.all:
        outdir = Path(args.outdir)
        if not outdir.is_absolute():
            outdir = ROOT / outdir
        return _export_all(client, outdir, args.limit)

    # 단일 소스 → 플레이리스트 ID 확정
    if args.likes or args.uploads:
        related = (
            client.api.channels()
            .list(part="contentDetails", mine=True)
            .execute()["items"][0]["contentDetails"]["relatedPlaylists"]
        )
        playlist_id = related.get("likes" if args.likes else "uploads")
        if not playlist_id:
            print("해당 시스템 플레이리스트가 없습니다.", file=sys.stderr)
            return 1
    elif args.name:
        playlist_id = client.find_playlist_id(args.name)
        if not playlist_id:
            print(f"'{args.name}' 플레이리스트를 찾을 수 없습니다.", file=sys.stderr)
            return 1
    else:
        playlist_id = args.id

    rows = _fetch_rows(client, playlist_id, args.limit)

    # CSV 출력 (파일이면 utf-8-sig, 아니면 stdout)
    if args.output:
        out_path = Path(args.output)
        _write_csv(rows, out_path)
        print(f"{len(rows)}개 행을 {out_path} 에 저장했습니다.", file=sys.stderr)
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
