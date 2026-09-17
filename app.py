import os
import time
import requests
import pandas as pd

from flask import Flask, render_template_string
from openai import OpenAI


app = Flask(__name__)


# =========================================================
# SETTINGS
# =========================================================

SYMBOL = "BTCUSDT"

ACCOUNT_BALANCE = 1000
MAX_RISK_PERCENT = 1
RR = 2

BASE_URL = "https://api.binance.us/api/v3"


# =========================================================
# BINANCE DATA
# =========================================================

def get_klines(interval, limit=100):

    url = f"{BASE_URL}/klines"

    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "limit": limit
    }

    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    df = pd.DataFrame(
        data,
        columns=[
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
        ]
    )

    for col in [
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]:
        df[col] = pd.to_numeric(df[col])

    return df


# =========================================================
# RSI
# =========================================================

def rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)

    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()

    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss.replace(0, 1e-10)

    return 100 - (100 / (1 + rs))


# =========================================================
# SCANNER
# =========================================================

def run_scanner():

    df1h = get_klines("1h", 100)

    df15 = get_klines("15m", 100)

    df5 = get_klines("5m", 100)


    # -----------------------------------------------------
    # CURRENT PRICE
    # -----------------------------------------------------

    price = float(
        df5["close"].iloc[-1]
    )


    # -----------------------------------------------------
    # 1H MOVING AVERAGES
    # -----------------------------------------------------

    ma10 = float(
        df1h["close"].rolling(10).mean().iloc[-1]
    )

    ma30 = float(
        df1h["close"].rolling(30).mean().iloc[-1]
    )

    ma60 = float(
        df1h["close"].rolling(60).mean().iloc[-1]
    )


    # -----------------------------------------------------
    # TREND
    # -----------------------------------------------------

    if ma10 > ma30 > ma60:

        trend = "BULLISH"

    elif ma10 < ma30 < ma60:

        trend = "BEARISH"

    else:

        trend = "SIDEWAYS"


    # -----------------------------------------------------
    # SUPPORT / RESISTANCE
    # -----------------------------------------------------

    support = float(
        df1h["low"].tail(50).min()
    )

    resistance = float(
        df1h["high"].tail(50).max()
    )


    # -----------------------------------------------------
    # 15M ANALYSIS
    # -----------------------------------------------------

    recent15 = df15.tail(20)

    support_15 = float(
        recent15["low"].min()
    )

    resistance_15 = float(
        recent15["high"].max()
    )

    last15 = df15.iloc[-1]


    support_hold = (
        last15["low"] <= support_15 * 1.002
        and
        last15["close"] > last15["open"]
    )


    resistance_rejection = (
        last15["high"] >= resistance_15 * 0.998
        and
        last15["close"] < last15["open"]
    )


    # -----------------------------------------------------
    # 5M RSI
    # -----------------------------------------------------

    df5["rsi"] = rsi(
        df5["close"]
    )

    current_rsi = float(
        df5["rsi"].iloc[-1]
    )


    # -----------------------------------------------------
    # VOLUME
    # -----------------------------------------------------

    avg_volume = float(
        df5["volume"].rolling(20).mean().iloc[-1]
    )

    current_volume = float(
        df5["volume"].iloc[-1]
    )


    if current_volume > avg_volume * 1.5:

        volume_status = "HIGH"

    elif current_volume < avg_volume * 0.7:

        volume_status = "LOW"

    else:

        volume_status = "NORMAL"


    # -----------------------------------------------------
    # MOMENTUM
    # -----------------------------------------------------

    close_now = float(
        df5["close"].iloc[-1]
    )

    close_prev = float(
        df5["close"].iloc[-4]
    )


    if close_now > close_prev:

        momentum = "BULLISH"

    elif close_now < close_prev:

        momentum = "BEARISH"

    else:

        momentum = "NEUTRAL"


    # -----------------------------------------------------
    # 5M CONFIRMATION
    # -----------------------------------------------------

    last5 = df5.iloc[-1]


    long_confirmation = (
        last5["close"] > last5["open"]
        and
        momentum == "BULLISH"
        and
        current_rsi > 50
    )


    short_confirmation = (
        last5["close"] < last5["open"]
        and
        momentum == "BEARISH"
        and
        current_rsi < 50
    )


    # -----------------------------------------------------
    # FUNDING RATE
    # -----------------------------------------------------

    funding_percent = 0.0


    try:

        funding_url = (
            "https://fapi.binance.com/"
            "fapi/v1/premiumIndex"
        )

        funding_response = requests.get(
            funding_url,
            params={
                "symbol": SYMBOL
            },
            timeout=20
        )


        if funding_response.ok:

            funding_data = (
                funding_response.json()
            )

            funding_percent = float(
                funding_data.get(
                    "lastFundingRate",
                    0
                )
            ) * 100


    except Exception:

        funding_percent = 0.0


    # -----------------------------------------------------
    # FINAL SIGNAL
    # -----------------------------------------------------

    if (
        trend == "BULLISH"
        and
        long_confirmation
        and
        support_hold
    ):

        signal = "LONG 🟢"

        reason = (
            "Bullish trend + "
            "5M long confirmation + "
            "support hold."
        )


    elif (
        trend == "BEARISH"
        and
        short_confirmation
        and
        resistance_rejection
    ):

        signal = "SHORT 🔴"

        reason = (
            "Bearish trend + "
            "5M short confirmation + "
            "resistance rejection."
        )


    else:

        signal = "WAIT ⏳"


        if trend == "SIDEWAYS":

            reason = (
                "1H trend is not confirmed."
            )

        elif price >= resistance:

            reason = (
                "Price is near resistance."
            )

        elif price <= support:

            reason = (
                "Price is near support."
            )

        else:

            reason = (
                "Entry conditions are "
                "not fully confirmed."
            )


    return {

        "price": price,

        "trend": trend,

        "ma10": ma10,

        "ma30": ma30,

        "ma60": ma60,

        "support": support,

        "resistance": resistance,

        "support_hold": support_hold,

        "resistance_rejection":
            resistance_rejection,

        "rsi": current_rsi,

        "volume_status":
            volume_status,

        "momentum":
            momentum,

        "long_confirmation":
            long_confirmation,

        "short_confirmation":
            short_confirmation,

        "funding_percent":
            funding_percent,

        "signal":
            signal,

        "reason":
            reason
    }


