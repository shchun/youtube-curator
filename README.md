# YouTube "Work Focus" Playlist Curator

GitHub Actions로 **매일 자동 실행**되어, 일할 때 듣기 좋은 YouTube 영상을 찾아
`Work Focus` 플레이리스트에 추가합니다. 관리 부담 없이 플레이리스트까지만 만들고 종료합니다.

- 추천 기준은 [`config.yaml`](config.yaml) 한 곳에서 관리
- "말 적고, 로우파이이고, 집중력 향상" 기준 우선 (no vocals / lo-fi / focus)
- 1회 실행 시 **최대 5개** 추가, 이미 들어있는 영상은 건너뜀

## 동작 방식

1. `config.yaml` 의 검색어로 후보 영상 수집 (search.list)
2. 영상 상세 조회 후 채점 (videos.list)
   - 길이(20분~6시간), 카테고리(Music), 선호 키워드 가점, 제외 키워드 탈락
3. 점수 높은 순으로 상위 N개를 `Work Focus` 플레이리스트에 추가
4. 종료

플레이리스트가 없으면 자동 생성합니다. 중복 방지는 플레이리스트의 기존 영상 ID로 처리하므로
별도의 상태 파일이 필요 없습니다.

## 프로젝트 구조

```
config.yaml                  # 추천 기준 (이 파일만 수정하면 됨)
requirements.txt
curator/
  config.py                  # config.yaml 로딩/검증
  youtube_client.py          # YouTube Data API 래퍼 (OAuth)
  filters.py                 # 채점/필터링
  main.py                    # 엔트리포인트
scripts/get_refresh_token.py # OAuth 리프레시 토큰 발급 (로컬 1회)
.github/workflows/curate.yml # 매일 실행 워크플로
```

## 설정 (최초 1회)

### 1. Google Cloud 준비

1. [Google Cloud Console](https://console.cloud.google.com/) 에서 프로젝트 생성
2. **YouTube Data API v3** 활성화
3. **OAuth 동의 화면** 구성 (External) — 테스트 사용자에 본인 Google 계정 추가
4. **사용자 인증 정보 → OAuth 클라이언트 ID → 데스크톱 앱** 생성
   → `client_id`, `client_secret` 확보

### 2. 리프레시 토큰 발급 (로컬)

```bash
pip install -r requirements.txt
export YOUTUBE_CLIENT_ID=...        # Windows PowerShell: $env:YOUTUBE_CLIENT_ID="..."
export YOUTUBE_CLIENT_SECRET=...
python scripts/get_refresh_token.py
```

브라우저에서 본인 계정으로 동의하면 콘솔에 세 값이 출력됩니다.

### 3. GitHub Secrets 등록

저장소 **Settings → Secrets and variables → Actions** 에 추가:

| Secret | 값 |
| --- | --- |
| `YOUTUBE_CLIENT_ID` | OAuth 클라이언트 ID |
| `YOUTUBE_CLIENT_SECRET` | OAuth 클라이언트 시크릿 |
| `YOUTUBE_REFRESH_TOKEN` | 위에서 발급한 리프레시 토큰 |

### 4. 추가 영상 알림 메일 (선택, AWS SES)

영상이 추가되면 요약을 메일로 받고 싶을 때만 설정합니다. 추가된 영상이 1개 이상일 때만,
하루 실행당 1통으로 묶어 발송합니다. (아래 secret 이 없으면 메일 발송은 자동으로 건너뜀)

1. AWS SES 에서 **발신 주소(또는 도메인)를 검증(verify)** 합니다. SES 가 샌드박스 모드라면
   **수신 주소도 검증**해야 메일이 갑니다(프로덕션 액세스를 받으면 수신 검증 불필요).
2. 발신/수신 주소·리전은 비밀이 아니라 **Actions Variables** 로 관리합니다
   (Settings → Secrets and variables → Actions → **Variables** 탭). 코드 수정 없이 바꿀 수 있습니다.

| Variable | 값 (예) |
| --- | --- |
| `SES_FROM_EMAIL` | `seunghyo.chun@precipi.com` (SES 에서 검증된 발신 주소) |
| `SES_TO_EMAIL` | `seunghyo.chun@gmail.com` (생략하면 발신 주소와 동일) |
| `AWS_REGION` | `us-east-1` (SES 가 설정된 리전) |

3. **비밀인 AWS 자격증명 2개만** Actions **Secrets** 에 추가합니다:

| Secret | 값 |
| --- | --- |
| `AWS_ACCESS_KEY_ID` | `ses:SendEmail` 권한이 있는 IAM 자격증명 |
| `AWS_SECRET_ACCESS_KEY` | 〃 |

### 5. 추가 영상 알림 Slack (선택, Incoming Webhook)

영상이 추가되면 Slack 채널로도 요약을 받고 싶을 때만 설정합니다. 메일과 동일하게
추가된 영상이 1개 이상일 때만, 하루 실행당 1번 발송합니다. (아래 secret 이 없으면
Slack 발송은 자동으로 건너뜀) 메일과 병행 사용 가능하며, 둘 중 하나만 켜도 됩니다.

1. Slack [API 앱](https://api.slack.com/apps) → **Create New App** → From scratch
2. **Incoming Webhooks** 활성화 → **Add New Webhook to Workspace** 로 알림 받을 채널 선택
3. 생성된 `https://hooks.slack.com/services/...` URL 을 **Secret** 으로 등록합니다
   (URL 자체가 비밀이므로 Variables 가 아니라 Secrets):

| Secret | 값 |
| --- | --- |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL |

`gh` CLI 로 등록하려면:

```bash
gh secret set SLACK_WEBHOOK_URL   # 프롬프트에 URL 붙여넣기 (셸 히스토리에 안 남음)
```

## 로컬 실행

```bash
# 실제 추가 없이 선정 결과만 확인
python -m curator.main --config config.yaml --dry-run

# 실제로 플레이리스트에 추가
python -m curator.main --config config.yaml
```

(로컬 실행에도 위 3개 환경변수가 필요합니다.)

## 자동 실행

[`.github/workflows/curate.yml`](.github/workflows/curate.yml) 가 매일 **05:00 KST**(UTC 20:00)에 실행됩니다.
Actions 탭에서 **Run workflow** 로 수동 실행도 가능하며, `dry_run` 옵션을 켜면 추가 없이 결과만 확인합니다.

## 추천 기준 조정

[`config.yaml`](config.yaml) 에서:

- `queries`: 검색어 목록
- `run.max_additions`: 1회 추가 개수 (기본 5)
- `playlist.max_size`: 플레이리스트 최대 영상 수. 새 영상은 **맨 앞**에 추가되고, 초과분은 맨 뒤(오래된 것)부터 삭제 (기본 30, `0`=무제한)
- `filters.prefer_keywords` / `exclude_keywords`: 가점/탈락 키워드
- `filters.min_duration_seconds` / `max_duration_seconds`: 영상 길이 범위
- `filters.min_score`: 통과 최소 점수

## API 할당량 참고

YouTube Data API 기본 일일 할당량은 10,000 units입니다.
`search.list` 는 호출당 100 units(검색어 수만큼), `videos.list` 는 1 unit,
`playlistItems.insert` 는 50 units입니다. 기본 설정(검색어 5개)이면 하루 약 600~800 units로 넉넉합니다.
