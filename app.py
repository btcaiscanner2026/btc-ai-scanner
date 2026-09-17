import os
import requests
import pandas as pd

from flask import Flask, render_template_string
from openai import OpenAI

app = Flask(__name__)

SYMBOL = "BTCUSDT"
ACCOUNT_BALANCE = 1000
MAX_RISK_PERCENT = 1
RR = 2

BASE_URL = "https://api.binance.us/api/v3"


def get_klines(interval, limit=100):
    url = f"{BASE_URL}/klines"
    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "limit": limit
    }

    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()

    data = r.json()

    df = pd.DataFrame(data, columns=[
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore"
    ])

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col])

    return df


def rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss.replace(0, 1e-10)

    return 100 - (100 / (1 + rs))


def run_scanner():

    df1h = get_klines("1h", 100)
    df15 = get_klines("15m", 100)
    df5 = get_klines("5m", 100)

    price = float(df5["close"].iloc[-1])

    # 1H moving averages
    ma10 = df1h["close"].rolling(10).mean().iloc[-1]
    ma30 = df1h["close"].rolling(30).mean().iloc[-1]
    ma60 = df1h["close"].rolling(60).mean().iloc[-1]

    if ma10 > ma30 > ma60:
        trend = "BULLISH"
    elif ma10 < ma30 < ma60:
        trend = "BEARISH"
    else:
        trend = "SIDEWAYS"

    # Support / resistance
    support = float(df1h["low"].tail(50).min())
    resistance = float(df1h["high"].tail(50).max())

    # 15M
    recent15 = df15.tail(20)

    support_15 = float(recent15["low"].min())
    resistance_15 = float(recent15["high"].max())

    last15 = df15.iloc[-1]

    support_hold = (
        last15["low"] <= support_15 * 1.002
        and last15["close"] > last15["open"]
    )

    resistance_rejection = (
        last15["high"] >= resistance_15 * 0.998
        and last15["close"] < last15["open"]
    )

    # 5M RSI
    df5["rsi"] = rsi(df5["close"])
    current_rsi = float(df5["rsi"].iloc[-1])

    # Volume
    avg_volume = df5["volume"].rolling(20).mean().iloc[-1]
    current_volume = float(df5["volume"].iloc[-1])

    if current_volume > avg_volume * 1.5:
        volume_status = "HIGH"
    elif current_volume < avg_volume * 0.7:
        volume_status = "LOW"
    else:
        volume_status = "NORMAL"

    # Momentum
    close_now = float(df5["close"].iloc[-1])
    close_prev = float(df5["close"].iloc[-4])

    if close_now > close_prev:
        momentum = "BULLISH"
    elif close_now < close_prev:
        momentum = "BEARISH"
    else:
        momentum = "NEUTRAL"

    # 5M confirmation
    last5 = df5.iloc[-1]

    long_confirmation = (
        last5["close"] > last5["open"]
        and momentum == "BULLISH"
        and current_rsi > 50
    )

    short_confirmation = (
        last5["close"] < last5["open"]
        and momentum == "BEARISH"
        and current_rsi < 50
    )

    # Funding
    funding_percent = 0.0

    try:
        funding_url = "https://fapi.binance.com/fapi/v1/premiumIndex"
        funding_response = requests.get(
            funding_url,
            params={"symbol": SYMBOL},
            timeout=20
        )

        if funding_response.ok:
            funding_data = funding_response.json()
            funding_percent = float(
                funding_data.get("lastFundingRate", 0)
            ) * 100

    except Exception:
        funding_percent = 0.0

    # Final signal
    if trend == "BULLISH" and long_confirmation and support_hold:
        signal = "LONG 🟢"
        reason = "Bullish trend + 5M long confirmation + support hold."

    elif trend == "BEARISH" and short_confirmation and resistance_rejection:
        signal = "SHORT 🔴"
        reason = "Bearish trend + 5M short confirmation + resistance rejection."

    else:
        signal = "WAIT ⏳"

        if trend == "SIDEWAYS":
            reason = "1H trend is not confirmed."
        elif price >= resistance:
            reason = "Price is near resistance."
        elif price <= support:
            reason = "Price is near support."
        else:
            reason = "Entry conditions are not fully confirmed."

    return {
        "price": price,
        "trend": trend,
        "ma10": ma10,
        "ma30": ma30,
        "ma60": ma60,
        "support": support,
        "resistance": resistance,
        "support_hold": support_hold,
        "resistance_rejection": resistance_rejection,
        "rsi": current_rsi,
        "volume_status": volume_status,
        "momentum": momentum,
        "long_confirmation": long_confirmation,
        "short_confirmation": short_confirmation,
        "funding_percent": funding_percent,
        "signal": signal,
        "reason": reason
    }


