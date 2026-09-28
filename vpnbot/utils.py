"""توابع کمکی مشترک: تاریخ، قیمت، ساخت کانفیگ."""
from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")


def fmt_dt(ts: int) -> str:
    """epoch → تاریخ شمسی‌خوانا (میلادی با ساعت تهران)."""
    return datetime.fromtimestamp(ts, TEHRAN).strftime("%Y/%m/%d %H:%M")


def fmt_price(amount: int) -> str:
    """مبلغ به تومان با جداکننده هزارگان."""
    return f"{amount:,} تومان"


def fmt_left(expires_at: int, now_ts: int) -> str:
    """باقی‌مانده اشتراک: «۵ روز و ۳ ساعت»."""
    left = max(0, expires_at - now_ts)
    days, left = divmod(left, 86400)
    hours = left // 3600
    if days:
        return f"{days} روز و {hours} ساعت"
    if hours:
        return f"{hours} ساعت"
    mins = max(1, left // 60)
    return f"{mins} دقیقه"


def fmt_volume(volume_gb: float) -> str:
    return "نامحدود ♾️" if volume_gb <= 0 else f"{volume_gb:g} گیگ"


def new_uuid() -> str:
    return str(uuid.uuid4())


def sub_email(user_id: int) -> str:
    """ایمیل یکتا برای ساخت کانفیگ از روی قالب."""
    return f"u{user_id}-{uuid.uuid4().hex[:6]}"


def render_template(template: str, email: str) -> str:
    """پر کردن قالب کانفیگ سرور با UUID و ایمیل تازه."""
    return template.replace("{UUID}", new_uuid()).replace("{EMAIL}", email)
