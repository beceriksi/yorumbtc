#!/usr/bin/env python3
"""
Auto TF whale BUY/SELL scanner for Binance Futures (USDT perpetual).
- Multi-TF: 15m, 1h, 4h
- Auto mode (C): if 4h trend strong -> use 1h primary, else use 4h primary
- Uses taker_buy_base from /fapi/v1/klines to approximate buy/sell taker volumes.
- Sends Telegram alert only on confluence (to avoid spam).
"""
import os, time, requests
import pandas as pd
import numpy as np
from datetime import datetime

# ===== CONFIG =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOLS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","AVAXUSDT","ARBUSDT","OPUSDT","DOGEUSDT"]
# Timeframes
TFS = {"15m":"15m","1h":"1h","4h":"4h"}  # labels only
# fapi klines intervals mapping (Binance uses same string)
INTERVAL_15 = "15m"
INTERVAL_1H = "1h"
INTERVAL_4H = "4h"

# scanning params
LOOKBACK = 120               # how many candles to fetch for averages (per TF)
VOL_MULT = 3.0               # spike threshold multiplier (tweakable)
MIN_BASE_VOL = 10.0          # minimum absolute base sell/buy to consider (reduce noise)
MAX_PRICE_DROP_EARLY = 0.03  # if price already dropped >3% over window, consider it's not 'early'
EMA_FAST = 20
EMA_SLOW = 50
EMA_STRONG_SPREAD_PCT = 0.02  # if 4h ema spread >2% consider trend strong

# endpoints
FAPI_KLINES = "https://fapi.binance.com/fapi/v1/klines"

REQUEST_TIMEOUT = 8

# ===== HELPERS =====
def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram not configured. Message:\n", text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode":"HTML"}, timeout=10)
        if r.status_code != 200:
            print("Telegram error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram exception:", e)

def fetch_futures_klines(symbol, interval, limit=LOOKBACK):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        r = requests.get(FAPI_KLINES, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or len(data) == 0:
            return None
        df = pd.DataFrame(data, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_asset_volume","num_trades",
            "taker_buy_base","taker_buy_quote","ignore"
        ])
        # numeric cast
        df[["open","high","low","close","volume","taker_buy_base","taker_buy_quote"]] = df[["open","high","low","close","volume","taker_buy_base","taker_buy_quote"]].astype(float)
        return df
    except Exception as e:
        # silent failure
        # print(f"fetch error {symbol} {interval}: {e}")
        return None

def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def simple_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.rolling(period, min_periods=1).mean()
    ma_down = down.rolling(period, min_periods=1).mean().replace(0,1e-9)
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

# detect spikes on one timeframe df; returns dict or None
def detect_spike_direction(df, side="sell", lookback_exclude=3, mult=VOL_MULT):
    """
    side: 'sell' or 'buy'
    compute taker sell ~ volume - taker_buy_base
    compute rolling mean excluding last lookback_exclude candles for baseline
    return info if any of last lookback_exclude candles spike > mult * baseline and above MIN_BASE_VOL
    """
    if df is None or len(df) < lookback_exclude + 5:
        return None
    temp = df.copy().reset_index(drop=True)
    # compute buy/taker values
    temp["taker_buy"] = temp["taker_buy_base"]
    temp["sell_vol"] = (temp["volume"] - temp["taker_buy"]).clip(lower=0.0)
    temp["buy_vol"] = temp["taker_buy"].clip(lower=0.0)

    target_col = "sell_vol" if side=="sell" else "buy_vol"
    hist = temp[target_col].iloc[:-lookback_exclude]
    baseline = hist.mean() if len(hist)>0 else 0.0
    if baseline <= 0:
        baseline = max(1.0, temp[target_col].mean()*0.25)  # fallback

    spikes = []
    for i in range(len(temp)-lookback_exclude, len(temp)):
        val = temp.at[i, target_col]
        if val >= baseline * mult and val >= MIN_BASE_VOL:
            spikes.append({"idx": i, "val": val, "ts": temp.at[i,"open_time"], "close": temp.at[i,"close"]})
    if not spikes:
        return None
    # price change across the lookback_exclude window (old -> now)
    price_start = float(temp.at[len(temp)-lookback_exclude-1, "close"])
    price_now = float(temp.at[len(temp)-1, "close"])
    price_change = (price_now - price_start) / price_start
    return {"baseline": baseline, "spikes": spikes, "price_change": price_change, "price_now": price_now}

# decide primary timeframe based on 4h trend strength (C mode)
def choose_primary_tf(symbol):
    df4 = fetch_futures_klines(symbol, INTERVAL_4H, limit=100)
    if df4 is None or len(df4) < 30:
        return INTERVAL_1H  # fallback
    df4['ema_fast'] = ema(df4['close'], EMA_FAST)
    df4['ema_slow'] = ema(df4['close'], EMA_SLOW)
    last = df4.iloc[-1]
    # relative spread pct between fast and slow
    spread = abs(last['ema_fast'] - last['ema_slow']) / last['close']
    if spread >= EMA_STRONG_SPREAD_PCT:
        # strong trend -> prefer 1h primary to catch intraday moves
        return INTERVAL_1H
    else:
        # weak/flat -> use 4h primary for higher-confidence signals
        return INTERVAL_4H

