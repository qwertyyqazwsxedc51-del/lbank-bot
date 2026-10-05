import os
import time
import hmac
import hashlib
import requests
import pandas as pd
import ccxt

API_KEY = os.getenv("LBANK_API_KEY")
API_SECRET = os.getenv("LBANK_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOLS = ["NEAR/USDT", "PAXG/USDT"]
TIMEFRAME = "15m"
LEVERAGE = 10
DEFAULT_MARGIN = 2.0

exchange = ccxt.lbank({
    'apiKey': API_KEY,
    'secret': API_SECRET,
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
    if not API_KEY or not API_SECRET:
        print("[!] API keys missing.")
        return 0.0

    timestamp = str(int(time.time() * 1000))
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    # تلاش ۱: اندپوینت فیوچرز البانک
    try:
        url = "https://lbkperp.lbank.com/cfd/openApi/v1/pub/account"
        params_str = f"api_key={API_KEY}&timestamp={timestamp}"
        sign = hmac.new(API_SECRET.encode('utf-8'), params_str.encode('utf-8'), hashlib.sha256).hexdigest()
        perp_headers = {
            **headers,
            'api_key': API_KEY,
            'sign': sign,
            'timestamp': timestamp,
        }
        res = requests.post(url, data=params_str + f"&sign={sign}", headers=perp_headers, timeout=10)
        print(f"[LBK Perp Response]: {res.status_code} - {res.text[:200]}")
        if res.status_code == 200:
            res_json = res.json()
            if str(res_json.get("result")).lower() == "true" or res_json.get("code") == 200:
                data_items = res_json.get("data", [])
                if isinstance(data_items, list):
                    for item in data_items:
                        if str(item.get("asset", "")).upper() == "USDT":
                            return float(item.get("availableMargin", item.get("free", 0.0)))
    except Exception as e:
        print(f"[!] Perp API Error: {e}")

    # تلاش ۲: اندپوینت کیف‌پول اصلی
    try:
        url = "https://api.lbkex.com/v2/supplemental/user_info.do"
        params_str = f"api_key={API_KEY}&timestamp={timestamp}"
        sign = hmac.new(API_SECRET.encode('utf-8'), params_str.encode('utf-8'), hashlib.sha256).hexdigest()
        data = {'api_key': API_KEY, 'timestamp': timestamp, 'sign': sign}
        res = requests.post(url, data=data, headers=headers, timeout=10)
        print(f"[LBK Wallet Response]: {res.status_code} - {res.text[:200]}")
        if res.status_code == 200:
            res_json = res.json()
            if str(res_json.get("result")).lower() == "true":
                balances = res_json.get("data", {}).get("balances", [])
                for b in balances:
                    asset = b.get("asset", b.get("currency", ""))
                    if str(asset).lower() == "usdt":
                        return float(b.get("free", b.get("available", 0.0)))
    except Exception as e:
        print(f"[!] Wallet API Error: {e}")

    return 0.0

def analyze_market(symbol, margin):
    print(f"\n--- Checking {symbol} ---")
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=50)
        if not ohlcv or len(ohlcv) < 25:
            print("Data insufficient.")
            return

        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()

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
                f"مارجین: {margin:.2f}$ (لوریج {LEVERAGE})"
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
                f"مارجین: {margin:.2f}$ (لوریج {LEVERAGE})"
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

    print(f"[*] USDT Balance: {balance:.2f}$ | Active Margin per Trade: {trade_margin:.2f}$")

    for sym in SYMBOLS:
        analyze_market(sym, trade_margin)

    print("Done.")
        
