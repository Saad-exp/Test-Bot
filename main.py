import requests
import time
import numpy as np
from datetime import datetime
from telegram import Bot
from flask import Flask
from threading import Thread
import os

# === CONFIGURATION ===
BOT_TOKEN = "7631338194:AAHe8_XWlH3E5uFyusXFmyNsFuSB8brOUuE"
CHAT_ID = "7651640560"

PRICE_CHANGE_THRESHOLD = 4   # % movement trigger
RSI_THRESHOLD = 65
MAX_PRICE = 1.5
UPDATE_INTERVAL = 5          # seconds
COOLDOWN_SECONDS = 600       # 10-minute cooldown

bot = Bot(token=BOT_TOKEN)
last_alert_time = {}  # Track last alert time per symbol

# === Logging Helper ===
def log(msg):
    print(f"[{datetime.utcnow()}] {msg}")

# === Fetch tradable symbols from MEXC USDT-M futures ===
def get_mexc_usdt_futures_symbols():
    log("Fetching MEXC USDT-M futures symbols...")
    try:
        url = "https://contract.mexc.com/api/v1/contract/detail"
        response = requests.get(url, timeout=10)
        symbols = []
        if response.status_code == 200:
            data = response.json().get("data", [])
            for item in data:
                if item["quoteCoin"] == "USDT" and int(item["maxLeverage"]) >= 50:
                    symbols.append(item["symbol"].replace("_", "").upper())
            log(f"Fetched {len(symbols)} valid symbols.")
        else:
            log(f"Failed to fetch symbols: Status {response.status_code}")
        return symbols
    except Exception as e:
        log(f"Error fetching symbols: {e}")
        return []

VALID_SYMBOLS = get_mexc_usdt_futures_symbols()

# === RSI Calculation ===
def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices)
    ups = deltas[deltas > 0].sum() / period
    downs = -deltas[deltas < 0].sum() / period
    rs = ups / downs if downs != 0 else 0
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

# === Alert Sender ===
def send_alert(symbol, price, change, interval):
    now = datetime.utcnow()
    try:
        if symbol in last_alert_time:
            elapsed = (now - last_alert_time[symbol]).total_seconds()
            if elapsed < COOLDOWN_SECONDS:
                log(f"Alert skipped for {symbol}, cooldown active.")
                return

        message = f"🚨 {symbol} moved {change:.2f}% in last {interval} min\nPrice: ${price:.4f}"
        bot.send_message(chat_id=CHAT_ID, text=message)
        last_alert_time[symbol] = now
        log(f"Alert sent for {symbol}: change {change:.2f}% at price ${price:.4f}")
    except Exception as e:
        log(f"Failed to send alert for {symbol}: {e}")

# === Price Checker ===
def fetch_price_changes():
    try:
        url = "https://api.mexc.com/api/v3/ticker/price"
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            log(f"Failed to fetch price data: Status {response.status_code}")
            return

        data = response.json()
        prices_now = {coin['symbol']: float(coin['price']) for coin in data if coin['symbol'].endswith("USDT")}
        log(f"Fetched prices for {len(prices_now)} symbols.")

        for symbol, current_price in prices_now.items():
            if symbol not in VALID_SYMBOLS:
                continue
            if current_price > MAX_PRICE:
                continue

            kline_url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit=100"
            kline_response = requests.get(kline_url, timeout=10)
            if kline_response.status_code != 200:
                log(f"Failed to fetch klines for {symbol}: Status {kline_response.status_code}")
                continue

            candles = kline_response.json()
            closes = [float(c[4]) for c in candles]
            if len(closes) < 15:
                continue

            rsi = calculate_rsi(closes[-15:])
            if rsi is None:
                log(f"RSI not calculated for {symbol}, insufficient data.")
                continue
            if rsi < RSI_THRESHOLD:
                log(f"{symbol} RSI {rsi} below threshold {RSI_THRESHOLD}. Skipping.")
                continue

            price_5m_ago = closes[-2]
            price_15m_ago = closes[-4]

            change_5m = ((current_price - price_5m_ago) / price_5m_ago) * 100
            change_15m = ((current_price - price_15m_ago) / price_15m_ago) * 100

            if abs(change_5m) >= PRICE_CHANGE_THRESHOLD:
                send_alert(symbol, current_price, change_5m, 5)
            elif abs(change_15m) >= PRICE_CHANGE_THRESHOLD:
                send_alert(symbol, current_price, change_15m, 15)

    except Exception as e:
        log(f"Error in fetch_price_changes: {e}")

# === Flask Server Setup ===
app = Flask('')

@app.route('/')
def home():
    return "✅ Bot is running!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# === Main Bot Loop ===
def run_bot_loop():
    log("🤖 Bot is running. Waiting for triggers...")
    
    # Startup test alert
    try:
        bot.send_message(chat_id=CHAT_ID, text="✅ Bot loop started successfully!")
        log("Startup test alert sent to Telegram.")
    except Exception as e:
        log(f"Failed to send startup alert: {e}")

    while True:
        try:
            fetch_price_changes()
            log("Bot cycle completed successfully.")
            time.sleep(UPDATE_INTERVAL)
        except Exception as e:
            log(f"Error in bot loop: {e}")
            time.sleep(UPDATE_INTERVAL)

# === Start Everything ===
keep_alive()
Thread(target=run_bot_loop).start()
