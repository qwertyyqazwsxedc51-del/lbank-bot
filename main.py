import os
import time
import requests
import ccxt
import pandas as pd
import numpy as np

# --- اطلاعات احراز هویت و پارامترها ---
GAPGPTMASKTOKEN8z3ozgzmzr7X0X = os.getenv("3fbd463c-b7a1-403c-955c-34958a3537d8", "")
GAPGPTMASKTOKEN8z3ozgzmzr7X1X = os.getenv("6DEAC5931CAAAAE74956CBCAC10B9FAB", "")
TELEGRAM_TOKEN = os.getenv("8718217424:AAEN461V8g6lEyuCDWeB16-tMkGULfcNRrw", "")
CHAT_ID = os.getenv("1499492919", "")

# جفت‌ارزهای فیوچرز: نیر و طلا
SYMBOLS = ["NEAR/USDT:USDT", "XAUUSD/USDT:USDT"]
LEVERAGE = 10              # لوریج ۱۰
BASE_MARGIN_USD = 2.0      # حداقل مارجین ورود (دلار)
RISK_PERCENT = 0.50        # در صورت رشد موجودی، ۵۰٪ موجودی آزاد را درگیر کن
TIMEFRAME = "15m"

exchange = ccxt.lbank({
    'apiKey': GAPGPTMASKTOKEN8z3ozgzmzr7X2X,
    'secret': GAPGPTMASKTOKEN8z3ozgzmzr7X3X,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'},  # بازار مشتقه و فیوچرز
})