def get_ai_analysis(data):

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return "OPENAI_API_KEY is not configured."

    client = OpenAI(api_key=api_key)

    prompt = f"""
You are a BTC/USDT trading scanner assistant.

Analyze the scanner data below.

Give:
1. Signal
2. Main reasons
3. Important support/resistance
4. Risk warning

Do not invent data.

Scanner data:

Price: {data["price"]:.2f}

1H Trend: {data["trend"]}

MA10: {data["ma10"]:.2f}
MA30: {data["ma30"]:.2f}
MA60: {data["ma60"]:.2f}

Support: {data["support"]:.2f}
Resistance: {data["resistance"]:.2f}

15M Support Hold: {data["support_hold"]}
15M Resistance Rejection: {data["resistance_rejection"]}

5M RSI: {data["rsi"]:.2f}
Volume: {data["volume_status"]}
Momentum: {data["momentum"]}

5M Long Confirmation: {data["long_confirmation"]}
5M Short Confirmation: {data["short_confirmation"]}

Funding Rate: {data["funding_percent"]:.4f}%

Scanner Signal: {data["signal"]}
Reason: {data["reason"]}

Keep the answer concise and practical.
"""

    try:
        response = client.responses.create(
            model="gpt-5.6-luna",
            input=prompt
        )

        return response.output_text

    except Exception as e:
        return f"AI analysis error: {type(e).__name__}: {e}"


HTML = """
<!DOCTYPE html>

<html>

<head>

<meta name="viewport" content="width=device-width, initial-scale=1">

<title>BTC AI Scanner</title>

<style>

body {
    margin: 0;
    background: #0b0f19;
    color: white;
    font-family: Arial, sans-serif;
}

.container {
    max-width: 1000px;
    margin: auto;
    padding: 25px;
}

.card {
    background: #151a27;
    border: 1px solid #303747;
    border-radius: 14px;
    padding: 22px;
    margin-top: 18px;
}

.signal {
    font-size: 32px;
    font-weight: bold;
    margin: 15px 0;
}

.ai {
    margin-top: 20px;
    background: #151a27;
    border: 1px solid #303747;
    border-radius: 14px;
    padding: 25px;
}

.ai-analysis {
    background: #0b0f19;
    border: 1px solid #303747;
    border-radius: 12px;
    padding: 20px;
    margin-top: 15px;
    line-height: 1.9;
    white-space: pre-wrap;
    overflow-wrap: break-word;
}

button {
    margin-top: 20px;
    padding: 12px 20px;
    border: 0;
    border-radius: 10px;
    cursor: pointer;
    font-size: 16px;
}

</style>

</head>

<body>

<div class="container">

<h1>₿ BTC/USDT AI Scanner</h1>

<div class="card">

<h2>Market</h2>

<p>Price: <b>${price:,.2f}</b></p>

<p>1H Trend: <b>{trend}</b></p>

<p>MA10: {ma10:.2f}</p>
<p>MA30: {ma30:.2f}</p>
<p>MA60: {ma60:.2f}</p>

</div>

<div class="card">

<h2>Support / Resistance</h2>

<p>Support: {support:.2f}</p>

<p>Resistance: {resistance:.2f}</p>

</div>

<div class="card">

<h2>5M Confirmation</h2>

<p>RSI: {rsi:.2f}</p>

<p>Volume: {volume_status}</p>

<p>Momentum: {momentum}</p>

<p>Long Confirmation: {long_confirmation}</p>

<p>Short Confirmation: {short_confirmation}</p>

</div>

<div class="card">

<h2>🤖 SCANNER SIGNAL</h2>

<div class="signal">{signal}</div>

<p>{reason}</p>

</div>

<div class="ai">

<h2>🤖 AI ANALYSIS</h2>

<div class="ai-analysis">{ai_analysis}</div>

<button onclick="location.reload()">
🔄 SCAN AGAIN
</button>

</div>

</div>

</body>

</html>
"""


@app.route("/")
def home():

    data = run_scanner()

    ai_analysis = get_ai_analysis(data)

    return render_template_string(
        HTML,
        price=data["price"],
        trend=data["trend"],
        ma10=data["ma10"],
        ma30=data["ma30"],
        ma60=data["ma60"],
        support=data["support"],
        resistance=data["resistance"],
        rsi=data["rsi"],
        volume_status=data["volume_status"],
        momentum=data["momentum"],
        long_confirmation=data["long_confirmation"],
        short_confirmation=data["short_confirmation"],
        signal=data["signal"],
        reason=data["reason"],
        ai_analysis=ai_analysis
    )


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
