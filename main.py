import os
import time
import hashlib
import hmac
import requests
import ccxt
import pandas as pd

api_key = os.getenv("LBANK_API_KEY", "")
api_secret = os.getenv("LBANK_API_SECRET", "")
tele_token = os.getenv("TELEGRAM_TOKEN", "")
chat_id = os.getenv("CHAT_ID", "")

SYMBOLS = ["NEAR/USDT", "PAXG/USDT"]
LEVERAGE = 10
BASE_MARGIN_USD = 2.0
RISK_PERCENT = 0.50
TIMEFRAME = "15m"

# کلاینت فیوچرز اختصاصی LBank
exchange = ccxt.lbank({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',
        'createMarketBuyOrderRequiresPrice': False,
    }
})

def send_telegram(message: str):
    if not tele_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{tele_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}, timeout=8)
    except Exception as e:
        print(f"[Telegram Error] {e}")

def get_lbank_futures_balance():
    """خواندن مستقیم کیف‌پول فیوچرز LBank"""
    # راهکار ۱: استفاده از ccxt با مود swap
    try:
        bal = exchange.fetch_balance(params={'type': 'swap'})
        if 'USDT' in bal and 'free' in bal['USDT']:
            val = float(bal['USDT']['free'] or 0.0)
            if val > 0:
                return val
        if 'free' in bal and 'USDT' in bal['free']:
            val = float(bal['free']['USDT'] or 0.0)
            if val > 0:
                return val
    except Exception as e:
        print(f"[CCXT Swap Balance Notice] {e}")

    # راهکار ۲: اندپوینت اختصاصی سرور پرپچوال LBank
    if api_key and api_secret:
        try:
            ts = str(int(time.time() * 1000))
            params = {
                "api_key": api_key,
                "timestamp": ts
            }
            sorted_str = "&".join([f"{k}={params[k]}" for k in sorted(params.keys())])
            sign = hmac.new(api_secret.encode('utf-8'), sorted_str.encode('utf-8'), hashlib.sha256).hexdigest()
            
            url = f"https://lbkperp.lbank.com/cfd/openApi/v1/pub/user/assets?{sorted_str}&sign={sign}"
            res = requests.get(url, headers={"api_key": api_key, "timestamp": ts, "signature": sign}, timeout=7)
            if res.status_code == 200:
                res_json = res.json()
                data = res_json.get("data") or []
                if isinstance(data, list):
                    for coin in data:
                        symbol = coin.get("currency") or coin.get("asset") or ""
                        if symbol.upper() == "USDT":
                            return float(coin.get("availableMargin") or coin.get("availableBalance") or coin.get("balance") or 0.0)
        except Exception as e:
            print(f"[Direct API Notice] {e}")

    return 0.0

def get_dynamic_margin():
    if not (api_key and api_secret):
        return BASE_MARGIN_USD

    free_usdt = get_lbank_futures_balance()

    if free_usdt > 0.0:
        margin = max(BASE_MARGIN_USD, free_usdt * RISK_PERCENT)
    else:
        # اگر صفر خواند، حداقل ۲ دلار مارجین پیش‌فرض حفظ شود
        margin = BASE_MARGIN_USD

    print(f"[*] Free USDT: {free_usdt:.2f}$ | Allocated Margin: {margin:.2f}$")
    return round(margin, 2)

def place_order_safe(symbol: str, side: str, margin_usd: float, sl_price: float, tp_price: float):
    if not (api_key and api_secret):
        print(f"[Mode] API Keys not present, running in Signal-Only mode.")
        return None

    try:
        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker.get('last') or ticker.get('close')
        if not current_price:
            return None

        raw_amount = (margin_usd * LEVERAGE) / current_price
        try:
            amount = float(exchange.amount_to_precision(symbol, raw_amount))
        except Exception:
            amount = round(raw_amount, 2)

        print(f"[*] Placing {side.upper()} order on {symbol} | Amount: {amount}")
        order = exchange.create_order(
            symbol=symbol,
            type='market',
            side=side,
            amount=amount,
            price=current_price,
            params={'leverage': LEVERAGE}
        )
        print(f"[+] Order Filled: {order.get('id', 'N/A')}")
        return order
    except Exception as e:
        err_msg = f"⚠️ *خطا در ثبت سفارش ({symbol}):*\n`{e}`"
        print(err_msg)
        send_telegram(err_msg)
        return None

def fetch_data(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=50)
        return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except Exception as e:
        print(f"[Fetch Error {symbol}] {e}")
        return None

def calc_indicators(df):
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift()).abs()
    lc = (df['low'] - df['close'].shift()).abs()
    df['atr'] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()
    return df

def analyze(symbol: str, margin: float):
    df = fetch_data(symbol)
    if df is None or len(df) < 25:
        return

    df = calc_indicators(df)
    c = df.iloc[-2]
    curr = df.iloc[-1]
    
    ema = c['ema20']
    atr = c['atr']
    rng = c['high'] - c['low']
    body = abs(c['close'] - c['open'])

    if rng == 0 or (body / rng) < 0.35:
        print(f"[{symbol}] Price: {curr['close']} | EMA20: {ema:.4f} | No setup (Doji/Weak)")
        return

    close_in_upper_third = (c['close'] - c['low']) >= (0.65 * rng)
    close_in_lower_third = (c['high'] - c['close']) >= (0.65 * rng)

    # ستاپ M2B (خرید)
    if c['close'] > ema and c['open'] >= ema and c['close'] > c['open'] and close_in_upper_third:
        sl = c['low'] - (0.2 * atr)
        risk = c['close'] - sl
        if risk <= 0: return
        tp = c['close'] + (2.0 * risk)

        msg = (
            f"🟢 *سیگنال خرید (LONG)*\n"
            f"نماد: `{symbol}`\n"
            f"قیمت ورود: `{curr['close']}`\n"
            f"مارجین: `{margin}$` | اهرم: `x{LEVERAGE}`\n"
            f"🛑 حد ضرر: `{sl:.4f}`\n"
            f"🎯 حد سود: `{tp:.4f}`"
        )
        print(f"[{time.strftime('%H:%M:%S')}] Signal LONG on {symbol}")
        send_telegram(msg)
        place_order_safe(symbol, 'buy', margin, sl, tp)

    # ستاپ M2S (فروش)
    elif c['close'] < ema and c['open'] <= ema and c['close'] < c['open'] and close_in_lower_third:
        sl = c['high'] + (0.2 * atr)
        risk = sl - c['close']
        if risk <= 0: return
        tp = c['close'] - (2.0 * risk)

        msg = (
            f"🔴 *سیگنال فروش (SHORT)*\n"
            f"نماد: `{symbol}`\n"
            f"قیمت ورود: `{curr['close']}`\n"
            f"مارجین: `{margin}$` | اهرم: `x{LEVERAGE}`\n"
            f"🛑 حد ضرر: `{sl:.4f}`\n"
            f"🎯 حد سود: `{tp:.4f}`"
        )
        print(f"[{time.strftime('%H:%M:%S')}] Signal SHORT on {symbol}")
        send_telegram(msg)
        place_order_safe(symbol, 'sell', margin, sl, tp)
    else:
        print(f"[{symbol}] Price: {curr['close']} | EMA20: {ema:.4f} | Waiting for setup...")

if __name__ == "__main__":
    for i in range(9):
        margin = get_dynamic_margin()
        for sym in SYMBOLS:
            analyze(sym, margin)
        if i < 8:
            time.sleep(30)
        
