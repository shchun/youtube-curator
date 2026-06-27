# 프로젝트 설계서: 유튜브 플레이리스트 데이터 분석 · 클러스터링 플랫폼

## 1. 개요 (Objective)
내 유튜브 플레이리스트(좋아요 / 업로드 / 직접 만든 재생목록)에 담긴 동영상을 수집·정제하고,
제목·설명·태그를 임베딩하여 벡터화한 뒤 클러스터링으로 자동 주제 그룹을 만든다.
이를 통해 "이 재생목록은 어떤 주제들로 구성돼 있는가", "비슷한 영상끼리 어떻게 묶이는가"를
대시보드에서 한눈에 파악하는 것이 목표다.

기존 `scripts/export_playlist_csv.py` 는 동영상의 **얕은 메타데이터**(제목·채널·게시일)만 내보낸다.
본 플랫폼은 여기에 `videos.list` 일괄 조회로 **조회수·길이·태그·카테고리** 등 풍부한 필드를 덧붙여
분석 가치가 높은 테이블을 구성한다.

## 2. 기술 스택 (Tech Stack)
* **Input Source:** YouTube Data API v3 (`playlistItems.list`, `videos.list`)
* **Database:** PostgreSQL (with `pgvector` extension) — 로컬 Docker Compose 로 구동 (§5 참조)
* **Container:** Docker / Docker Compose (`pgvector/pgvector` 이미지)
* **Language:** Python
* **Libraries:** `google-api-python-client`(기존 `curator` 패키지 재사용), `openai`, `pandas`, `numpy`,
  `scikit-learn`(KMeans/DBSCAN/HDBSCAN/지표), `umap-learn`(2D 투영),
  `SQLAlchemy` + `psycopg[binary]`(DB 드라이버) + `pgvector`(SQLAlchemy `Vector` 타입),
  `streamlit` + `plotly`(시각화)
  - HDBSCAN 은 scikit-learn 1.3+ 의 `sklearn.cluster.HDBSCAN` 사용(별도 `hdbscan` 패키지 불필요).
* **Embedding Model:** OpenAI `text-embedding-3-large` (`dimensions=1536` 으로 축소 호출) — API, 유료(저비용)
  - 8191토큰까지 입력 → 긴 `description` 도 잘림 없이 반영. 1536차원이라 pgvector HNSW 인덱스 사용 가능.
  - 키는 `.env` 의 `OPENAI_API_KEY` 로 주입 (§5.4).
* **Visualization (최종):** Streamlit — Python 분석 코드를 그대로 재사용해 클러스터 2D 산점도·필터·영상 테이블 제공
* **Visualization (탐색·옵션):** Apache Superset — 필요 시 임시로 세워 SQL 집계/조회수 대시보드 탐색 (§6.5)
* **IDE/Workflow:** VS Code (Jupyter Notebook, Database Client 확장)

## 3. 데이터 파이프라인 설계 (Data Pipeline)
1. **Collect (수집):** `playlistItems.list` 로 플레이리스트의 `video_id` 목록을 페이지네이션으로 모은다.
   (기존 `export_playlist_csv.py` 의 `_fetch_rows` 로직 재사용)
2. **Enrich (상세 보강):** 모은 `video_id` 를 **50개씩 묶어** `videos.list` 한 번에 호출하여
   조회수·길이·태그·카테고리 등 상세 필드를 받아온다. — 본 설계의 핵심 개선점 (§3.1 참조)
3. **Ingestion (적재):** 보강된 레코드를 단일 `videos` 테이블로 **`video_id` 기준 UPSERT**.
   같은 영상이 여러 플레이리스트에서 수집돼도 한 행으로 병합되고(자연 dedup), 출처는
   `source_playlists` 배열에 누적된다. — 스키마 §4 참조.
4. **Embedding (임베딩):** `title + description + tags` 결합 텍스트를 OpenAI
   `text-embedding-3-large`(`dimensions=1536`)로 벡터화하여 `embedding` 컬럼에 저장. (API 다건 배치 호출)
   **`embedding IS NULL` 인 행만 호출**해 재실행 시 중복 비용을 피한다(멱등).
