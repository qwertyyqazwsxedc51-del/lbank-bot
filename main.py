import os
import time
import hmac
import hashlib
import requests
import pandas as pd
import ccxt

LBANK_API_KEY = os.getenv("LBANK_API_KEY")
LBANK_API_SECRET = os.getenv("LBANK_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOLS = ["NEAR/USDT", "PAXG/USDT"]
TIMEFRAME = "15m"
LEVERAGE = 10
DEFAULT_MARGIN = 2.0

exchange = ccxt.lbank({
    'apiKey': LBANK_API_KEY,
    'secret': LBANK_API_SECRET,
    'enableRateLimit': True,
})

def send_telegram(msg):
    if TELEGRAM_TOKEN and CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        except Exception as e:
            print(f"Telegram error: {e}")

def get_futures_balance():
    """دریافت مستقیم موجودی از سرور اختصاصی فیوچرز البانک"""
    if not LBANK_API_KEY or not LBANK_API_SECRET:
        return 0.0
    
    url = "https://lbkperp.lbank.com/cfd/openApi/v1/pub/account"
    timestamp = str(int(time.time() * 1000))
    params_str = f"api_key={LBANK_API_KEY}&timestamp={timestamp}"
    sign = hmac.new(LBANK_API_SECRET.encode('utf-8'), params_str.encode('utf-8'), hashlib.sha256).hexdigest()
    
    headers = {
        'api_key': LBANK_API_KEY,
        'sign': sign,
        'timestamp': timestamp,
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    try:
        res = requests.post(url, data=params_str, headers=headers, timeout=10)
        print(f"[RAW Futures Response]: {res.text}")
        data = res.json()
        if data.get("result") == "true" or data.get("code") == 200:
            for item in data.get("data", []):
                if item.get("asset") == "USDT":
                    return float(item.get("availableMargin", item.get("free", 0.0)))
    except Exception as e:
        print(f"[!] Futures API Error: {e}")
    return 0.0

def calculate_ema(df, period=20):
    return df['close'].ewm(span=period, adjust=False).mean()

def analyze_market(symbol, margin):
    print(f"\n--- Checking {symbol} ---")
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=50)
        if not ohlcv or len(ohlcv) < 25:
            print("Data insufficient.")
            return

        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        df['ema20'] = calculate_ema(df, 20)

        prev = df.iloc[-2]
        curr_price = df.iloc[-1]['close']
        body_pct = abs(prev['close'] - prev['open']) / (prev['high'] - prev['low'] + 1e-9)

        print(f"Price: {curr_price} | EMA20: {prev['ema20']:.4f} | Body Pct: {body_pct:.2f}")

        if body_pct < 0.35:
            print("Setup rejected: Signal candle is a Doji (< 35% body).")
            return

        # ستاپ پرایس‌اکشن خرید M2B
        if prev['low'] <= prev['ema20'] and prev['close'] > prev['ema20'] and prev['close'] > prev['open']:
            stop_loss = prev['low']
            take_profit = curr_price + (curr_price - stop_loss) * 1.5
            msg = (
                f"🟢 سیگنال خرید فیوچرز (M2B)\n"
                f"ارز: {symbol}\n"
                f"نقطه ورود: {curr_price}\n"
                f"حد ضرر: {stop_loss}\n"
                f"حد سود: {take_profit:.4f}\n"
                f"مارجین معامله: {margin:.2f}$ (لوریج {LEVERAGE})"
            )
            print(msg)
            send_telegram(msg)

        # ستاپ پرایس‌اکشن فروش M2S
        elif prev['high'] >= prev['ema20'] and prev['close'] < prev['ema20'] and prev['close'] < prev['open']:
            stop_loss = prev['high']
            take_profit = curr_price - (stop_loss - curr_price) * 1.5
            msg = (
                f"🔴 سیگنال فروش فیوچرز (M2S)\n"
                f"ارز: {symbol}\n"
                f"نقطه ورود: {curr_price}\n"
                f"حد ضرر: {stop_loss}\n"
                f"حد سود: {take_profit:.4f}\n"
                f"مارجین معامله: {margin:.2f}$ (لوریج {LEVERAGE})"
            )
            print(msg)
            send_telegram(msg)
        else:
            print("Waiting for price action setup...")

    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")

if __name__ == "__main__":
    print(f"Starting execution at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}...")
    
    futures_balance = get_futures_balance()
    # مارجین ۰.۵٪ موجودی با حداقل ۲ دلار
    trade_margin = max(DEFAULT_MARGIN, futures_balance * 0.005)
    
    print(f"[*] Futures USDT Balance: {futures_balance:.2f}$ | Active Margin per Trade: {trade_margin:.2f}$")
    
    for sym in SYMBOLS:
        analyze_market(sym, trade_margin)
        
    print("Done.")
    
