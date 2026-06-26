"""내 YouTube 채널의 플레이리스트 목록을 출력하는 테스트 스크립트.

실행:
  python scripts/list_playlists.py

필요한 환경변수 (.env 또는 셸 환경):
  YOUTUBE_CLIENT_ID
  YOUTUBE_CLIENT_SECRET
  YOUTUBE_REFRESH_TOKEN   # scripts/get_refresh_token.py 로 발급

리포지토리 루트의 .env 파일이 있으면 자동으로 읽어들인다(python-dotenv 불필요).
각 플레이리스트의 제목 / 영상 개수 / 공개범위 / ID 를 표로 보여준다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# curator 패키지를 import 할 수 있도록 리포지토리 루트를 경로에 추가.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 콘솔 인코딩(cp949 등)에서도 이모지/한글 제목이 깨지지 않도록 UTF-8 고정.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _load_dotenv(path: Path) -> None:
    """아주 단순한 .env 로더 (KEY=VALUE 한 줄씩). 이미 설정된 환경변수는 덮어쓰지 않는다."""
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


def main() -> int:
    _load_dotenv(ROOT / ".env")

    from curator.youtube_client import MissingCredentials, YouTubeClient

    try:
        client = YouTubeClient()
    except MissingCredentials as exc:
        print(f"인증 오류: {exc}", file=sys.stderr)
        print(
            "\n리프레시 토큰이 없으면 먼저 발급하세요:\n"
            "  python scripts/get_refresh_token.py\n"
            "그리고 출력된 YOUTUBE_REFRESH_TOKEN 값을 .env 에 추가하세요.",
            file=sys.stderr,
        )
        return 2

    playlists: list[dict] = []
    page_token = None
    while True:
        resp = (
            client.api.playlists()
            .list(
                part="snippet,contentDetails,status",
                mine=True,
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )
        playlists.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    if not playlists:
        print("플레이리스트가 없습니다.")
        return 0

    print(f"플레이리스트 {len(playlists)}개\n")
    for i, pl in enumerate(playlists, 1):
        title = pl["snippet"]["title"]
        count = pl["contentDetails"]["itemCount"]
        privacy = pl["status"]["privacyStatus"]
        pid = pl["id"]
        print(f"{i:2}. {title}")
        print(f"    영상 {count}개 · {privacy} · id={pid}")
        print(f"    https://www.youtube.com/playlist?list={pid}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
