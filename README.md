# Sang Joon의 오늘 경제 지표 — 뉴스레터 자동 발송

Python + GitHub Actions 조합으로 매일 정해진 시각에 코스피/S&P500/나스닥/관심종목/환율 정보를
카드뉴스 스타일 이메일로 자동 발송하는 프로젝트입니다.

## 1. 구성 파일

```
.
├── README.md
├── requirements.txt
├── scripts/
│   └── generate_newsletter.py   # 시세 조회 + HTML 생성 + 이메일 발송
└── .github/
    └── workflows/
        └── newsletter.yml       # 매일 자동 실행 스케줄
```

## 2. 저장소 반영 절차

1. 본인 GitHub 저장소(신규 또는 기존)에 위 파일 구조 그대로 커밋/푸시합니다.
2. 저장소 `Settings > Secrets and variables > Actions` 메뉴로 이동하여
   `New repository secret`으로 아래 3개 값을 등록합니다.

| Secret 이름 | 값 |
|---|---|
| `GMAIL_ADDRESS` | 발신용 Gmail 주소 (예: sajui800822@gmail.com) |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 (아래 3항 참고) |
| `RECIPIENT_EMAIL` | 수신 이메일 주소 (본인 수신 시 GMAIL_ADDRESS와 동일하게 입력) |

## 3. Gmail 앱 비밀번호 발급 방법

일반 Gmail 로그인 비밀번호는 SMTP 발송에 사용할 수 없습니다. 아래 절차로 별도 앱 비밀번호를 발급받아야 합니다.

1. 사용할 Gmail 계정에 **2단계 인증**이 활성화되어 있어야 합니다. (Google 계정 > 보안 > 2단계 인증)
2. Google 계정 > 보안 > "앱 비밀번호" 메뉴에서 새 앱 비밀번호를 생성합니다.
3. 발급된 16자리 비밀번호를 `GMAIL_APP_PASSWORD` Secret 값으로 등록합니다.

## 4. 동작 확인(수동 실행)

Secrets 등록 후 정기 스케줄을 기다리지 않고 즉시 테스트할 수 있습니다.

1. 저장소 상단 `Actions` 탭 이동
2. 좌측 `Sang Joon Daily Market Newsletter` 워크플로 선택
3. `Run workflow` 버튼 클릭 → 실행 로그에서 정상 완료 여부 확인
4. 등록한 수신 이메일함에서 실제 수신 여부 확인

**중요**: 본 스크립트는 Cowork 세션(외부 네트워크 접근이 제한된 환경) 내에서는
실시간 시세 조회(yfinance → Yahoo Finance) 테스트를 진행하지 못했습니다.
HTML 카드 생성 로직 및 서식은 목업 데이터로 검증을 완료했으나,
**최초 배포 후 반드시 위 수동 실행으로 실제 시세 조회 및 이메일 발송 정상 동작을 확인하시기 바랍니다.**

## 5. 발송 시각 변경

`.github/workflows/newsletter.yml`의 `cron` 값은 UTC 기준입니다. 현재 인도시간(IST) 06:00에 맞춰
`30 0 * * *`(UTC 00:30)로 설정되어 있습니다. 시각을 변경하려면 원하는 IST 시각에서 5시간 30분을 뺀
UTC 시각으로 cron 표현식을 수정하십시오.

## 6. 관심 종목 목록 수정

`scripts/generate_newsletter.py` 상단의 `WATCHLIST` 딕셔너리에서 `label`(표시명)과 `ticker`
(Yahoo Finance 티커)를 수정/추가/삭제하면 됩니다. 한국 종목은 `.KS`(코스피) 또는 `.KQ`(코스닥)
접미사가 필요합니다.

## 7. 알려진 제약사항

- 시세 데이터는 Yahoo Finance 비공식 API(yfinance)를 사용하므로, Yahoo 측 정책 변경 시
  일시적으로 조회가 실패할 수 있습니다. 개별 종목 조회 실패 시 해당 카드만
  "시세 조회 실패" 상태로 표시되고 나머지 발송은 정상 진행됩니다.
- 표시되는 가격은 실시간 체결가가 아닌 **최근 종가 기준**입니다.
- 원/루피(INR/KRW) 환율은 Yahoo Finance에 직접적인 교차 티커가 없을 가능성을 고려하여,
  1차로 `INRKRW=X` 조회를 시도하고 실패 시 USD/KRW ÷ USD/INR로 자동 환산합니다.
- 카카오톡/왓츠앱 등 메신저 채널 확장은 별도 검토 문서(`Sang_Joon_경제지표_뉴스레터_검토안.md`)의
  3항을 참고하여 추후 진행 예정입니다.
