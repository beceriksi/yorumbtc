import os
import requests
import pandas as pd
from datetime import datetime

# =================== Ayarlar ===================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
COINS = ["BTCUSDT", "ETHUSDT"]
TIMEFRAMES = {"Günlük": "1d", "4 Saatlik": "4h"}
LIMIT = 200  # Mum sayısı
VOL_MULTIPLIER = 1.5  # Hacim artışı için çarpan

# =================== Telegram Fonksiyonu ===================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Telegram bilgileri eksik!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": message})
        print(f"Telegram mesaj durumu: {r.status_code}")
    except Exception as e:
        print(f"Telegram hatası: {e}")

# =================== Binance API ===================
def get_klines(symbol, interval, limit=LIMIT):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        df = pd.DataFrame(data, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_asset_volume","num_trades",
            "taker_buy_base","taker_buy_quote","ignore"
        ])
        df[["open","high","low","close","volume"]] = df[["open","high","low","close","volume"]].astype(float)
        return df
    except Exception as e:
        print(f"API hatası ({symbol} {interval}): {e}")
        return None

# =================== Analiz ===================
def analyze(df):
    if len(df) < 20:
        return ["⚠️ Veri yetersiz, analiz sınırlı"]

    df['ema_short'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema_long'] = df['close'].ewm(span=21, adjust=False).mean()
    df['change'] = df['close'].pct_change()
    df['vol_avg'] = df['volume'].rolling(10).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]
    signals = []

    # EMA kesişimi
    if last['ema_short'] > last['ema_long'] and prev['ema_short'] <= prev['ema_long']:
        signals.append("🟢 EMA kısa üstü → Yükseliş sinyali")
    elif last['ema_short'] < last['ema_long'] and prev['ema_short'] >= prev['ema_long']:
        signals.append("🔴 EMA kısa altı → Düşüş sinyali")

    # Son mum rengi
    if last['close'] > last['open']:
        signals.append("📈 Son mum yeşil → Alıcı baskısı")
    else:
        signals.append("📉 Son mum kırmızı → Satıcı baskısı")

    # Hacim artışı
    if last['volume'] > VOL_MULTIPLIER * last['vol_avg']:
        signals.append("💥 Hacim artışı tespit edildi")

    # Balina satışı
    if -0.01 < last['change'] < 0 and last['volume'] > 5*last['vol_avg']:
        signals.append("🐋 Balina satışı olabilir")

    # Trend yönü (20 mumluk)
    trend = last['close'] - df['close'].iloc[-20]
    if trend > 0:
        signals.append("⬆️ Kısa dönem trend yukarı")
    elif trend < 0:
        signals.append("⬇️ Kısa dönem trend aşağı")
    else:
        signals.append("➡️ Trend yatay")

    return signals

# =================== Main ===================
def main():
    print(f"=== Multi-Timeframe Trend Bot Çalışıyor... {datetime.now()} ===")
    msg = f"📊 BTC & ETH Trend Yorumları ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"

    for coin in COINS:
        for label, tf in TIMEFRAMES.items():
            df = get_klines(coin, tf)
            if df is None:
                msg += f"{coin} ({label}): Veri alınamadı\n"
                continue
            analysis = analyze(df)
            msg += f"{coin} ({label}):\n" + "\n".join(analysis) + "\n\n"

    send_telegram(msg)

if __name__ == "__main__":
    main()
