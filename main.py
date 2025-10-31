import os
import requests
import pandas as pd
from datetime import datetime

# =================== Ayarlar ===================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
INTERVALS = ["1d", "4h"]  # Günlük ve 4 saatlik
COINS = ["BTCUSDT", "ETHUSDT"]
VOL_MULTIPLIER = 3  # Hacim patlaması için çarpan
MIN_ROWS = 20        # Analiz için minimum mum sayısı

# =================== Telegram Fonksiyonları ===================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Telegram bilgileri eksik! Secretleri kontrol et.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": CHAT_ID, "text": message})
        print(f"Telegram mesaj durumu: {r.status_code}")
    except Exception as e:
        print("Telegram hatası:", e)

# =================== Binance Kline Verisi ===================
def get_klines(symbol, interval, limit=500):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if not data or len(data) < MIN_ROWS:
            return None
        df = pd.DataFrame(data, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_asset_volume","trades","taker_buy_base","taker_buy_quote","ignore"
        ])
        df = df[["open","high","low","close","volume"]].astype(float)
        return df
    except Exception as e:
        print(f"API hatası ({symbol} {interval}): {e}")
        return None

# =================== Sinyal Analizi ===================
def analyze(df):
    if df is None or len(df) < MIN_ROWS:
        return ["❌ Veri yetersiz, analiz yapılamadı"], "Bekle ⚪"

    df['ema_short'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema_long'] = df['close'].ewm(span=21, adjust=False).mean()
    df['change'] = df['close'].pct_change()
    df['vol_avg'] = df['volume'].rolling(10, min_periods=1).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]
    signals = []

    # EMA kesişimi
    if last['ema_short'] > last['ema_long'] and prev['ema_short'] <= prev['ema_long']:
        signals.append("🟢 EMA kısa üstü → Yükseliş sinyali")
    elif last['ema_short'] < last['ema_long'] and prev['ema_short'] >= prev['ema_long']:
        signals.append("🔴 EMA kısa altı → Düşüş sinyali")

    # Son mum (Price Action)
    if last['close'] > last['open']:
        signals.append("📈 Son mum yeşil → Alıcı baskısı")
    else:
        signals.append("📉 Son mum kırmızı → Satıcı baskısı")

    # Hacim patlaması
    if last['volume'] > VOL_MULTIPLIER * last['vol_avg']:
        signals.append("💥 Hacim artışı tespit edildi")

    # Balina satışı
    if -0.01 < last['change'] < 0 and last['volume'] > 5*last['vol_avg']:
        signals.append("🐋 Balina satışı olabilir")

    # Trend yönü
    trend = last['close'] - df['close'].iloc[0]
    if trend > 0:
        signals.append("⬆️ Kısa dönem trend yukarı")
    elif trend < 0:
        signals.append("⬇️ Kısa dönem trend aşağı")
    else:
        signals.append("➡️ Trend yatay")

    # Tahmini Öneri
    recommendation = "Bekle ⚪"
    if last['ema_short'] > last['ema_long'] and last['close'] > last['open']:
        recommendation = "BUY 🟢"
    elif last['ema_short'] < last['ema_long'] and last['close'] < last['open']:
        recommendation = "SELL 🔴"

    return signals, recommendation

# =================== Main ===================
def main():
    print(f"=== Binance PA + EMA Trend Botu Çalışıyor... {datetime.now()} ===")
    msg = f"📊 BTC & ETH Günlük ve 4 Saatlik Trend Yorumları ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"

    for coin in COINS:
        for tf in INTERVALS:
            label = "Günlük" if tf=="1d" else "4 Saatlik"
            df = get_klines(coin, tf)
            if df is None or len(df) < MIN_ROWS:
                msg += f"{coin} ({label}): ❌ Veri yetersiz, analiz yapılamadı\n\n"
                continue
            signals, recommendation = analyze(df)
            msg += f"{coin} ({label}):\n" + "\n".join(signals) + f"\nTahmini Öneri: {recommendation}\n\n"

    send_telegram(msg)
    print("✅ Telegram mesajı gönderildi.")

if __name__ == "__main__":
    main()
