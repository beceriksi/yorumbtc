import os
import requests
import pandas as pd
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

COINS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","AVAXUSDT"]
TIMEFRAME = "1h"
MIN_ROWS = 50
VOL_BOOM = 2.5  # Hacim artış çarpanı
DROP_LIMIT = -0.7  # %0.7 üstü hızlı düşüş

def tg(msg):
    if TELEGRAM_TOKEN and CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def get_klines(symbol):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={TIMEFRAME}&limit=200"
    data = requests.get(url).json()
    if not data or len(data) < MIN_ROWS: return None
    df = pd.DataFrame(data, columns=["t","o","h","l","c","v","_","_","_","_","_","_"])
    df = df[["o","h","l","c","v"]].astype(float)
    return df

def analyze(df):
    df["ema20"] = df["c"].ewm(span=20).mean()
    df["ema50"] = df["c"].ewm(span=50).mean()
    df["ret"] = df["c"].pct_change()*100
    df["vol_avg"] = df["v"].rolling(20).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # SELL sinyal kriterlerimiz
    cond_sell = (
        last["c"] < last["ema20"] < last["ema50"] and
        last["ret"] < DROP_LIMIT and
        last["v"] > last["vol_avg"] * VOL_BOOM
    )

    # BUY sinyal kriteri (daha sık)
    cond_buy = (
        last["c"] > last["ema20"] > last["ema50"] and
        last["v"] > last["vol_avg"] * VOL_BOOM
    )

    if cond_sell:
        return "SELL"

    if cond_buy:
        return "BUY"

    return None

def main():
    msg_header = f"📊 *Saatlik Kripto Tarama*\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    signals = []

    for coin in COINS:
        df = get_klines(coin)
        if df is None: continue
        signal = analyze(df)
        if signal == "SELL": signals.append(f"🔻 SELL → {coin}")
        elif signal == "BUY": signals.append(f"🟢 BUY → {coin}")

    if not signals:
        tg(msg_header + "⚪ Şu anda net sinyal yok.")
    else:
        tg(msg_header + "\n".join(signals))

if __name__ == "__main__":
    main()
