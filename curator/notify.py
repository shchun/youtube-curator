"""추가된 영상 요약을 AWS SES 로 메일 발송.

SES 로 검증된 발신 주소(Source)에서 수신 주소로 메일을 보낸다.
(발신 주소 검증/SES 설정은 AWS 콘솔에서 미리 해 둔다.)

필요한 환경변수:
  SES_FROM_EMAIL         발신 주소(SES 에서 검증된 주소). 없으면 메일 발송을 건너뛴다.
  SES_TO_EMAIL           수신 주소. 없으면 발신 주소와 동일하게 보낸다.
  AWS_REGION             (또는 AWS_DEFAULT_REGION) SES 가 설정된 리전.
  AWS_ACCESS_KEY_ID      AWS 자격증명 (boto3 가 자동 인식).
  AWS_SECRET_ACCESS_KEY

영상이 1개 이상 추가됐을 때만 호출하면 되며, 하루 1회 실행되므로
메일도 하루 1통으로 묶여 나간다.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from .filters import ScoredVideo

# 한국 표준시 (UTC+9). 실행 시각이 KST 새벽이라 UTC 날짜는 전날로 어긋나므로
# 메일 제목/본문의 날짜는 KST 기준으로 표기한다.
_KST = timezone(timedelta(hours=9))


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_summary(
    added_by_playlist: dict[str, list[ScoredVideo]],
) -> tuple[str, str]:
    """(제목, 본문) 을 만든다. SES 는 UTF-8 을 지원하므로 한글 그대로 둔다."""
    today = datetime.now(_KST).strftime("%Y-%m-%d")
    total = sum(len(v) for v in added_by_playlist.values())

    subject = f"[YouTube Curator] {today} 새 영상 {total}개 추가됨"

    lines = [f"{today} 큐레이션 결과 — 새 영상 {total}개 추가", ""]
    for name, videos in added_by_playlist.items():
        if not videos:
            continue
        lines.append(f"▶ {name} ({len(videos)}개)")
        for v in videos:
            lines.append(
                f"  • [{v.score}] {v.title}  ({_fmt_duration(v.duration_seconds)}) — {v.channel}"
            )
            lines.append(f"    {v.url}")
        lines.append("")

    return subject, "\n".join(lines).rstrip() + "\n"


def send_summary(added_by_playlist: dict[str, list[ScoredVideo]]) -> bool:
    """추가된 영상 요약을 SES 로 발송한다.

    추가된 영상이 없거나 SES_FROM_EMAIL 이 설정되지 않았으면 발송하지 않고
    False 를 반환한다. 발송에 성공하면 True.
    """
    total = sum(len(v) for v in added_by_playlist.values())
    if total == 0:
        print("[notify] 추가된 영상이 없어 메일을 보내지 않습니다.")
        return False

    from_email = os.environ.get("SES_FROM_EMAIL")
    if not from_email:
        print("[notify] SES_FROM_EMAIL 미설정 — 메일 발송을 건너뜁니다.")
        return False
    to_email = os.environ.get("SES_TO_EMAIL") or from_email

    try:
        import boto3
    except ImportError:
        print("[notify] boto3 가 설치되어 있지 않아 메일 발송을 건너뜁니다.")
        return False

    subject, body = build_summary(added_by_playlist)

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    client = boto3.client("ses", region_name=region) if region else boto3.client("ses")
    client.send_email(
        Source=from_email,
        Destination={"ToAddresses": [to_email]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        },
    )
    print(f"[notify] SES 발송 완료 — {total}개 영상 요약 메일을 {to_email} 로 보냈습니다.")
    return True
