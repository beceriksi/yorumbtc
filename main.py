#!/usr/bin/env python3
import os, time, requests, math
import pandas as pd
from datetime import datetime

# ===== CONFIG =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Symbols to scan (futures tickers -> add/remove as you like)
SYMBOLS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","AVAXUSDT","ARBUSDT","OPUSDT","DOGEUSDT"]

# Kline settings
INTERVAL = "5m"        # ince periyot (1m veya 5m önerilir)
LOOKBACK = 36          # kaç mum üzerinden ortalama / trend hesaplanır (36*5m = 3 saat)
CHECK_WINDOW = 3       # son kaç mumda sell hacmi patlaması arıyoruz
VOL_MULT = 4.0         # son sell_vol > VOL_MULT * vol_avg => patlama
MAX_PRICE_DROP = 0.02  # henüz çok düşmemiş: son CHECK_WINDOW mum içindeki düşüş < 2% (0.02)
MIN_BASE_VOLUME = 50   # (opsiyonel) minimum baz hacim eşiği (örn 50 base units) — düşük likiditede false pozitif azalt

# Binance Futures API endpoints (USDT perpetual)
KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"

REQUEST_TIMEOUT = 8

# ===== HELPERS =====
def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram secrets missing; would send:", text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code != 200:
            print("Telegram error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram exception:", e)

def fetch_klines(symbol, interval=INTERVAL, limit=LOOKBACK+10):
    """Return DataFrame with columns: open_time, open, high, low, close, volume, taker_buy_base"""
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        r = requests.get(KLINES_URL, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or len(data) == 0:
            return None
        df = pd.DataFrame(data, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_asset_volume","num_trades",
            "taker_buy_base","taker_buy_quote","ignore"
        ])
        # numeric
        df[["open","high","low","close","volume","taker_buy_base"]] = df[["open","high","low","close","volume","taker_buy_base"]].astype(float)
        return df
    except Exception as e:
        # silent failure for robust running
        print(f"[{symbol}] fetch_klines error:", e)
        return None

def detect_sell_spike(df):
    """
    - compute taker sell volume ~ volume - taker_buy_base
    - compute rolling average sell_vol over LOOKBACK (excluding tail CHECK_WINDOW)
    - check if any of last CHECK_WINDOW candles sell_vol > VOL_MULT * avg_sell
    - also check price change across CHECK_WINDOW to be > -MAX_PRICE_DROP (i.e. not deep drop)
    """
    if df is None or len(df) < LOOKBACK:
        return None

    # compute sell volume approx
    df = df.copy().reset_index(drop=True)
    df["sell_vol"] = df["volume"] - df["taker_buy_base"]
    # guard negative due to rounding
    df["sell_vol"] = df["sell_vol"].clip(lower=0.0)

    # moving average of sell_vol excluding the last CHECK_WINDOW candles
    hist_cut = df["sell_vol"].iloc[:-CHECK_WINDOW]
    if len(hist_cut) < 5:
        avg_sell = hist_cut.mean() if len(hist_cut)>0 else 0.0
    else:
        avg_sell = hist_cut.tail(LOOKBACK - CHECK_WINDOW).mean()

    # avoid tiny avg causing false positives
    if avg_sell <= 0:
        avg_sell = df["sell_vol"].mean() * 0.25  # fallback baseline

    # check spikes in last CHECK_WINDOW
    spikes = []
    for i in range(len(df)-CHECK_WINDOW, len(df)):
        sv = df.at[i, "sell_vol"]
        if sv >= VOL_MULT * avg_sell and sv >= MIN_BASE_VOLUME:
            spikes.append((i, sv))

    if not spikes:
        return None

    # price change across CHECK_WINDOW
    price_start = df.at[len(df)-CHECK_WINDOW-1, "close"]
    price_now = df.at[len(df)-1, "close"]
    price_change = (price_now - price_start) / price_start  # fractional

    return {
        "avg_sell": avg_sell,
        "spikes": spikes,
        "price_change": price_change,
        "price_now": price_now,
        "last_sell": df.at[len(df)-1, "sell_vol"],
        "close": price_now
    }

# ===== MAIN SCAN =====
def run_once():
    alerts = []
    for sym in SYMBOLS:
        df = fetch_klines(sym)
        if df is None:
            continue
        info = detect_sell_spike(df)
        if info is None:
            continue

        # apply price drop filter: we want sell spikes but price hasn't collapsed yet
        if info["price_change"] > -MAX_PRICE_DROP:
            # build message
            # compute percent spike relative to avg
            last_sv = info["last_sell"]
            avg = info["avg_sell"] if info["avg_sell"]>0 else 1
            ratio = last_sv / avg
            pct_drop = info["price_change"] * 100
            msg = (f"🐋 EARLY SELL ALERT — {sym}\n"
                   f"Price: {info['price_now']:.6f}  (Δ last {pct_drop:.2f}%)\n"
                   f"Last sell vol: {last_sv:.2f}  ({ratio:.1f}x average)\n"
                   f"Detected spikes in last {CHECK_WINDOW} candles: {len(info['spikes'])}\n"
                   f"Note: büyük satış var ama fiyat henüz sert düşmedi — dikkatle izle.")
            alerts.append(msg)
        else:
            # price already dropped more than threshold -> not 'early' anymore; skip or optionally alert as ongoing dump
            # we skip to focus on 'henüz çok düşmemiş' cases
            continue

    # send alerts
    for a in alerts:
        send_telegram(a)
        time.sleep(0.5)  # small pause

    return alerts

if __name__ == "__main__":
    print("Starting futures early-sell scanner:", datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
    # run single scan (for cron/GitHub Actions). If you want continuous, place in loop.
    found = run_once()
    if not found:
        print("No early sell alerts this run.")
    else:
        print(f"Sent {len(found)} alerts.")