# main per-symbol analysis using multi-tf confluence
def analyze_symbol(symbol):
    # choose primary TF automatically
    primary = choose_primary_tf(symbol)
    confirm_tf = INTERVAL_1H if primary==INTERVAL_4H else INTERVAL_4H  # confirmation opposite
    short_tf = INTERVAL_15

    # fetch dfs
    df_p = fetch_futures_klines(symbol, primary, limit=LOOKBACK)
    df_c = fetch_futures_klines(symbol, confirm_tf, limit=LOOKBACK)
    df_s = fetch_futures_klines(symbol, short_tf, limit=LOOKBACK)

    if df_p is None:
        return None

    # detect sell spike and buy spike on each TF
    p_sell = detect_spike_direction(df_p, side="sell")
    p_buy  = detect_spike_direction(df_p, side="buy")
    c_sell = detect_spike_direction(df_c, side="sell") if df_c is not None else None
    c_buy  = detect_spike_direction(df_c, side="buy") if df_c is not None else None
    s_sell = detect_spike_direction(df_s, side="sell") if df_s is not None else None
    s_buy  = detect_spike_direction(df_s, side="buy") if df_s is not None else None

    # compute some indicators on primary
    df = df_p.copy()
    df['ema_fast'] = ema(df['close'], EMA_FAST)
    df['ema_slow'] = ema(df['close'], EMA_SLOW)
    df['rsi'] = simple_rsi(df['close'], period=14)
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # build human-like decision
    alerts = []
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    price = float(last['close'])

    # BUY condition: primary buy spike AND (confirm buy spike OR short_tf buy spike) AND EMA/RSI supportive
    if p_buy and (c_buy or s_buy):
        # extra filters
        if last['ema_fast'] > last['ema_slow'] and last['rsi'] < 70:
            # ensure price hasn't already soared (avoid late)
            if p_buy['price_change'] < 0.08:  # <8% rise over window
                strength = (p_buy['spikes'][-1]['val'] / p_buy['baseline'])
                alerts.append({
                    "type":"BUY",
                    "symbol":symbol,
                    "price":price,
                    "strength":strength,
                    "primary":primary,
                    "details":p_buy
                })

    # SELL condition: primary sell spike AND (confirm sell spike OR short_tf sell spike) AND EMA/RSI supportive
    if p_sell and (c_sell or s_sell):
        if last['ema_fast'] < last['ema_slow'] and last['rsi'] > 30:
            # ensure price hasn't already collapsed beyond threshold (we want early)
            if p_sell['price_change'] > -0.12:  # allow up to -12% drop across window; still early detection
                strength = (p_sell['spikes'][-1]['val'] / p_sell['baseline'])
                alerts.append({
                    "type":"SELL",
                    "symbol":symbol,
                    "price":price,
                    "strength":strength,
                    "primary":primary,
                    "details":p_sell
                })

    # return alerts list (empty if none)
    return alerts

# top-level run: scan all symbols once and send alerts
def run_once():
    total_alerts = []
    for s in SYMBOLS:
        try:
            res = analyze_symbol(s)
            if not res:
                continue
            for a in res:
                # format human message
                typ = a['type']
                sym = a['symbol']
                pri = a['primary']
                strength = a['strength']
                price = a['price']
                pct = (strength - 1.0) * 100.0
                # details
                last_sv = a['details']['spikes'][-1]['val']
                avg = a['details']['baseline']
                price_change = a['details']['price_change'] * 100.0
                msg = (f"🐋 <b>Early {typ} Alert</b> — {sym}\n"
                       f"Primary TF: {pri}  Price: {price:.6f}\n"
                       f"Spike: {last_sv:.1f} ({last_sv/avg:.2f}x avg)  Δprice: {price_change:.2f}%\n"
                       f"Note: büyük taker {'buy' if typ=='BUY' else 'sell'} hacmi tespit edildi — henüz tam dump/pump değil, dikkatle izle.")
                send_telegram(msg)
                total_alerts.append(msg)
                time.sleep(0.6)
        except Exception as e:
            # continue on error per symbol
            print("Error analyzing", s, e)
            continue
    return total_alerts

# ===== ENTRY =====
if __name__ == "__main__":
    # run single pass (suitable for GitHub Actions cron); if you want continuous loop, wrap in while True with sleep
    print("Running futures early sell/buy scanner:", datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
    alerts = run_once()
    if not alerts:
        print("No alerts this run.")
    else:
        print(f"Sent {len(alerts)} alerts.")
