import os
import time
import hashlib
import hmac
import requests
import ccxt
import pandas as pd

# کلیدها از سکرت‌های گیت‌هاب
api_key = os.getenv("LBANK_API_KEY", "")
api_secret = os.getenv("LBANK_API_SECRET", "")
tele_token = os.getenv("TELEGRAM_TOKEN", "")
chat_id = os.getenv("CHAT_ID", "")

SYMBOLS = ["NEAR/USDT", "PAXG/USDT"]
LEVERAGE = 10
BASE_MARGIN_USD = 2.0
RISK_PERCENT = 0.50
TIMEFRAME = "15m"

# تنظیمات کلاینت برای دریافت قیمت و دیتا
exchange = ccxt.lbank({
    'enableRateLimit': True,
    'apiKey': api_key,
    'secret': api_secret,
    'options': {
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
    """دریافت دقیق موجودی تتر فیوچرز LBank از طریق اندپوینت رسمی REST"""
    if not (api_key and api_secret):
        return 0.0

    timestamp = str(int(time.time() * 1000))
    query_str = f"api_key={api_key}&timestamp={timestamp}"
    
    # تولید امضای استاندارد LBank Futures
    sign = hmac.new(api_secret.encode('utf-8'), query_str.encode('utf-8'), hashlib.sha256).hexdigest()
    
    headers = {
        'api_key': api_key,
        'timestamp': timestamp,
        'signature': sign,
        'Content-Type': 'application/json'
    }

    urls = [
        f"https://lbkperp.lbank.com/cfd/openApi/v1/pub/user/assets?{query_str}&sign={sign}",
        f"https://www.lbank.com/v2/supplement/customer_asset.do?{query_str}&sign={sign}"
    ]

    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200:
                data = res.json()
                # جستجو در خروجی داده‌های LBank
                raw_data = data.get('data') or data.get('result') or []
                if isinstance(raw_data, list):
                    for item in raw_data:
                        curr = item.get('currency') or item.get('asset') or item.get('coinName') or ''
                        if curr.upper() == 'USDT':
                            val = item.get('availableMargin') or item.get('availableBalance') or item.get('free') or item.get('balance')
                            if val is not None:
                                return float(val)
                elif isinstance(raw_data, dict):
                    if 'USDT' in raw_data:
                        return float(raw_data['USDT'].get('free', 0.0) or raw_data['USDT'].get('available', 0.0) or 0.0)
                    val = raw_data.get('availableMargin') or raw_data.get('availableBalance') or raw_data.get('free')
                    if val is not None:
                        return float(val)
        except Exception:
            continue

    return 0.0

def get_dynamic_margin():
    if not (api_key and api_secret):
        return BASE_MARGIN_USD

    free_usdt = get_lbank_futures_balance()

    # در صورتی که پاسخ مستقیم دریافت نشد، از CCXT اسپات تست شود
    if free_usdt == 0.0:
        try:
            bal = exchange.fetch_balance()
            free_usdt = float(bal.get('USDT', {}).get('free', 0.0) or 0.0)
        except Exception:
            pass

    if free_usdt > 0.0:
        margin = max(BASE_MARGIN_USD, free_usdt * RISK_PERCENT)
    else:
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
            print(f"[Order Error] Could not fetch current price for {symbol}")
            return None

        raw_amount = (margin_usd * LEVERAGE) / current_price
        
        try:
            amount = float(exchange.amount_to_precision(symbol, raw_amount))
        except Exception:
            amount = round(raw_amount, 2)

        print(f"[*] Placing {side.upper()} order for {symbol} | Amount: {amount} | Ref Price: {current_price}")
        
        order = exchange.create_order(
            symbol=symbol,
            type='market',
            side=side,
            amount=amount,
            price=current_price
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

    # ستاپ خرید M2B (لانگ)
    if c['close'] > ema and c['open'] >= ema and c['close'] > c['open'] and close_in_upper_third:
        sl = c['low'] - (0.2 * atr)
        risk = c['close'] - sl
        if risk <= 0: return
        tp = c['close'] + (2.0 * risk)

        msg = (
            f"🟢 *سیگنال خرید (LONG)*\n"
            f"نماد: `{symbol}`\n"
            f"قیمت ورود: `{curr['close']}`\n"
            f"مارجین: `{margin}$` | لوریج: `x{LEVERAGE}`\n"
            f"🛑 حد ضرر: `{sl:.4f}`\n"
            f"🎯 حد سود: `{tp:.4f}`"
        )
        print(f"[{time.strftime('%H:%M:%S')}] Signal LONG on {symbol}")
        send_telegram(msg)
        place_order_safe(symbol, 'buy', margin, sl, tp)

    # ستاپ فروش M2S (شورت)
    elif c['close'] < ema and c['open'] <= ema and c['close'] < c['open'] and close_in_lower_third:
        sl = c['high'] + (0.2 * atr)
        risk = sl - c['close']
        if risk <= 0: return
        tp = c['close'] - (2.0 * risk)

        msg = (
            f"🔴 *سیگنال فروش (SHORT)*\n"
            f"نماد: `{symbol}`\n"
            f"قیمت ورود: `{curr['close']}`\n"
            f"مارجین: `{margin}$` | لوریج: `x{LEVERAGE}`\n"
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
        