# =========================================================
# AI ANALYSIS CACHE
# =========================================================

AI_CACHE = ""

AI_CACHE_TIME = 0

AI_CACHE_SECONDS = 600


# =========================================================
# OPENAI AI ANALYSIS
# =========================================================

def get_ai_analysis(data):

    global AI_CACHE
    global AI_CACHE_TIME


    # -----------------------------------------------------
    # USE CACHE FOR 10 MINUTES
    # -----------------------------------------------------

    now = time.time()


    if AI_CACHE:

        if now - AI_CACHE_TIME < AI_CACHE_SECONDS:

            return AI_CACHE


    # -----------------------------------------------------
    # OPENAI API KEY
    # -----------------------------------------------------

    api_key = os.getenv(
        "OPENAI_API_KEY"
    )


    if not api_key:

        return (
            "OPENAI_API_KEY is not configured."
        )


    client = OpenAI(
        api_key=api_key
    )


    # -----------------------------------------------------
    # AI PROMPT
    # -----------------------------------------------------

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

15M Support Hold:
{data["support_hold"]}

15M Resistance Rejection:
{data["resistance_rejection"]}

5M RSI:
{data["rsi"]:.2f}

Volume:
{data["volume_status"]}

Momentum:
{data["momentum"]}

5M Long Confirmation:
{data["long_confirmation"]}

5M Short Confirmation:
{data["short_confirmation"]}

Funding Rate:
{data["funding_percent"]:.4f}%

Scanner Signal:
{data["signal"]}

Reason:
{data["reason"]}