5. **Clustering (클러스터링):** 벡터 기반 유사도 그룹핑(KMeans / DBSCAN / HDBSCAN) 후
   `cluster_id` / `is_outlier` 할당. — Python 스크립트로 수행 (§6 참조)
6. **Projection (2D 투영):** UMAP 으로 임베딩을 2차원으로 축소해 `umap_x` / `umap_y` 저장 (산점도용).
7. **Visualization (시각화):** Streamlit 앱에서 클러스터 산점도·대표 영상·조회수 분포 확인.
   (필요 시 Superset 을 임시로 띄워 SQL 집계 탐색 — §6.5)

### 3.1 상세 정보 일괄 조회 (videos.list 배치)
YouTube `videos.list` 는 `id` 파라미터에 **쉼표로 구분한 video_id 를 최대 50개**까지 받아
한 번의 호출로 모든 영상의 상세 정보를 반환한다. 이를 활용하면:

* **API 호출 횟수 절감:** 1,000개 영상 → 단 20회 호출 (50개 × 20).
* **테이블 컬럼 강화:** `playlistItems` 만으로는 얻을 수 없는 `statistics`(조회수·좋아요),
  `contentDetails`(길이·화질·자막 유무), `snippet`(태그·카테고리·설명) 을 채운다.
* **요청 part 구성:** `part="snippet,contentDetails,statistics,topicDetails,status"`

```text
ids = [모든 video_id]
for batch in chunks(ids, 50):          # 50개씩 분할
    resp = videos.list(
        part="snippet,contentDetails,statistics,topicDetails,status",
        id=",".join(batch),            # id 와 함께면 maxResults 는 무시되므로 생략
    )
    # resp["items"] 로 상세 필드 추출
```

> 주의: 비공개·삭제된 영상의 id 는 `items` 에서 빠진 채 반환된다. 이런 영상은 상세 정보가 없어
> 분석 가치가 없으므로 **저장하지 않고**(행 생성 안 함), 누락 개수만 로그로 남긴다.

**응답 필드 파싱 주의 (타입 변환 필요):**
- `contentDetails.caption` 은 boolean 이 아니라 문자열 `"true"`/`"false"` → `== "true"` 로 변환.
- `snippet.categoryId` 는 문자열 `"10"`. **id 는 저장하지 않고 이름으로 변환**(예: `"10"`→`"음악"`)해
  `category` 컬럼에 넣는다. 변환표는 `videoCategories.list(regionCode="KR")` 한 번 호출로 만들거나
  코드에 정적 딕셔너리로 둔다(카테고리는 ~30개로 거의 안 바뀜).
- `contentDetails.duration` 은 ISO8601(`PT#M#S`). 라이브/예정 영상은 `"P0D"`·`"PT0S"` 등 엣지값이 있으니
  파싱 실패 시 `NULL` 로 두는 방어 코드를 둔다.
- `statistics.likeCount`·`viewCount` 등은 비공개면 키 자체가 없을 수 있다 → `.get()` 으로 안전 접근.
- `tags`·`topicCategories` 는 없을 수 있다(키 부재) → 기본값 `[]`/`NULL`.

## 4. 데이터베이스 스키마 (Schema)
**단일 `videos` 테이블**(영상당 1행)로 단순하게 간다. 한 영상이 여러 플레이리스트에 속하는 관계는
별도 조인 테이블 대신 **`source_playlists` JSONB 컬럼**에 "어느 리스트에서 수집됐는지"를 배열로 담는다.
이 규모(개인용·수천 건)에서는 조인 테이블의 정합성 관리보다 단일 테이블의 단순함이 이점이 크다.

**`video_id` 를 기본키로 삼는 것이 핵심.** 같은 영상이 여러 플레이리스트에 있어도 PK 충돌로
한 행에 모이므로 (1) 임베딩·클러스터링을 영상당 **한 번만** 계산하고, (2) 여러 리스트를 동시에/반복
수집해도 `INSERT ... ON CONFLICT (video_id) DO UPDATE` 로 **자연스럽게 중복 제거**된다.

