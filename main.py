print("Starting analysis cycle...")
import ccxt
import time
import requests
import pandas as pd
import numpy as np

# ================= تنظیمات و کلیدها =================
API_KEY = "3fbd463c-b7a1-403c-955c-34958a3537d8"
SECRET_KEY = "6DEAC5931CAAAAE74956CBCAC10B9FAB"
TELEGRAM_TOKEN = "GAPGPTMASKTOKENa7iq162fcjuX0X"
CHAT_ID = "1499492919"

SYMBOL = "NEAR/USDT"
TIMEFRAME = "5m"
BASE_MARGIN = 2.0  # مارجین پایه ۲ دلار
LEVERAGE = 10      # لوریج ۱۰

exchange = ccxt.lbank({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'options': {'defaultType': 'swap'},
    'enableRateLimit': True,
})

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def get_market_data():
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['tr'] = np.maximum(df['high'] - df['low'], 
                          np.maximum(abs(df['high'] - df['close'].shift()), 
                                     abs(df['low'] - df['close'].shift())))
    df['atr'] = df['tr'].rolling(14).mean()
    return df

def analyze_and_trade():
    try:
        df = get_market_data()
        last = df.iloc[-2]      # کندل بسته شده قبلی (سیگنال)
        current = df.iloc[-1]   # کندل جاری
        
        body_size = abs(last['close'] - last['open'])
        candle_range = last['high'] - last['low']
        
        # فیلتر کندل دوجی / بدون بدنه ال بروکس
        if candle_range == 0 or (body_size / candle_range) < 0.35:
            return

        # ستاپ فروش (M2S / Bearish Breakout)
        if last['close'] < last['ema20'] and last['open'] < last['ema20']:
            if current['close'] < last['low']:  # تریگر شکست کف
                entry = current['close']
                sl = last['high'] + (last['atr'] * 0.2)
                tp1 = entry - (1.5 * (sl - entry))
                tp2 = entry - (2.5 * (sl - entry))
                
                msg = f"🔴 *سیگنال فروش پرایس‌اکشن (SHORT)*\n\nنماد: {SYMBOL}\nنقطه ورود: {entry:.4f}\nحد ضرر: {sl:.4f}\nتارگت ۱: {tp1:.4f}\nتارگت ۲: {tp2:.4f}\nاهرم: 10x"
                send_telegram(msg)
                print("Signal Sent: SHORT")
                time.sleep(900)

        # ستاپ خرید (M2B / Bullish Breakout)
        elif last['close'] > last['ema20'] and last['open'] > last['ema20']:
            if current['close'] > last['high']:  # تریگر شکست سقف
                entry = current['close']
                sl = last['low'] - (last['atr'] * 0.2)
                tp1 = entry + (1.5 * (entry - sl))
                tp2 = entry + (2.5 * (entry - sl))
                
                msg = f"🟢 *سیگنال خرید پرایس‌اکشن (LONG)*\n\nنماد: {SYMBOL}\nنقطه ورود: {entry:.4f}\nحد ضرر: {sl:.4f}\nتارگت ۱: {tp1:.4f}\nتارگت ۲: {tp2:.4f}\nاهرم: 10x"
                send_telegram(msg)
                print("Signal Sent: LONG")
                time.sleep(900)
                
    except Exception as e:
        print(f"Loop Error: {e}")

if __name__ == '__main__':
    analyze_and_trade()
    
