import os
import time
import requests
import ccxt
import pandas as pd

# دریافت متغیرهای محیطی از سکرت‌های گیت‌هاب
api_key = os.getenv("3fbd463c-b7a1-403c-955c-34958a3537d8", "")
api_secret = os.getenv("6DEAC5931CAAAAE74956CBCAC10B9FAB", "")
tele_token = os.getenv("8718217424:AAEN461V8g6lEyuCDWeB16-tMkGULfcNRrw", "")
chat_id = os.getenv("1499492919", "")

SYMBOLS = ["NEAR/USDT:USDT", "XAUUSD/USDT:USDT"]
LEVERAGE = 10
BASE_MARGIN_USD = 2.0
RISK_PERCENT = 0.50
TIMEFRAME = "15m"

# اتصال به صرافی البانک (بخش فیوچرز)
exchange = ccxt.lbank({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'},
})

def send_telegram(message: str):
    if not tele_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{tele_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}, timeout=8)
    except Exception as e:
        print(f"[Telegram Error] {e}")

def get_dynamic_margin():
    try:
        balance = exchange.fetch_balance()
        free_usdt = 0.0
        if 'USDT' in balance and 'free' in balance['USDT']:
            free_usdt = float(balance['USDT']['free'] or 0.0)
        
        if free_usdt < BASE_MARGIN_USD:
            print(f"[*] Available Futures USDT: {free_usdt:.2f}$ (Using Base {BASE_MARGIN_USD}$)")
            return BASE_MARGIN_USD
        
        margin = max(BASE_MARGIN_USD, free_usdt * RISK_PERCENT)
        print(f"[*] Available Futures USDT: {free_usdt:.2f}$ | Selected Margin: {margin:.2f}$")
        return round(margin, 2)
    except Exception as e:
        print(f"[Balance Warning] {e}")
        return BASE_MARGIN_USD

def has_open_position(symbol: str) -> bool:
    try:
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            contracts = float(pos.get('contracts') or pos.get('size') or 0.0)
            if pos.get('symbol') == symbol and contracts > 0:
                print(f"[!] Position already open for {symbol}. Skipping.")
                return True
        return False
    except Exception as e:
        return False

def place_order_safe(symbol: str, side: str, margin_usd: float, sl_price: float, tp_price: float):
    try:
        markets = exchange.load_markets()
        if symbol not in markets:
            print(f"[Error] Symbol {symbol} not supported on LBank Swap.")
            return None

        try:
            exchange.set_leverage(LEVERAGE, symbol)
        except Exception:
            pass

        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker['last']

        raw_amount = (margin_usd * LEVERAGE) / current_price
        amount = float(exchange.amount_to_precision(symbol, raw_amount))

        market_info = markets[symbol]
        min_amount = market_info.get('limits', {}).get('amount', {}).get('min', 0.0)
        if min_amount and amount < min_amount:
            err = f"⚠️ حجم محاسبه‌شده ({amount}) کمتر از حداقل سفارش البانک ({min_amount}) است."
            print(err)
            send_telegram(err)
            return None

        print(f"[*] Executing {side.upper()} on {symbol} -> Amount: {amount} at ~{current_price}")
        
        order = exchange.create_market_order(symbol, side, amount)
        print(f"[+] Entry Order Filled! ID: {order.get('id', 'N/A')}")

        exit_side = 'sell' if side.lower() == 'buy' else 'buy'
        try:
            exchange.create_order(
                symbol=symbol,
                type='limit',
                side=exit_side,
                amount=amount,
                price=float(exchange.price_to_precision(symbol, tp_price)),
                params={'reduceOnly': True}
            )
            print(f"[+] TP Order Placed at {tp_price}")
        except Exception as tp_err:
            print(f"[TP Note] {tp_err}")

        return order

    except Exception as e:
        err_msg = f"⚠️ *خطا در اجرای سفارش ({symbol}):*\n`{e}`"
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
    if has_open_position(symbol):
        return

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
        return

    close_in_upper_third = (c['close'] - c['low']) >= (0.65 * rng)
    close_in_lower_third = (c['high'] - c['close']) >= (0.65 * rng)

    # ستاپ خرید M2B
    if c['close'] > ema and c['open'] >= ema and c['close'] > c['open'] and close_in_upper_third:
        sl = c['low'] - (0.2 * atr)
        risk = c['close'] - sl
        if risk <= 0: return
        tp = c['close'] + (2.0 * risk)

        msg = (
            f"🟢 *سیگنال خرید و ثبت سفارش (LONG)*\n"
            f"نماد: `{symbol}`\n"
            f"قیمت: `{curr['close']}`\n"
            f"مارجین: `{margin}$` | لوریج: `x{LEVERAGE}`\n"
            f"🛑 حد ضرر: `{sl:.4f}`\n"
            f"🎯 حد سود: `{tp:.4f}`"
        )
        print(f"[{time.strftime('%H:%M:%S')}] Signal LONG on {symbol}")
        send_telegram(msg)
        place_order_safe(symbol, 'buy', margin, sl, tp)

    # ستاپ فروش M2S
    elif c['close'] < ema and c['open'] <= ema and c['close'] < c['open'] and close_in_lower_third:
        sl = c['high'] + (0.2 * atr)
        risk = sl - c['close']
        if risk <= 0: return
        tp = c['close'] - (2.0 * risk)

        msg = (
            f"🔴 *سیگنال فروش و ثبت سفارش (SHORT)*\n"
            f"نماد: `{symbol}`\n"
            f"قیمت: `{curr['close']}`\n"
            f"مارجین: `{margin}$` | لوریج: `x{LEVERAGE}`\n"
            f"🛑 حد ضرر: `{sl:.4f}`\n"
            f"🎯 حد سود: `{tp:.4f}`"
        )
        print(f"[{time.strftime('%H:%M:%S')}] Signal SHORT on {symbol}")
        send_telegram(msg)
        place_order_safe(symbol, 'sell', margin, sl, tp)

if __name__ == "__main__":
    for i in range(9):
        margin = get_dynamic_margin()
        for sym in SYMBOLS:
            analyze(sym, margin)
        if i < 8:
            time.sleep(30)
            