### 4.1 DDL
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE videos (
    video_id          TEXT PRIMARY KEY,            -- 영상 고유 ID (UPSERT 키)
    title             TEXT,                        -- snippet
    description       TEXT,                        -- snippet (임베딩 입력)
    channel_id        TEXT,                        -- snippet
    channel_title     TEXT,                        -- snippet
    published_at      TIMESTAMPTZ,                 -- snippet
    category          TEXT,                        -- snippet.categoryId 를 이름으로 변환해 저장 (예: "음악")
    tags              TEXT[],                      -- snippet (임베딩 입력)
    default_language  TEXT,                        -- snippet
    duration_seconds  INTEGER,                     -- contentDetails (ISO8601→초)
    definition        TEXT,                        -- contentDetails (hd/sd)
    has_caption       BOOLEAN,                     -- contentDetails
    view_count        BIGINT,                      -- statistics (NULL 허용)
    like_count        BIGINT,                      -- statistics (NULL 허용)
    comment_count     BIGINT,                      -- statistics (NULL 허용)
    topic_categories  TEXT[],                      -- topicDetails
    privacy_status    TEXT,                        -- status
    -- 수집 출처: 이 영상이 담겨 있던 플레이리스트들
    source_playlists  JSONB,                       -- [{playlist_id, title, position}, ...]
    -- 파생 (분석 단계에서 채움)
    embedding         VECTOR(1536),                -- OpenAI text-embedding-3-large (dimensions=1536)
    cluster_id        INTEGER,                     -- 클러스터 번호 (-1=이상치)
    cluster_label     TEXT,                        -- 클러스터 라벨/키워드 (분석 산출, 선택)
    is_outlier        BOOLEAN DEFAULT FALSE,
    umap_x            REAL,                        -- UMAP 2D X
    umap_y            REAL,                        -- UMAP 2D Y
    fetched_at        TIMESTAMPTZ DEFAULT now()    -- 상세 보강 시각
);

-- 인덱스
CREATE INDEX ON videos (cluster_id);
CREATE INDEX ON videos (channel_id);
CREATE INDEX ON videos USING gin (source_playlists);          -- JSONB 포함 검색
CREATE INDEX ON videos USING hnsw (embedding vector_cosine_ops); -- 적재 후 생성 권장
```

### 4.2 `source_playlists` 예시 값
```json
[
  {"playlist_id": "LL",                              "title": "좋아요",  "position": 12},
  {"playlist_id": "PLZBDMucXmsppNRERgnzyRD-GMKC8...", "title": "영화",   "position": 3}
]
```
> 같은 영상을 다른 플레이리스트에서 또 수집하면, 그 행의 `source_playlists` 배열에 **원소를 추가**(append)
> 하는 방식으로 병합한다. (UPSERT 시 기존 배열과 합치고 `playlist_id` 기준 중복 제거)

### 4.3 조회 예시 (특정 플레이리스트의 클러스터별 인기 영상)
```sql
-- "영화" 플레이리스트에서 수집된 영상만
SELECT cluster_id, cluster_label, title, view_count
FROM videos
WHERE source_playlists @> '[{"title": "영화"}]'      -- JSONB 포함 연산
ORDER BY cluster_id, view_count DESC;

