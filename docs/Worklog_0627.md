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

## 데이터 분석 · 클러스터링 플랫폼 설계서 작성

플레이리스트 데이터를 입력으로 임베딩→클러스터링→시각화하는 분석 플랫폼 설계서(`docs/Plan-data-analysis-platform.md`)를 작성·리뷰했다. (구현은 아직, 문서 단계)

### 한 일
- 기존 "로그 데이터 클러스터링" 템플릿을 **유튜브 플레이리스트 분석**용으로 전면 개편.
- 파이프라인 확정: 수집(`playlistItems.list`) → **상세 보강(`videos.list` 50개 배치)** → 단일 `videos` 테이블 UPSERT → 임베딩 → 클러스터링(KMeans/HDBSCAN) → UMAP 2D 투영 → Streamlit 시각화.
- 여러 차례 리뷰하며 설계 결정을 닫음.

### 주요 결정
- **임베딩:** OpenAI `text-embedding-3-large` 를 `dimensions=1536` 으로 호출 → `embedding VECTOR(1536)` (pgvector HNSW 한도 2000 이내). 키는 루트 `.env` 의 `OPENAI_API_KEY`. (대안: 로컬 무료 `ko-sroberta`/`bge-m3`)
- **스키마:** 단일 `videos` 테이블, **`video_id` PK** + **`source_playlists` JSONB**(여러 플레이리스트 출처를 배열로). PK 충돌로 자연 dedup, 임베딩·클러스터링 영상당 1회.
- **인프라:** 로컬 Docker Compose(`pgvector/pgvector:pg16`), DB 비번 로컬 기본값.
- **시각화:** Streamlit(최종) + Superset(임시 탐색 옵션).
- **디렉터리:** 신규 분석 코드 일체를 **`analysis/` 폴더** 신설(collect/enrich/embed/cluster/db/run_pipeline/dashboard + `db/init`). 기존 `curator/youtube_client.py` 만 재사용.
- 비공개·삭제 영상은 저장 안 함(누락 수만 로깅), 카테고리는 id→이름 변환해 `category` 컬럼에 저장.

### 알게 된 것 / 리뷰로 잡은 함정
- **UPSERT 재실행 함정(§4.4):** 순진한 `DO UPDATE = EXCLUDED.*` 는 ① 파생 컬럼(embedding/cluster/umap)을 NULL 로 덮어쓰고 ② `source_playlists` 를 병합 대신 덮어씀 → 수집 컬럼만 갱신하고 source_playlists 는 `기존 || 신규` 후 dedup 하도록 SQL 예시를 문서에 명시.
- 임베딩은 **`embedding IS NULL` 행만** 호출(멱등, 비용 절감).
- `videos.list` 응답 타입 주의: `caption`/`categoryId` 는 문자열, `duration` ISO8601 엣지값(`P0D`), 통계 키 부재 → 방어 파싱.
- `videos.list` 는 `id` 와 함께 쓰면 `maxResults` 가 무시됨.
- pgvector HNSW 인덱스는 최대 2000차원 → `3-large`(3072)는 `dimensions=1536` 축소로 인덱스 사용 가능.