def send_telegram(message: str):
    """ارسال اعلان وضعیت و سیگنال‌ها به تلگرام"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[Telegram] Token or Chat ID not configured.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        res = requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
        if res.status_code != 200:
            print(f"[Telegram Error] {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[Telegram Exception] {e}")

def get_dynamic_margin():
    """محاسبه سرمایه ورودی متناسب با رشد حساب"""
    try:
        balance = exchange.fetch_balance()
        free_usdt = balance['USDT']['free'] if 'USDT' in balance and 'free' in balance['USDT'] else BASE_MARGIN_USD
        margin = max(BASE_MARGIN_USD, free_usdt * RISK_PERCENT)
        print(f"[*] Total Free USDT: {free_usdt:.2f}$ | Allocated Margin: {margin:.2f}$")
        return round(margin, 2)
    except Exception as e:
        print(f"[Balance Warning] {e}")
        return BASE_MARGIN_USD

def has_open_position(symbol: str) -> bool:
    """بررسی اینکه آیا پوزیشن فعالی روی نماد وجود دارد یا خیر"""
    try:
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            # اگر حجم پوزیشن غیر صفر باشد، یعنی معامله باز داریم
            if pos.get('symbol') == symbol and float(pos.get('contracts', 0) or pos.get('size', 0) or 0) > 0:
                print(f"[!] Active position already open for {symbol}. Skipping new entry.")
                return True
        return False
    except Exception as e:
        print(f"[Position Check Info] {e}")
        return False

def place_order_with_brackets(symbol: str, side: str, margin_usd: float, sl_price: float, tp_price: float):
    """
    ثبت اردر ورود مارکت همراه با ثبت حد سود (TP) و حد ضرر (SL) خودکار در صرافی
    """
    try:
        market = exchange.market(symbol)
        exchange.set_leverage(LEVERAGE, market['id'])
        current_price = exchange.fetch_ticker(symbol)['last']
        
        # محاسبه حجم دقیق بر اساس لوریج
        amount = (margin_usd * LEVERAGE) / current_price
        amount = float(exchange.amount_to_precision(symbol, amount))
        sl_price = float(exchange.price_to_precision(symbol, sl_price))
        tp_price = float(exchange.price_to_precision(symbol, tp_price))

        print(f"[*] Placing {side.upper()} on {symbol}: Amount={amount}, SL={sl_price}, TP={tp_price}")
        
        # ۱. ثبت اردر مارکت برای ورود
        entry_order = exchange.create_market_order(symbol, side, amount)
        print(f"[+] Entry Order Filled! ID: {entry_order.get('id', 'N/A')}")
        
        # ۲. ثبت اردرهای محافظتی معکوس (Exit Brackets)
        exit_side = 'sell' if side.lower() == 'buy' else 'buy'
        
        # اردر حد ضرر (Stop Loss)
        try:
            exchange.create_order(
                symbol=symbol,
                type='stop_market',
                side=exit_side,
                amount=amount,
                params={'stopPrice': sl_price, 'reduceOnly': True}
            )
            print(f"[+] Stop-Loss set at {sl_price}")
        except Exception as e:
            print(f"[!] Warning on Setting SL Order: {e}")

        # اردر حد سود (Take Profit)
        try:
            exchange.create_order(
                symbol=symbol,
                type='limit',
                side=exit_side,
                amount=amount,
                price=tp_price,
                params={'reduceOnly': True}
            )
            print(f"[+] Take-Profit set at {tp_price}")
        except Exception as e:
            print(f"[!] Warning on Setting TP Order: {e}")

        return entry_order

    except Exception as e:
        err_msg = f"⚠️ *خطا در ثبت معامله در البانک ({symbol}):*\n`{e}`"
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
    """محاسبه میانگین متحرک ۲۰ و ATR دوره ۱۴"""
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
    c = df.iloc[-2]     # کندل بسته شده معیار تصمیم‌گیری
    curr = df.iloc[-1]  # قیمت لحظه‌ای
    
    ema = c['ema20']
    atr = c['atr']
    rng = c['high'] - c['low']
    body = abs(c['close'] - c['open'])

    if rng == 0:
        return

    # ۱. فیلتر حداقل بدنه کندل (حداقل ۳۵٪ کل دامنه کندل)
    if (body / rng) < 0.35:
        return

    # ۲. قوانین پرایس‌اکشن ال بروکس برای کندل سیگنال معتبر
    close_in_upper_third = (c['close'] - c['low']) >= (0.65 * rng)
    close_in_lower_third = (c['high'] - c['close']) >= (0.65 * rng)

    # --- ستاپ صعودی M2B (Long) ---
    if c['close'] > ema and c['open'] >= ema and c['close'] > c['open'] and close_in_upper_third:
        # حد ضرر: کف کندل منهای بافر ATR
        sl = c['low'] - (0.2 * atr)
        risk = c['close'] - sl
        if risk <= 0:
            return
        # حد سود با نسبت ریسک به ریوارد ۱ به ۲
        tp = c['close'] + (2.0 * risk)

        msg = (
            f"🟢 *سیگنال خرید و پوزیشن باز شد (LONG)*\n"
            f"نماد: `{symbol}`\n"
            f"قیمت ورود: `{curr['close']}`\n"
            f"مارجین اختصاص‌یافته: `{margin}$` (لوریج: `x{LEVERAGE}`)\n"
            f"🛑 حد ضرر (SL): `{sl:.4f}`\n"
            f"🎯 حد سود (TP): `{tp:.4f}` (R:R 1:2)"
        )
        print(f"[{time.strftime('%H:%M:%S')}] Signal LONG on {symbol}")
        send_telegram(msg)
        place_order_with_brackets(symbol, 'buy', margin, sl, tp)

    # --- ستاپ نزولی M2S (Short) ---
    elif c['close'] < ema and c['open'] <= ema and c['close'] < c['open'] and close_in_lower_third:
        # حد ضرر: سقف کندل به‌علاوه بافر ATR
        sl = c['high'] + (0.2 * atr)
        risk = sl - c['close']
        if risk <= 0:
            return
        # حد سود با نسبت ریسک به ریوارد ۱ به ۲
        tp = c['close'] - (2.0 * risk)

        msg = (
            f"🔴 *سیگنال فروش و پوزیشن باز شد (SHORT)*\n"
            f"نماد: `{symbol}`\n"
            f"قیمت ورود: `{curr['close']}`\n"
            f"مارجین اختصاص‌یافته: `{margin}$` (لوریج: `x{LEVERAGE}`)\n"
            f"🛑 حد ضرر (SL): `{sl:.4f}`\n"
            f"🎯 حد سود (TP): `{tp:.4f}` (R:R 1:2)"
        )
        print(f"[{time.strftime('%H:%M:%S')}] Signal SHORT on {symbol}")
        send_telegram(msg)
        place_order_with_brackets(symbol, 'sell', margin, sl, tp)

if __name__ == "__main__":
    for i in range(9):
        margin = get_dynamic_margin()
        for sym in SYMBOLS:
            analyze(sym, margin)
        if i < 8:
            time.sleep(30)
    
