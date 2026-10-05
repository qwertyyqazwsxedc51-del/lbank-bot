import os
import time
import hmac
import hashlib
import requests
import pandas as pd
import ccxt

# تنظیم متغیرها
secret_key = os.getenv("LBANK_API_SECRET")
api_key = os.getenv("LBANK_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOLS = ["NEAR/USDT", "PAXG/USDT"]
TIMEFRAME = "15m"
LEVERAGE = 10
DEFAULT_MARGIN = 2.0

def send_telegram(msg):
    if TELEGRAM_TOKEN and CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        except Exception as e:
            print(f"Telegram error: {e}")

def get_futures_balance():
    """تلاش مجدد برای دریافت موجودی با تغییر در هدرها"""
    if not api_key or not secret_key:
        return 0.0
    
    # تغییر اندپوینت به نسخه عمومی‌تر اگر قبلی دسترسی نداشت
    url = "https://lbkperp.lbank.com/cfd/openApi/v1/pub/account"
    timestamp = str(int(time.time() * 1000))
    
    # ساخت پارامترها - معمولاً در البانک فیوچرز امضا روی کل پارامترها انجام می‌شود
    params_str = f"api_key={api_key}&timestamp={timestamp}"
    sign = hmac.new(secret_key.encode('utf-8'), params_str.encode('utf-8'), hashlib.sha256).hexdigest()
    
    headers = {
        'api_key': api_key,
        'sign': sign,
        'timestamp': timestamp,
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'Mozilla/5.0' # اضافه کردن User-Agent برای عبور از 403
    }
    
    try:
        # استفاده از GET به جای POST اگر اندپوینت فقط اطلاعات می‌خواهد
        res = requests.get(url, params=f"{params_str}&sign={sign}", headers=headers, timeout=10)
        print(f"[RAW Futures Response]: {res.status_code} - {res.text}")
        
        if res.status_code == 200:
            data = res.json()
            if data.get("result") == "true":
                # بسته به ساختار پاسخ البانک، ممکن است مسیر داده متفاوت باشد
                balance_list = data.get("data", {}).get("assets", [])
                for item in balance_list:
                    if item.get("asset") == "USDT":
                        return float(item.get("balance", 0.0))
    except Exception as e:
        print(f"[!] Futures API Error: {e}")
    return 0.0

# ... (بقیه کدهای قبلی را بدون تغییر باقی بگذارید) ...
