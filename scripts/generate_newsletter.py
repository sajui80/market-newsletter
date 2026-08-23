"""
Sang Joon의 오늘 경제 지표 - 뉴스레터 생성 및 발송 스크립트

GitHub Actions에서 매일 정해진 시각(기본값: 인도시간 06:00 = UTC 00:30)에 실행되어
1) yfinance로 지수/한국 주식/미국 주식/환율 시세를 조회하고
2) 카드뉴스 스타일의 HTML 이메일을 생성한 뒤
3) Gmail SMTP를 통해 발송한다.

필요한 환경변수(GitHub Secrets):
- GMAIL_ADDRESS       : 발신용 Gmail 주소
- GMAIL_APP_PASSWORD  : Gmail 앱 비밀번호(2단계 인증 계정에서 발급)
- RECIPIENT_EMAIL     : 수신 이메일 주소 (콤마로 구분하면 여러 명에게 동시 발송, 미지정 시 GMAIL_ADDRESS로 자기 자신에게 발송)
"""

import os
import smtplib
import sys
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import yfinance as yf

# ---------------------------------------------------------------------------
# 1. 관심 종목/지수/환율 설정 — 필요 시 이 목록만 수정하면 됩니다.
#    섹션 순서가 곧 발송되는 이메일의 배치 순서입니다.
# ---------------------------------------------------------------------------

# currency: "KRW"(원화 정수 표기) / "USD"(달러 소수점 2자리) / "PT"(지수 포인트) / "RATE"(환율)
# icon: 뱃지에 표시할 1~2글자 약칭
WATCHLIST = {
    "지수": [
        {"label": "KOSPI", "ticker": "^KS11", "currency": "PT", "icon": "KS"},
        {"label": "S&P 500", "ticker": "^GSPC", "currency": "PT", "icon": "SP"},
        {"label": "NASDAQ", "ticker": "^IXIC", "currency": "PT", "icon": "NQ"},
    ],
    "한국 주식": [
        {"label": "삼성전자", "ticker": "005930.KS", "currency": "KRW", "icon": "삼성"},
        {"label": "SK하이닉스", "ticker": "000660.KS", "currency": "KRW", "icon": "SK"},
        {"label": "KODEX 200타겟위클리커버드콜", "ticker": "498400.KS", "currency": "KRW", "icon": "KDX"},
        {"label": "현대차", "ticker": "005380.KS", "currency": "KRW", "icon": "현대"},
        {"label": "삼성전기", "ticker": "009150.KS", "currency": "KRW", "icon": "삼전"},
    ],
    "미국 주식": [
        {"label": "VOO", "ticker": "VOO", "currency": "USD", "icon": "VO"},
        {"label": "QQQM", "ticker": "QQQM", "currency": "USD", "icon": "QM"},
        {"label": "QLD", "ticker": "QLD", "currency": "USD", "icon": "QL"},
        {"label": "TQQQ", "ticker": "TQQQ", "currency": "USD", "icon": "TQ"},
        {"label": "SCHD", "ticker": "SCHD", "currency": "USD", "icon": "SC"},
        {"label": "SOXL", "ticker": "SOXL", "currency": "USD", "icon": "SO"},
        {"label": "QQQ", "ticker": "QQQ", "currency": "USD", "icon": "QQ"},
        {"label": "NVDA", "ticker": "NVDA", "currency": "USD", "icon": "NV"},
        {"label": "AAPL", "ticker": "AAPL", "currency": "USD", "icon": "AA"},
        {"label": "TSLA", "ticker": "TSLA", "currency": "USD", "icon": "TS"},
        {"label": "SPCX", "ticker": "SPCX", "currency": "USD", "icon": "SX"},
        {"label": "GOOGL", "ticker": "GOOGL", "currency": "USD", "icon": "GO"},
    ],
    "환율": [
        {"label": "원/달러 (USD/KRW)", "ticker": "KRW=X", "currency": "RATE", "icon": "$"},
        {"label": "원/루피 (INR/KRW)", "ticker": "INRKRW=X", "currency": "RATE", "icon": "₹",
         "fallback": {"numerator": "KRW=X", "denominator": "INR=X"}},
    ],
}

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# 2. 데이터 조회
# ---------------------------------------------------------------------------

@dataclass
class Quote:
    price: float
    prev_close: float

    @property
    def change(self) -> float:
        return self.price - self.prev_close

    @property
    def pct(self) -> float:
        return (self.change / self.prev_close * 100) if self.prev_close else 0.0


def _history_last_two_closes(ticker: str):
    hist = yf.Ticker(ticker).history(period="5d", interval="1d")
    if hist.empty or len(hist) < 2:
        return None
    price = float(hist["Close"].iloc[-1])
    prev = float(hist["Close"].iloc[-2])
    return Quote(price=price, prev_close=prev)


