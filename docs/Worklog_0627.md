# Worklog 2026-06-27

## 플레이리스트 조회 / CSV 내보내기 스크립트 추가

내 YouTube 계정의 플레이리스트와 동영상을 살펴보기 위한 탐색용 스크립트를 `scripts/` 에 작성했다.

### 한 일
- **`scripts/list_playlists.py`** — 내 채널의 플레이리스트 목록(제목·영상 개수·공개범위·ID·URL)을 출력. `playlists().list(mine=True)` 사용, 페이지네이션 처리.
  - 결과: 내가 만든 플레이리스트 10개 확인.
- **`scripts/export_playlist_csv.py`** — 플레이리스트/좋아요/업로드 동영상을 CSV 로 내보내는 통합 스크립트.
  - 소스 선택: `--id` / `--name` / `--likes` / `--uploads` / `--all`
  - `--all` 은 내 플레이리스트 전체 + 좋아요 + 업로드를 각각 `data/<제목>_YYYYMMDD.csv` 로 저장 (총 12개).
  - Excel 한글 호환을 위해 `utf-8-sig`(BOM) 저장, 표준 `csv` 모듈로 콤마/줄바꿈 안전 처리.
  - 파일명 안전화(`_safe_filename`), 저장 폴더 `--outdir` (기본 `data/`).

### 알게 된 것
- **시청기록(watch history)·나중에 볼 동영상(Watch Later)** 은 YouTube Data API v3 로 접근 불가 (구글이 2016년경 막음). Google Takeout 이 유일한 경로.
- **좋아요(LL)·업로드(UU)** 는 `channels().relatedPlaylists` 로 접근 가능 — `playlists().list(mine=True)` 결과에는 안 나오는 시스템 플레이리스트.
- 좋아요 표시한 동영상은 총 **3,023개**.
- 옛날(2008~2012) 플레이리스트는 ID 가 짧은 형식(`PL` + 16자리 hex), 이후는 긴 base64 형식(`PL` + 32자).

### 정리
- `.gitignore` 에 `data/` 추가 (내보낸 CSV 는 커밋하지 않음).
- 동영상 목록 조회 스크립트 3개(`list_liked_videos` / `list_uploaded_videos` / `list_playlist_videos`)는 `export_playlist_csv.py` 에 흡수되어 삭제.
- 자격증명은 환경변수에서만 읽으므로, 각 스크립트가 리포 루트 `.env` 를 단순 파싱해 로드(python-dotenv 불필요).