-- 플레이리스트별 영상 수 집계 (배열 펼치기)
SELECT pl->>'title' AS playlist, count(*)
FROM videos v, jsonb_array_elements(v.source_playlists) AS pl
GROUP BY 1 ORDER BY 2 DESC;
```

> **트레이드오프:** 단일 테이블 + JSONB 는 적재·조회가 단순한 대신, "플레이리스트별" 집계는
> `jsonb_array_elements` 로 펼쳐야 한다(정규화 조인보다 약간 번거롭고 대규모에선 느림).
> 데이터가 수만 건을 크게 넘기거나 플레이리스트 단위 분석이 핵심이 되면 그때 조인 테이블로 재검토.

### 4.4 UPSERT 규칙 ⚠️ (재실행 시 데이터 손실 방지 — 구현 핵심)
수집을 재실행할 때 순진한 `DO UPDATE SET ... = EXCLUDED.*` 는 **두 가지를 망가뜨린다.**
1. 이미 계산해 둔 **파생 컬럼(`embedding`/`cluster_id`/`cluster_label`/`umap_x`/`umap_y`)을 NULL 로 덮어씀**
   → 임베딩 비용·클러스터링을 다시 해야 함.
2. `source_playlists` 를 **병합이 아니라 덮어씀** → 다른 플레이리스트 출처가 사라짐.

따라서 UPSERT 는 **(a) 수집 컬럼만 갱신하고 파생 컬럼은 건드리지 않으며, (b) `source_playlists` 는
기존 배열과 합친 뒤 `playlist_id` 기준으로 중복 제거**해야 한다.

```sql
INSERT INTO videos (video_id, title, description, channel_id, /* ...수집 컬럼... */, source_playlists, fetched_at)
VALUES (:video_id, :title, :description, :channel_id, /* ... */, :source_playlists, now())
ON CONFLICT (video_id) DO UPDATE SET
    title         = EXCLUDED.title,
    description   = EXCLUDED.description,
    -- ...(수집 컬럼만 나열; embedding/cluster_id/umap_* 등 파생 컬럼은 의도적으로 제외)...
    view_count    = EXCLUDED.view_count,
    fetched_at    = now(),
    -- source_playlists: 기존 || 신규 후 playlist_id 기준 중복 제거
    source_playlists = (
        SELECT jsonb_agg(DISTINCT elem)
        FROM jsonb_array_elements(
            COALESCE(videos.source_playlists, '[]'::jsonb) || EXCLUDED.source_playlists
        ) AS elem
    );
```
> `DISTINCT elem` 은 객체 전체가 동일할 때만 중복 제거한다. 같은 `playlist_id` 인데 `position` 이 바뀌면
> 둘 다 남을 수 있으니, position 변동을 무시하려면 적재 전에 코드에서 playlist_id 기준 dedup 하거나
> position 을 source_playlists 에서 빼는 방안을 검토한다.

## 5. 로컬 인프라 (Local Infrastructure — Docker Compose)
PostgreSQL + pgvector 를 로컬에 Docker Compose 로 띄운다. `ankane/pgvector` 후속인
공식 **`pgvector/pgvector`** 이미지를 쓰면 확장이 미리 빌드돼 있어 `CREATE EXTENSION` 만 하면 된다.

### 5.1 디렉터리 구성 (제안)
```text
youtube-curator/
├─ docker-compose.yml        # DB 서비스 정의 (루트에서 실행 → 루트 .env 자동 로드)
├─ .env                      # 기존 YouTube 자격증명 + DB 접속정보 + OPENAI_API_KEY (git 제외)
├─ curator/                  # 기존 패키지 — youtube_client.py 만 재사용(API 인증)
└─ analysis/                 # ★신설: 데이터 분석 플랫폼 일체
   ├─ collect.py             #   playlistItems 수집 (기존 _fetch_rows 로직 참고)
   ├─ enrich.py              #   videos.list 50개 배치 보강 + 카테고리 이름 변환
   ├─ embed.py               #   OpenAI 임베딩 (embedding IS NULL 행만)
   ├─ cluster.py             #   클러스터링 + UMAP 투영
   ├─ db.py                  #   SQLAlchemy 엔진 / UPSERT(§4.4)
   ├─ run_pipeline.py        #   진입점: 수집→보강→적재→임베딩→클러스터 일괄 실행
   ├─ dashboard.py           #   Streamlit 대시보드
   └─ db/
      └─ init/
         └─ 01_schema.sql    #   최초 기동 시 자동 실행 (확장 + 테이블 DDL)