def fetch_quote(item: dict):
    """단일 종목/지수/환율 시세 조회. 실패 시 None 반환(해당 행에는 '데이터 없음' 표시)."""
    ticker = item["ticker"]
    try:
        quote = _history_last_two_closes(ticker)
        if quote is not None:
            return quote
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] {ticker} 기본 조회 실패: {exc}", file=sys.stderr)

    # INR/KRW처럼 직접 크로스 티커가 없을 수 있는 경우, USD 경유 계산으로 대체
    fallback = item.get("fallback")
    if fallback:
        try:
            num = _history_last_two_closes(fallback["numerator"])
            den = _history_last_two_closes(fallback["denominator"])
            if num and den:
                price = num.price / den.price
                prev = num.prev_close / den.prev_close
                return Quote(price=price, prev_close=prev)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] {ticker} 대체 조회 실패: {exc}", file=sys.stderr)

    return None


# ---------------------------------------------------------------------------
# 3. 숫자 포맷팅
# ---------------------------------------------------------------------------

def format_price(value: float, currency: str) -> str:
    if currency == "KRW":
        return f"{value:,.0f}원"
    if currency == "USD":
        return f"${value:,.2f}"
    if currency == "RATE":
        return f"{value:,.2f}원"
    return f"{value:,.2f}"  # PT (지수)


def format_change(quote: Quote, currency: str) -> str:
    sign = "+" if quote.change >= 0 else "-"
    magnitude = abs(quote.change)
    if currency == "KRW":
        change_str = f"{sign}{magnitude:,.0f}원"
    elif currency == "USD":
        change_str = f"{sign}${magnitude:,.2f}"
    elif currency == "RATE":
        change_str = f"{sign}{magnitude:,.2f}원"
    else:
        change_str = f"{sign}{magnitude:,.2f}"
    return f"{change_str} ({sign}{abs(quote.pct):.2f}%)"


# ---------------------------------------------------------------------------
# 4. 카드뉴스(리스트형) 스타일 HTML 생성
# ---------------------------------------------------------------------------

# 뱃지 색상 팔레트 — 종목명을 해시하여 결정적으로 배정(동일 종목은 매일 같은 색)
BADGE_COLORS = [
    "#2f5fa8", "#c0392b", "#1f8a70", "#8e44ad", "#c77d24",
    "#0f766e", "#a13d63", "#3b5b78", "#8a6d1e", "#4a4e69",
]


def _badge_color(label: str) -> str:
    idx = zlib.crc32(label.encode("utf-8")) % len(BADGE_COLORS)
    return BADGE_COLORS[idx]


SECTION_OPEN_TEMPLATE = """
<tr>
  <td style="padding:20px 0 0 0;">
    <div style="font-size:13px; font-weight:700; letter-spacing:0.03em; color:#8a8a8a; padding:0 2px 10px;">%(title)s</div>
    <div style="border:1px solid #eef0ec; border-radius:14px; overflow:hidden;">
    <table role="presentation" width="100%%" cellpadding="0" cellspacing="0">
"""

SECTION_CLOSE_TEMPLATE = """
    </table>
    </div>
  </td>
</tr>
"""

# 짝수/홀수 행 배경 — 줄무늬로 가독성 확보
ROW_BG_EVEN = "#ffffff"
ROW_BG_ODD = "#f7f7f5"

ROW_TEMPLATE = """
<tr>
  <td style="background:%(row_bg)s; padding:14px 14px;">
    <table role="presentation" width="100%%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="22" style="vertical-align:middle; font-size:17px; font-weight:800; color:#c7cbc2;">%(number)s</td>
        <td width="40" style="vertical-align:middle; padding-left:4px;">
          <div style="width:34px; height:34px; border-radius:9px; background:%(badge_color)s; color:#ffffff; font-size:%(icon_size)s; font-weight:700; text-align:center; line-height:34px; font-family:'IBM Plex Sans KR', Arial, sans-serif;">%(icon)s</div>
        </td>
        <td style="vertical-align:middle; padding-left:10px; font-size:15.5px; font-weight:600; color:#1a1a1a;">%(label)s</td>
        <td align="right" style="vertical-align:middle; white-space:nowrap;">
          <div style="font-size:16px; font-weight:700; color:#1a1a1a;">%(price)s</div>
          <div style="font-size:12.5px; font-weight:700; color:%(change_color)s; margin-top:2px;">%(change)s</div>
        </td>
      </tr>
    </table>
  </td>
</tr>
"""

