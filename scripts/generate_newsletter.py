"""
Sang Joon의 오늘 경제 지표 - 뉴스레터 생성 및 발송 스크립트

GitHub Actions에서 매일 정해진 시각(기본값: 인도시간 06:00 = UTC 00:30)에 실행되어
1) yfinance로 지수/환율/관심종목 시세를 조회하고
2) 인스타그램 카드뉴스 스타일의 HTML 이메일을 생성한 뒤
3) Gmail SMTP를 통해 발송한다.

필요한 환경변수(GitHub Secrets):
- GMAIL_ADDRESS       : 발신용 Gmail 주소
- GMAIL_APP_PASSWORD  : Gmail 앱 비밀번호(2단계 인증 계정에서 발급)
- RECIPIENT_EMAIL     : 수신 이메일 주소 (미지정 시 GMAIL_ADDRESS로 자기 자신에게 발송)
"""

import os
import smtplib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import yfinance as yf

# ---------------------------------------------------------------------------
# 1. 관심 종목/지수/환율 설정 — 필요 시 이 목록만 수정하면 됩니다.
# ---------------------------------------------------------------------------

# currency: "KRW"(원화 정수 표기) / "USD"(달러 소수점 2자리) / "PT"(지수 포인트) / "RATE"(환율)
WATCHLIST = {
    "지수": [
        {"label": "코스피", "ticker": "^KS11", "currency": "PT"},
        {"label": "S&P 500", "ticker": "^GSPC", "currency": "PT"},
        {"label": "나스닥", "ticker": "^IXIC", "currency": "PT"},
    ],
    "환율": [
        {"label": "원/달러 (USD/KRW)", "ticker": "KRW=X", "currency": "RATE"},
        {"label": "원/루피 (INR/KRW)", "ticker": "INRKRW=X", "currency": "RATE",
         "fallback": {"numerator": "KRW=X", "denominator": "INR=X"}},
    ],
    "관심종목": [
        {"label": "삼성전자", "ticker": "005930.KS", "currency": "KRW"},
        {"label": "SK하이닉스", "ticker": "000660.KS", "currency": "KRW"},
        {"label": "KODEX 200타겟위클리커버드콜", "ticker": "498400.KS", "currency": "KRW"},
        {"label": "VOO", "ticker": "VOO", "currency": "USD"},
        {"label": "QQQM", "ticker": "QQQM", "currency": "USD"},
        {"label": "QLD", "ticker": "QLD", "currency": "USD"},
        {"label": "TQQQ", "ticker": "TQQQ", "currency": "USD"},
        {"label": "SCHD", "ticker": "SCHD", "currency": "USD"},
        {"label": "SOXL", "ticker": "SOXL", "currency": "USD"},
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
    """단일 종목/지수/환율 시세 조회. 실패 시 None 반환(카드에는 '데이터 없음' 표시)."""
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
    sign = "+" if quote.change >= 0 else ""
    if currency == "KRW":
        change_str = f"{sign}{quote.change:,.0f}원"
    elif currency == "USD":
        change_str = f"{sign}${quote.change:,.2f}"
    elif currency == "RATE":
        change_str = f"{sign}{quote.change:,.2f}원"
    else:
        change_str = f"{sign}{quote.change:,.2f}"
    return f"{change_str} ({sign}{quote.pct:.2f}%)"


# ---------------------------------------------------------------------------
# 4. 카드뉴스 스타일 HTML 생성
# ---------------------------------------------------------------------------

CARD_TEMPLATE = """
<tr>
  <td style="padding: 0 0 12px 0;">
    <table role="presentation" width="100%%" cellpadding="0" cellspacing="0"
           style="background:#ffffff; border:1px solid #eaeaea; border-radius:14px; overflow:hidden;">
      <tr>
        <td style="width:6px; background:%(bar_color)s;"></td>
        <td style="padding:16px 18px;">
          <table role="presentation" width="100%%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="font-size:13px; color:#8a8a8a; font-weight:600; letter-spacing:0.2px;">%(label)s</td>
              <td align="right" style="font-size:13px; color:%(text_color)s; font-weight:700;">%(arrow)s %(pct)s%%</td>
            </tr>
            <tr>
              <td colspan="2" style="padding-top:6px; font-size:24px; font-weight:800; color:#1a1a1a;">%(price)s</td>
            </tr>
            <tr>
              <td colspan="2" style="padding-top:2px; font-size:13px; color:%(text_color)s;">%(change)s</td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </td>
</tr>
"""

NO_DATA_CARD_TEMPLATE = """
<tr>
  <td style="padding: 0 0 12px 0;">
    <table role="presentation" width="100%%" cellpadding="0" cellspacing="0"
           style="background:#f7f7f7; border:1px dashed #cccccc; border-radius:14px;">
      <tr>
        <td style="padding:16px 18px;">
          <div style="font-size:13px; color:#8a8a8a; font-weight:600;">%(label)s</div>
          <div style="padding-top:6px; font-size:15px; color:#aaaaaa;">시세 조회 실패 — 다음 발송에서 재시도됩니다</div>
        </td>
      </tr>
    </table>
  </td>
</tr>
"""

SECTION_HEADER_TEMPLATE = """
<tr>
  <td style="padding:22px 0 10px 2px; font-size:15px; font-weight:800; color:#1a1a1a;">%(title)s</td>
</tr>
"""

# 국내 관행: 상승 = 적색, 하락 = 청색
UP_COLOR = "#d92b2b"
DOWN_COLOR = "#1a56db"
FLAT_COLOR = "#8a8a8a"


def render_card(item: dict, quote) -> str:
    if quote is None:
        return NO_DATA_CARD_TEMPLATE % {"label": item["label"]}

    currency = item["currency"]
    if quote.change > 0:
        color, arrow = UP_COLOR, "▲"
    elif quote.change < 0:
        color, arrow = DOWN_COLOR, "▼"
    else:
        color, arrow = FLAT_COLOR, "―"

    return CARD_TEMPLATE % {
        "bar_color": color,
        "text_color": color,
        "arrow": arrow,
        "label": item["label"],
        "price": format_price(quote.price, currency),
        "change": format_change(quote, currency),
        "pct": f"{abs(quote.pct):.2f}",
    }


def build_email_html(sections: dict, today_str: str) -> str:
    body_rows = []
    for section_title, items in sections.items():
        body_rows.append(SECTION_HEADER_TEMPLATE % {"title": section_title})
        for item in items:
            quote = fetch_quote(item)
            body_rows.append(render_card(item, quote))

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
            <td style="padding:4px 4px 18px 4px;">
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

def send_email(html_body: str, subject: str) -> None:
    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("RECIPIENT_EMAIL", gmail_address)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Sang Joon의 오늘 경제 지표 <{gmail_address}>"
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, [recipient], msg.as_string())


def main() -> None:
    now_ist = datetime.now(IST)
    today_str = now_ist.strftime("%Y년 %m월 %d일 (%a)")
    subject = f"[Sang Joon의 오늘 경제 지표] {now_ist.strftime('%Y-%m-%d')} 아침 브리핑"

    html_body = build_email_html(WATCHLIST, today_str)
    send_email(html_body, subject)
    print("뉴스레터 발송 완료")


if __name__ == "__main__":
    main()