Keep the answer concise and practical.
"""


    # -----------------------------------------------------
    # OPENAI REQUEST
    # -----------------------------------------------------

    try:

        response = client.responses.create(

            model="gpt-5.6-luna",

            input=prompt

        )


        result = response.output_text


        # -------------------------------------------------
        # SAVE SUCCESSFUL RESULT TO CACHE
        # -------------------------------------------------

        AI_CACHE = result

        AI_CACHE_TIME = time.time()


        return result


    except Exception as e:

        # If an API error happens, show a simple message
        # instead of exposing the full error.

        return (
            "AI analysis temporarily unavailable: "
            f"{type(e).__name__}"
        )


# =========================================================
# HTML
# =========================================================

HTML = """

<!DOCTYPE html>

<html>

<head>

    <meta charset="UTF-8">

    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <title>BTC AI Scanner</title>

    <style>

        body {
            font-family: Arial, sans-serif;
            background: #111;
            color: white;
            margin: 0;
            padding: 20px;
        }

        .container {
            max-width: 900px;
            margin: auto;
        }

        h1 {
            text-align: center;
        }

        .card {
            background: #1d1d1d;
            padding: 20px;
            margin-bottom: 20px;
            border-radius: 12px;
        }

        .row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #333;
        }

        .signal {
            font-size: 30px;
            text-align: center;
            padding: 20px;
        }

        .ai {
            white-space: pre-wrap;
            line-height: 1.6;
        }

        .refresh {
            display: block;
            width: 100%;
            padding: 12px;
            margin-top: 20px;
            border: none;
            border-radius: 8px;
            background: #333;
            color: white;
            font-size: 16px;
            cursor: pointer;
        }

        .refresh:hover {
            background: #444;
        }

    </style>

</head>


<body>

<div class="container">

    <h1>₿ BTC / USDT AI Scanner</h1>


    <div class="card">

        <div class="row">
            <span>Price</span>
            <span>
                ${{ "%.2f"|format(price) }}
            </span>
        </div>


        <div class="row">
            <span>1H Trend</span>
            <span>{{ trend }}</span>
        </div>


        <div class="row">
            <span>MA10</span>
            <span>
                {{ "%.2f"|format(ma10) }}
            </span>
        </div>


        <div class="row">
            <span>MA30</span>
            <span>
                {{ "%.2f"|format(ma30) }}
            </span>
        </div>


        <div class="row">
            <span>MA60</span>
            <span>
                {{ "%.2f"|format(ma60) }}
            </span>
        </div>


        <div class="row">
            <span>Support</span>
            <span>
                {{ "%.2f"|format(support) }}
            </span>
        </div>


        <div class="row">
            <span>Resistance</span>
            <span>
                {{ "%.2f"|format(resistance) }}
            </span>
        </div>


        <div class="row">
            <span>RSI</span>
            <span>
                {{ "%.2f"|format(rsi) }}
            </span>
        </div>


        <div class="row">
            <span>Volume</span>
            <span>{{ volume_status }}</span>
        </div>


        <div class="row">
            <span>Momentum</span>
            <span>{{ momentum }}</span>
        </div>


        <div class="row">
            <span>Long Confirmation</span>
            <span>{{ long_confirmation }}</span>
        </div>


        <div class="row">
            <span>Short Confirmation</span>
            <span>{{ short_confirmation }}</span>
        </div>


        <div class="row">
            <span>Funding Rate</span>
            <span>
                {{ "%.4f"|format(funding_percent) }}%
            </span>
        </div>

    </div>


    <div class="card">

        <div class="signal">

            {{ signal }}

        </div>


        <p>
            <strong>Reason:</strong>
        </p>

        <p>
            {{ reason }}
        </p>

    </div>


    <div class="card">

        <h2>🤖 AI Analysis</h2>

        <div class="ai">
            {{ ai_analysis }}
        </div>

    </div>


    <button
        class="refresh"
        onclick="location.reload()">

        🔄 Refresh Scanner

    </button>


</div>

</body>

</html>

"""


# =========================================================
# ROUTE
# =========================================================

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

        long_confirmation=
            data["long_confirmation"],

        short_confirmation=
            data["short_confirmation"],

        funding_percent=
            data["funding_percent"],

        signal=data["signal"],

        reason=data["reason"],

        ai_analysis=ai_analysis

    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        )
    )