```
> 신규 분석 코드는 전부 `analysis/` 에 모은다. API 인증 등 검증된 기존 로직만
> `curator/youtube_client.py` 에서 import 해 재사용한다(기존 `scripts/` 는 건드리지 않음).

### 5.2 docker-compose.yml (예시)
```yaml
services:
  db:
    image: pgvector/pgvector:pg16        # PostgreSQL 16 + pgvector 동봉
    container_name: yt-curator-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${DB_USER:-curator}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-curator}
      POSTGRES_DB: ${DB_NAME:-youtube_curator}
    ports:
      - "${DB_PORT:-5432}:5432"          # 로컬 5432 → 컨테이너 5432
    volumes:
      - pgdata:/var/lib/postgresql/data  # 데이터 영속화
      - ./analysis/db/init:/docker-entrypoint-initdb.d  # 최초 기동 시 *.sql 자동 실행
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-curator} -d ${DB_NAME:-youtube_curator}"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
```

> `docker-entrypoint-initdb.d` 의 스크립트는 **볼륨이 비어 있는 최초 기동에만** 실행된다.
> DDL 을 고친 뒤 다시 적용하려면 `docker compose down -v` 로 볼륨을 비우고 재기동한다.

### 5.3 analysis/db/init/01_schema.sql (요지)
```sql
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector 활성화
-- 이어서 §4 의 videos 테이블 DDL + 인덱스 작성
-- (임베딩 HNSW 인덱스는 데이터 적재 후 생성 권장)
```

### 5.4 .env 추가 항목
기존 YouTube 자격증명(`YOUTUBE_*`) 과 **같은 `.env` 파일**에 DB 접속 정보와 OpenAI 키를 더한다.
`SQLAlchemy` 접속 문자열은 이 값들로 조립한다. (`.env` 는 git 에 커밋하지 않는다 — `.gitignore` 확인)
```dotenv
# DB 접속
DB_USER=curator
DB_PASSWORD=curator
DB_NAME=youtube_curator
DB_PORT=5432
DB_HOST=localhost
# 파생: postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}

