import os
import requests
import pandas as pd
from datetime import datetime

# =================== Ayarlar ===================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INTERVALS = ["1d", "4h"]  # Günlük ve 4 saatlik
COINS = ["BTCUSDT", "ETHUSDT"]
VOL_MULTIPLIER = 3
MIN_ROWS = 10  # Günlük veri için düşürüldü

# =================== Telegram Fonksiyonu ===================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Telegram bilgileri eksik")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": message})
    except Exception as e:
        print("Telegram Error:", e)

# =================== Binance Kline Fonksiyonu ===================
def get_klines(symbol, interval, limit=200):
    for _ in range(3):  # 3 kez dene
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            r = requests.get(url, timeout=10)
            data = r.json()
            if data and len(data) >= MIN_ROWS:
                df = pd.DataFrame(data, columns=[
                    "open_time","open","high","low","close","volume",
                    "close_time","quote_asset_volume","trades","taker_buy_base","taker_buy_quote","ignore"
                ])
                df = df[["open","high","low","close","volume"]].astype(float)
                return df
        except:
            pass
    return None

# =================== Analiz Fonksiyonu ===================
def analyze(df):
    if df is None or len(df) < MIN_ROWS:
        return [], "Veri Az"

    df['ema_short'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema_long'] = df['close'].ewm(span=21, adjust=False).mean()
    df['chg'] = df['close'].pct_change()
    df['vol_avg'] = df['volume'].rolling(10).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]
    signals = []

    # EMA Cross
    if last['ema_short'] > last['ema_long'] and prev['ema_short'] <= prev['ema_long']:
        signals.append("🟢 EMA Cross Up (Al Sinyali)")
    elif last['ema_short'] < last['ema_long'] and prev['ema_short'] >= prev['ema_long']:
        signals.append("🔴 EMA Cross Down (Sat Sinyali)")

    # Mum rengi
    if last['close'] > last['open']:
        signals.append("📈 Alıcı Baskın")
    else:
        signals.append("📉 Satıcı Baskın")

    # Volume
    if last['volume'] > VOL_MULTIPLIER * last['vol_avg']:
        signals.append("💥 Hacim Patlaması")

    # Trend
    if last['close'] > df['close'].iloc[0]:
        signals.append("⬆️ Trend Yukarı")
    else:
        signals.append("⬇️ Trend Aşağı")

    # Öneri
    if last['ema_short'] > last['ema_long'] and last['close'] > last['open']:
        suggestion = "BUY 🟢"
    elif last['ema_short'] < last['ema_long'] and last['close'] < last['open']:
        suggestion = "SELL 🔴"
    else:
        suggestion = "BEKLE ⚪"

    return signals, suggestion

# =================== Main ===================
def main():
    print(f"=== Çalışıyor... {datetime.now()} ===")
    msg = f"📊 Günlük + 4H Trend Analizi ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"

    for coin in COINS:
        for t in INTERVALS:
            df = get_klines(coin, t)
            label = "Günlük" if t=="1d" else "4 Saatlik"

            if df is None:
                continue  # Sessizce geç

            signals, rec = analyze(df)
            msg += f"{coin} ({label}):\n"
            msg += "\n".join(signals) + f"\n➡️ Öneri: {rec}\n\n"

    send_telegram(msg)
    print("✅ Gönderildi")

if __name__ == "__main__":
    main()
