"""YouTube Data API v3 래퍼.

읽기(search/videos)와 쓰기(playlist insert) 모두 OAuth 사용자 자격증명을 쓴다.
GitHub Actions 에서는 환경변수로 주입된 리프레시 토큰으로 액세스 토큰을 갱신한다.

필요한 환경변수:
  YOUTUBE_CLIENT_ID
  YOUTUBE_CLIENT_SECRET
  YOUTUBE_REFRESH_TOKEN
"""

from __future__ import annotations

import os
from typing import Iterable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/youtube"]


class MissingCredentials(RuntimeError):
    pass


def _credentials_from_env() -> Credentials:
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    missing = [
        name
        for name, val in [
            ("YOUTUBE_CLIENT_ID", client_id),
            ("YOUTUBE_CLIENT_SECRET", client_secret),
            ("YOUTUBE_REFRESH_TOKEN", refresh_token),
        ]
        if not val
    ]
    if missing:
        raise MissingCredentials(
            "다음 환경변수가 필요합니다: " + ", ".join(missing)
        )
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=TOKEN_URI,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


class YouTubeClient:
    def __init__(self, credentials: Credentials | None = None):
        creds = credentials or _credentials_from_env()
        self.api = build("youtube", "v3", credentials=creds, cache_discovery=False)

    # --- 플레이리스트 ---------------------------------------------------

    def find_playlist_id(self, name: str) -> str | None:
        """내 채널에서 이름이 일치하는 플레이리스트 ID 를 찾는다."""
        page_token = None
        while True:
            resp = (
                self.api.playlists()
                .list(part="snippet", mine=True, maxResults=50, pageToken=page_token)
                .execute()
            )
            for item in resp.get("items", []):
                if item["snippet"]["title"] == name:
                    return item["id"]
            page_token = resp.get("nextPageToken")
            if not page_token:
                return None

    def create_playlist(self, name: str, description: str, privacy: str) -> str:
        resp = (
            self.api.playlists()
            .insert(
                part="snippet,status",
                body={
                    "snippet": {"title": name, "description": description},
                    "status": {"privacyStatus": privacy},
                },
            )
            .execute()
        )
        return resp["id"]

    def get_or_create_playlist(
        self, name: str, description: str, privacy: str
    ) -> tuple[str, bool]:
        existing = self.find_playlist_id(name)
        if existing:
            return existing, False
        return self.create_playlist(name, description, privacy), True

    def list_playlist_items(self, playlist_id: str) -> list[dict]:
        """플레이리스트 항목을 position 순서대로 반환.

        각 원소: {"playlist_item_id": ..., "video_id": ..., "position": ...}
        """
        items: list[dict] = []
        page_token = None
        while True:
            resp = (
                self.api.playlistItems()
                .list(
                    part="contentDetails,snippet",
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=page_token,
                )
                .execute()
            )
            for item in resp.get("items", []):
                items.append(
                    {
                        "playlist_item_id": item["id"],
                        "video_id": item["contentDetails"]["videoId"],
                        "position": item["snippet"]["position"],
                    }
                )
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        items.sort(key=lambda x: x["position"])
        return items

    def existing_video_ids(self, playlist_id: str) -> set[str]:
        """플레이리스트에 이미 들어있는 영상 ID 집합 (중복 추가 방지)."""
        return {item["video_id"] for item in self.list_playlist_items(playlist_id)}

    def add_to_playlist(
        self, playlist_id: str, video_id: str, position: int | None = None
    ) -> None:
        snippet: dict = {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
        # position 을 지정하면 해당 위치에 삽입(0 = 맨 앞), 없으면 맨 뒤에 추가.
        if position is not None:
            snippet["position"] = position
        self.api.playlistItems().insert(
            part="snippet", body={"snippet": snippet}
        ).execute()

    def remove_playlist_item(self, playlist_item_id: str) -> None:
        self.api.playlistItems().delete(id=playlist_item_id).execute()

    # --- 검색 / 영상 상세 -----------------------------------------------

    def search_video_ids(self, query: str, max_results: int) -> list[str]:
        resp = (
            self.api.search()
            .list(
                part="id",
                q=query,
                type="video",
                maxResults=min(max_results, 50),
                order="relevance",
                videoEmbeddable="true",
            )
            .execute()
        )
        return [
            item["id"]["videoId"]
            for item in resp.get("items", [])
            if item.get("id", {}).get("videoId")
        ]

    def videos_details(self, video_ids: Iterable[str]) -> list[dict]:
        """videos.list 로 snippet + contentDetails + statistics 를 가져온다."""
        ids = list(video_ids)
        results: list[dict] = []
        for i in range(0, len(ids), 50):
            batch = ids[i : i + 50]
            resp = (
                self.api.videos()
                .list(
                    part="snippet,contentDetails,statistics,status",
                    id=",".join(batch),
                )
                .execute()
            )
            results.extend(resp.get("items", []))
        return results
