import os
import time
import hmac
import hashlib
import requests
import pandas as pd
import ccxt

api_key = os.getenv("LBANK_API_KEY", "")
api_secret = os.getenv("LBANK_API_SECRET", "")
telegram_token = os.getenv("TELEGRAM_TOKEN", "")
chat_id = os.getenv("CHAT_ID", "")

SYMBOLS = ["NEAR/USDT", "PAXG/USDT"]
TIMEFRAME = "15m"
LEVERAGE = 10
DEFAULT_MARGIN = 2.0

exchange = ccxt.lbank({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
})

def send_telegram(msg):
    if telegram_token and chat_id:
        try:
            url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
        except Exception as e:
            print(f"Telegram error: {e}")

def get_futures_balance():
    if not api_key or not api_secret:
        return 0.0

    try:
        url = "https://api.lbkex.com/v2/user_info.do"
        timestamp = str(int(time.time() * 1000))
        params = {
            'api_key': api_key,
            'timestamp': timestamp,
            'signature_method': 'HmacSHA256',
            'echostr': 'signal_bot'
        }
        
        sorted_keys = sorted(params.keys())
        query_string = '&'.join([f"{k}={params[k]}" for k in sorted_keys])
        sign = hmac.new(api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest().upper()
        params['sign'] = sign

        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.post(url, data=params, headers=headers, timeout=10)
        print(f"[LBK Response]: {res.status_code} - {res.text[:120]}")
        
        if res.status_code == 200:
            res_json = res.json()
            free_dict = res_json.get("data", {}).get("info", {}).get("free", {})
            if "usdt" in free_dict:
                return float(free_dict["usdt"])
    except Exception as err:
        print(f"[!] Balance Read Error: {err}")

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
        candle_range = prev['high'] - prev['low']
        body_pct = abs(prev['close'] - prev['open']) / (candle_range if candle_range > 0 else 1e-9)

        print(f"Price: {curr_price} | EMA20: {prev['ema20']:.4f} | Body Pct: {body_pct:.2f}")

        if body_pct < 0.35:
            print("Setup rejected: Signal candle is a Doji (< 35% body).")
            return

        # ستاپ خرید M2B
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

        # ستاپ فروش M2S
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
    
    balance = get_futures_balance()
    trade_margin = max(DEFAULT_MARGIN, balance * 0.005)
    
    print(f"[*] Account USDT Balance: {balance:.2f}$ | Active Margin per Trade: {trade_margin:.2f}$")
    
    for sym in SYMBOLS:
        analyze_market(sym, trade_margin)
        
    print("Done.")
    