# OpenAI 임베딩 (text-embedding-3-large)
OPENAI_API_KEY=sk-...
```

### 5.5 운영 명령
```bash
docker compose up -d        # 기동 (백그라운드)
docker compose ps           # 상태 확인 (healthy 여부)
docker compose logs -f db   # 로그 추적
docker compose down         # 중지 (데이터 유지)
docker compose down -v      # 중지 + 데이터 볼륨 삭제 (스키마 재초기화 시)
```

> Superset 도 같은 Compose 에 서비스로 추가할 수 있으나, 우선 DB 만 컨테이너로 띄우고
> Superset 은 별도 도입하는 것을 권장한다(이미지·초기설정이 무거움). 추후 통합 시 §5.1 에 서비스 추가.

## 6. 분석 · 시각화 (Analysis & Visualization)
임베딩 적재까지 끝나면, 이후 **클러스터링·투영·시각화는 전부 Python 스크립트**로 수행한다.
DB(`videos`)에서 벡터를 읽어 분석하고 결과(`cluster_id`, `umap_x/y`)를 다시 DB 로 써넣는 구조다.

### 6.1 클러스터링 절차 (Python)
```text
1) 로드:    SQLAlchemy 로 videos 의 embedding 을 numpy 배열로 읽기
2) 정규화:  L2 정규화 (코사인 유사도 ≈ 정규화 후 유클리드)
3) 클러스터: KMeans / DBSCAN / HDBSCAN 중 선택 (§6.2)
4) 평가:    실루엣 점수·클러스터 수·노이즈 비율 비교 (§6.3)
5) 라벨링:  cluster_id, is_outlier 를 videos 에 UPDATE
6) 투영:    UMAP 으로 2D 축소 → umap_x, umap_y UPDATE (산점도용)
7) 해석:    클러스터별 대표 영상·키워드 추출 (§6.4)
```
> 투영(UMAP 2D)은 **시각화 전용**이다. 클러스터링은 원본 고차원 임베딩에서 수행하고,
> 2D 좌표는 화면에 점을 찍기 위한 용도로만 쓴다(2D 에서 다시 군집화하지 않는다).

### 6.2 알고리즘 선택 (KMeans vs DBSCAN vs HDBSCAN)
| 알고리즘 | 군집 수 k | 노이즈(이상치) | 군집 모양 | 특징 / 사용처 |
| --- | --- | --- | --- | --- |
| **KMeans** | 미리 지정 필요 | 없음(모두 배정) | 구형·균등 크기 가정 | 빠르고 단순. k 를 엘보우/실루엣으로 탐색. 우선 베이스라인으로 적합 |
| **DBSCAN** | 자동 | 있음(`-1`) | 임의 모양·밀도 기반 | `eps`·`min_samples` 민감. 밀도 균일할 때 |
| **HDBSCAN** | 자동 | 있음(`-1`) | 가변 밀도 | `eps` 불필요, `min_cluster_size` 만. 주제 밀도가 제각각인 플레이리스트에 권장 |

> 권장 진행: **KMeans 로 빠르게 베이스라인 → HDBSCAN 으로 노이즈·가변밀도 처리**를 비교.
> 결과 비교가 쉽도록 각 실행에 알고리즘·하이퍼파라미터를 함께 로깅한다.

### 6.3 평가 지표
- **실루엣 점수(silhouette):** 군집 응집도/분리도 (−1~1, 높을수록 좋음).
- **클러스터 수 / 노이즈 비율:** DBSCAN·HDBSCAN 의 `-1` 비중이 과하면 파라미터 재조정.
- **KMeans k 탐색:** 엘보우(inertia) + 실루엣을 함께 보고 결정.

### 6.4 클러스터 해석 (라벨 붙이기)
- **대표 영상:** 각 클러스터 중심(centroid)에 가장 가까운 영상 N개 → 클러스터 성격 파악.
- **키워드:** 클러스터별 `title+tags` 에 c-TF-IDF(또는 단순 빈도)로 상위 단어 추출 → 사람이 읽을 라벨 후보.
- (선택) 추출한 라벨을 `videos.cluster_label` 컬럼에 저장해 시각화에서 표시.

### 6.5 시각화 (Streamlit 우선, Superset 옵션)
**최종 화면은 Streamlit 단일 앱**으로 구성한다. 분석 스크립트와 같은 라이브러리(pandas/plotly)를
재사용하므로 별도 BI 인프라가 필요 없다.

- 구성 요소
  - **클러스터 산점도:** `umap_x/umap_y` 를 점으로, `cluster_id` 로 색상. 점에 마우스 올리면 제목/채널/조회수 표시(Plotly).
  - **사이드바 필터:** 채널·클러스터·최소 조회수·영상 길이 범위.
  - **클러스터 상세 테이블:** 선택한 클러스터의 대표 영상·키워드·조회수 정렬.
- 실행: `streamlit run analysis/dashboard.py` (DB 접속은 §5.4 의 `.env` 값 재사용).

> **Superset(옵션):** 조회수·카테고리별 정형 집계 대시보드를 공유·탐색하고 싶을 때
> Compose 에 임시 서비스로 띄워 같은 `videos` 테이블을 SQL 로 분석할 수 있다.
> 단, 2D 임베딩 산점도는 Superset 에서 약하므로 **상시 운영보다 임시 탐색용**으로 둔다.
> Streamlit 이 버겁거나 부족하다고 판단되면 이 단계에서 Superset 으로 재검토한다.

## 7. 구현 단계 (Action Items)
- [ ] **Step 1:** Docker Compose 로 PostgreSQL + `pgvector` 기동 (§5), `analysis/db/init/01_schema.sql` 에 `videos` DDL 작성
- [ ] **Step 2:** `playlistItems.list` 수집 모듈 (기존 `_fetch_rows` 재활용)
- [ ] **Step 3:** `videos.list` 50개 배치 보강 모듈 + ISO8601 길이 파싱
- [ ] **Step 4:** DB UPSERT 적재 스크립트 (video_id 충돌 시 갱신)
- [ ] **Step 5:** OpenAI 임베딩 호출(`embedding IS NULL` 인 행만) 및 `embedding` 저장
- [ ] **Step 6:** 클러스터링 스크립트 — KMeans 베이스라인 + HDBSCAN 비교, `cluster_id`/`is_outlier` 업데이트 (§6)
- [ ] **Step 7:** UMAP 2D 투영 → `umap_x`/`umap_y` 업데이트, 클러스터 라벨/키워드 추출
- [ ] **Step 8:** Streamlit 대시보드(`analysis/dashboard.py`) — 산점도·필터·클러스터 상세
- [ ] **Step 9 (옵션):** Superset 임시 기동 — SQL 집계 탐색이 필요할 때만 (§6.5)

## 8. 검증 전략 (Validation)
- `docker compose ps` 로 DB 가 `healthy` 상태인지, `\dx` 로 `vector` 확장이 설치됐는지 확인.
- 단일 플레이리스트(예: 좋아요 상위 50개)로 수집→보강→적재 전 과정 사전 테스트.
- 요청한 video_id 수와 `videos.list` 응답 수를 대조해 누락(비공개/삭제) 비율 확인.
- VS Code Database Client 로 `GROUP BY cluster_id` 쿼리 검증 (클러스터별 대표 제목·평균 조회수).
- 이상치(`cluster_id = -1`) 분포 확인 및 HDBSCAN `min_cluster_size` 튜닝.
- KMeans `k` 후보별 실루엣 점수를 비교해 합리적인 군집 수인지 검증.
- Streamlit 산점도에서 같은 색(클러스터) 점들이 실제로 비슷한 주제 영상인지 육안 확인.

## 9. 결정 사항 · 미결 사항 (Decisions & Open Questions)
- **[결정] 임베딩 모델·차원:** OpenAI `text-embedding-3-large` 를 `dimensions=1536` 으로 호출 → `embedding VECTOR(1536)`.
  - 키는 `.env` 의 `OPENAI_API_KEY`. 8191토큰까지 반영해 긴 `description` 도 잘리지 않음.
  - **비용:** 영상 수천 건 × 수백 토큰 ≈ 1~2M 토큰 → 1회 임베딩에 수 센트 수준(요율은 가격표 확인).
  - **대안(무료·로컬):** API 사용을 피하고 싶으면 `jhgan/ko-sroberta-multitask`(768) 또는 `bge-m3`(1024)로 전환 가능.
    전환 시 `embedding VECTOR(N)` 차원을 모델에 맞춰 변경.
  - **주의:** 임베딩 입력 텍스트가 외부(OpenAI)로 전송됨. 비공개 영상 메타데이터 전송이 꺼려지면 로컬 모델 사용.
- **API 할당량(Quota):** `playlistItems.list`·`videos.list` 각 호출 1 unit. 일일 기본 10,000 unit 내 운용 가능하나
  대량 재수집 시 주기/캐싱 정책 필요.
- **갱신 주기:** 조회수 등 통계는 시간에 따라 변하므로 스냅샷 재수집 주기를 정할지 결정 (`fetched_at` 활용).
- **[결정] 비공개/삭제 영상:** `videos.list` 에서 빠지는 영상은 **저장하지 않고**(행 생성 안 함) 누락 개수만 로깅.
- **[결정] 카테고리:** `categoryId`(숫자)는 버리고 **이름으로 변환해 `category TEXT` 컬럼에 저장**.
  변환표는 `videoCategories.list(regionCode="KR")` 1회 호출 또는 정적 딕셔너리(§3.1).
- **[결정] 모듈 디렉터리:** 신규 분석 코드 일체를 **`analysis/` 폴더**에 신설(수집·보강·임베딩·클러스터·대시보드·`db/init`).
  기존 `curator/youtube_client.py`(API 인증)만 import 재사용 (§5.1).
- **[결정] DB 비밀번호:** 로컬 전용이라 기본값 `curator` 로 충분. 포트(5432)를 외부에 노출하지만 않으면 됨.
