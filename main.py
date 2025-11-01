import os, requests, time
import pandas as pd
from datetime import datetime, timedelta

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send(msg):
    if not TOKEN or not CHAT_ID:
        print("Telegram token yok")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def get_liquidations(minutes=60):
    end = int(time.time() * 1000)
    start = end - (minutes * 60 * 1000)
    url = f"https://fapi.binance.com/futures/data/liquidationOrders?startTime={start}&endTime={end}&limit=1000"
    r = requests.get(url)
    return pd.DataFrame(r.json())

def get_funding(symbol="BTCUSDT"):
    url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=5"
    r = requests.get(url).json()
    if not r: return 0
    return float(r[-1]["fundingRate"])

def get_price(symbol="BTCUSDT"):
    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
    return float(requests.get(url).json()["price"])

# ---- MAIN ----
df = get_liquidations()

if df.empty:
    send("⚠️ Liquidation verisi yok")
    exit()

buy_liq = df[df["side"]=="BUY"]["price"].count()
sell_liq = df[df["side"]=="SELL"]["price"].count()

funding = get_funding()
price = get_price()

signal = "⚪ Nötr – büyük balina yönü yok"

# BUY sinyali (short squeeze)
if buy_liq > sell_liq * 1.5 and funding > 0:
    signal = "🟢 BUY — Short squeeze / Balinalar long"

# SELL sinyali (long squeeze)
elif sell_liq > buy_liq * 1.5 and funding < 0:
    signal = "🔴 SELL — Long squeeze / Balinalar short"

msg = f"""
🧠 Binance Likidasyon Botu
⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC

BTC Fiyat: {price}

💥 Son 1 Saat Likidasyonlar:
- Long likidasyon: {sell_liq}
- Short likidasyon: {buy_liq}

🏦 Funding: {funding}

📌 Sinyal: {signal}
"""

send(msg)
print(msg)
