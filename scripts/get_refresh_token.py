"""로컬에서 한 번만 실행해 YouTube OAuth 리프레시 토큰을 발급받는 헬퍼.

사전 준비:
  1. Google Cloud Console 에서 프로젝트 생성 후 "YouTube Data API v3" 활성화
  2. OAuth 동의 화면 구성 (External, 테스트 사용자에 본인 계정 추가)
  3. "사용자 인증 정보 > OAuth 클라이언트 ID > 데스크톱 앱" 생성
  4. 받은 client_id / client_secret 를 환경변수로 지정하거나 아래 입력 프롬프트에 입력

실행:
  pip install google-auth-oauthlib
  python scripts/get_refresh_token.py

브라우저가 열리고 본인 Google 계정으로 동의하면, 콘솔에 리프레시 토큰이 출력된다.
이 값을 GitHub Secret(YOUTUBE_REFRESH_TOKEN)으로 저장한다.
"""

from __future__ import annotations

import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube"]


def main() -> None:
    client_id = os.environ.get("YOUTUBE_CLIENT_ID") or input("Client ID: ").strip()
    client_secret = (
        os.environ.get("YOUTUBE_CLIENT_SECRET") or input("Client Secret: ").strip()
    )

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # access_type=offline + prompt=consent 로 리프레시 토큰을 확실히 받는다.
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent"
    )

    print("\n=== GitHub Secrets 에 저장하세요 ===")
    print(f"YOUTUBE_CLIENT_ID     = {client_id}")
    print(f"YOUTUBE_CLIENT_SECRET = {client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN = {creds.refresh_token}")


if __name__ == "__main__":
    main()