NO_DATA_ROW_TEMPLATE = """
<tr>
  <td style="background:%(row_bg)s; padding:14px 14px;">
    <table role="presentation" width="100%%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="22" style="vertical-align:middle; font-size:17px; font-weight:800; color:#c7cbc2;">%(number)s</td>
        <td width="40" style="vertical-align:middle; padding-left:4px;">
          <div style="width:34px; height:34px; border-radius:9px; background:#eef0ec; color:#aaaaaa; font-size:%(icon_size)s; font-weight:700; text-align:center; line-height:34px;">%(icon)s</div>
        </td>
        <td style="vertical-align:middle; padding-left:10px; font-size:15.5px; font-weight:600; color:#1a1a1a;">%(label)s</td>
        <td align="right" style="vertical-align:middle; white-space:nowrap; font-size:12.5px; color:#aaaaaa;">조회 실패</td>
      </tr>
    </table>
  </td>
</tr>
"""

# 국내 관행: 상승 = 적색, 하락 = 청색
UP_COLOR = "#d92b2b"
DOWN_COLOR = "#1a56db"
FLAT_COLOR = "#8a8a8a"


def _icon_font_size(icon: str) -> str:
    # 한글 2글자/영문 2글자는 작게, 1글자(통화 기호 등)는 크게
    return "11px" if len(icon) >= 2 else "16px"


def render_row(item: dict, quote, number: int) -> str:
    row_bg = ROW_BG_EVEN if number % 2 == 1 else ROW_BG_ODD
    icon = item.get("icon", item["label"][:2])

    if quote is None:
        return NO_DATA_ROW_TEMPLATE % {
            "row_bg": row_bg,
            "number": number,
            "icon": icon,
            "icon_size": _icon_font_size(icon),
            "label": item["label"],
        }

    currency = item["currency"]
    if quote.change > 0:
        color = UP_COLOR
    elif quote.change < 0:
        color = DOWN_COLOR
    else:
        color = FLAT_COLOR

    return ROW_TEMPLATE % {
        "row_bg": row_bg,
        "number": number,
        "badge_color": _badge_color(item["label"]),
        "icon": icon,
        "icon_size": _icon_font_size(icon),
        "label": item["label"],
        "price": format_price(quote.price, currency),
        "change": format_change(quote, currency),
        "change_color": color,
    }


def build_email_html(sections: dict, today_str: str) -> str:
    body_rows = []
    for section_title, items in sections.items():
        body_rows.append(SECTION_OPEN_TEMPLATE % {"title": section_title})
        for i, item in enumerate(items):
            quote = fetch_quote(item)
            body_rows.append(render_row(item, quote, i + 1))
        body_rows.append(SECTION_CLOSE_TEMPLATE)

    return f"""\
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sang Joon의 오늘 경제 지표</title>
</head>
<body style="margin:0; padding:0; background:#f2f2f2;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f2f2f2;">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;">
          <tr>
            <td style="padding:4px 4px 4px 4px;">
              <div style="font-size:20px; font-weight:800; color:#1a1a1a;">Sang Joon의 오늘 경제 지표</div>
              <div style="font-size:13px; color:#8a8a8a; padding-top:4px;">{today_str} 기준</div>
            </td>
          </tr>
          {''.join(body_rows)}
          <tr>
            <td style="padding:18px 4px 0 4px; font-size:11px; color:#aaaaaa; line-height:1.6;">
              본 정보는 투자 판단의 참고용이며, 최근 종가 기준으로 산출됩니다.<br>
              데이터 출처: Yahoo Finance (yfinance). 실제 거래 시세와 차이가 있을 수 있습니다.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 5. 이메일 발송
# ---------------------------------------------------------------------------

def _parse_recipients(raw: str) -> list:
    """콤마(,)로 구분된 여러 수신 주소를 리스트로 변환. 세미콜론(;)도 허용."""
    normalized = raw.replace(";", ",")
    return [addr.strip() for addr in normalized.split(",") if addr.strip()]


def send_email(html_body: str, subject: str) -> None:
    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]
    recipients = _parse_recipients(os.environ.get("RECIPIENT_EMAIL", gmail_address))

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Sang Joon의 오늘 경제 지표 <{gmail_address}>"
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, recipients, msg.as_string())


def main() -> None:
    now_ist = datetime.now(IST)
    today_str = now_ist.strftime("%Y년 %m월 %d일 (%a)")
    subject = f"[Sang Joon의 오늘 경제 지표] {now_ist.strftime('%Y-%m-%d')} 아침 브리핑"

    html_body = build_email_html(WATCHLIST, today_str)
    send_email(html_body, subject)
    print("뉴스레터 발송 완료")


if __name__ == "__main__":
    main()
