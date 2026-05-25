# 구갈점 장난감 예약 감시 봇

용인시육아종합지원센터 장난감도서관 구갈점에서 `걸음마학습기-한글판` 대여 가능 상태가 생기면 텔레그램으로 알려주는 봇입니다.

- 자동 예약은 하지 않습니다.
- 기본 대상은 구갈점 `걸음마학습기-한글판`입니다.
- `대여가능`, `예약가능` 상태가 있으면 알림을 보냅니다.
- 현재 기본값은 가능한 장난감이 있을 때만 알림을 보냅니다.

## 파일 구성

- `check_yicare_toy.py`: 장난감 대여상태 확인 및 텔레그램 발송 코드
- `config.json`: 사용자가 직접 바꾸는 설정 파일
- `requirements.txt`: Python 패키지 목록
- `.github/workflows/check-yicare-toy.yml`: GitHub Actions 자동 실행 설정

## 설정 바꾸기

`config.json`을 열어서 값을 바꾸면 됩니다.

```json
{
  "branch_no": "3",
  "branch_name": "구갈점",
  "target_product_name": "걸음마학습기-한글판",
  "target_product_no": "7563",
  "search_keyword": "걸음마학습기",
  "check_interval_seconds": 60,
  "checks_per_run": 5,
  "notify_when_available": true,
  "notify_when_no_available": false,
  "include_status_list": true,
  "timezone": "Asia/Seoul"
}
```

## GitHub Secrets 설정

GitHub 저장소에서 아래 두 값을 Secrets로 등록해야 합니다.

| Secret 이름 | 설명 |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 BotFather가 준 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 알림을 받을 텔레그램 chat_id |

Secrets 설정 위치:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

## GitHub Actions에서 실행하기

수동 실행:

1. GitHub 저장소의 `Actions` 탭을 엽니다.
2. `Check Yicare Toy Reservation`을 누릅니다.
3. `Run workflow`를 누릅니다.

자동 실행은 5분마다 시작합니다. 한 번 실행될 때 1분 간격으로 5번 확인합니다.
