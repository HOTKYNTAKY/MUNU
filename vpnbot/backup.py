"""بکاپ خودکار روزانه + ریستور + یادآوری انقضا.

- هر روز ساعت ۰۰:۰۰ (تهران) از دیتابیس بکاپ گرفته و فایلش برای ادمین ارسال می‌شود.
- ریستور: ادمین فایل .db را با دستور /restore برای ربات می‌فرستد.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime

from aiogram import Bot
from aiogram.types import FSInputFile

import database as db
from config import get_config
from utils import fmt_dt

log = logging.getLogger("vpnbot.backup")

REQUIRED_TABLES = {"users", "plans", "subscriptions", "orders", "tickets", "settings"}


def make_backup(db_path: str, backup_dir: str) -> str:
    """بکاپ امن با API خود sqlite (حتی حین اجرا) → مسیر فایل بکاپ."""
    os.makedirs(backup_dir, exist_ok=True)
    name = "backup-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".db"
    dest = os.path.join(backup_dir, name)
    src = sqlite3.connect(db_path, timeout=30)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)  # کپی اتمیک و امن
        finally:
            dst.close()
    finally:
        src.close()
    log.info("backup created: %s", dest)
    return dest


async def send_backup_to_admin(bot: Bot, path: str) -> None:
    """ارسال فایل بکاپ به آیدی ادمین."""
    admin_id = get_config(interactive=False).admin_id
    size_kb = os.path.getsize(path) // 1024
    await bot.send_document(
        admin_id,
        FSInputFile(path),
        caption=f"💾 بکاپ خودکار دیتابیس\n🕐 {fmt_dt(int(time.time()))}\n📦 حجم: {size_kb} KB",
    )


def validate_backup(path: str) -> tuple[bool, str]:
    """بررسی سلامت فایل بکاپ قبل از ریستور."""
    try:
        con = sqlite3.connect(path, timeout=10)
        try:
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            missing = REQUIRED_TABLES - tables
            if missing:
                return False, f"جدول‌های لازم نیست: {', '.join(sorted(missing))}"
            ok = con.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                return False, f"خطای سلامت فایل: {ok}"
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 — هر خطایی یعنی فایل خراب است
        return False, str(e)
    return True, "ok"


def restore_backup(src_path: str, db_path: str) -> None:
    """جایگزینی دیتابیس زنده با فایل بکاپ (بعد از validate).

    چون همه اتصال‌ها کوتاه‌مدت‌اند، نیازی به ریستارت ربات نیست؛
    ولی اول یک بکاپ اضطراری از وضعیت فعلی گرفته می‌شود.
    """
    cfg = get_config(interactive=False)
    try:
        make_backup(db_path, cfg.backup_dir)
    except Exception:
        log.exception("emergency backup before restore failed")
    shutil.copyfile(src_path, db_path)
    log.warning("database restored from %s", src_path)


# ------------------------------------------------------------ جاب‌های روزانه
async def backup_job(bot: Bot) -> None:
    """جاب ساعت ۰۰:۰۰ — بکاپ + ارسال به ادمین."""
    cfg = get_config(interactive=False)
    try:
        path = make_backup(cfg.db_path, cfg.backup_dir)
        await send_backup_to_admin(bot, path)
    except Exception:
        log.exception("daily backup failed")


async def expiry_job(bot: Bot) -> None:
    """یادآوری انقضای ۲۴ ساعت آینده + غیرفعال‌سازی منقضی‌شده‌ها."""
    try:
        for s in db.expiring_soon(24):
            try:
                await bot.send_message(
                    s["user_id"],
                    f"⏳ اشتراکت کمتر از ۲۴ ساعت دیگر تمام می‌شود!\n"
                    f"🖥️ سرور: {s['server_name']}\n"
                    f"از دکمه «🛒 خرید اشتراک» تمدیدش کن.",
                )
            except Exception:
                pass  # کاربر ربات را بلاک کرده؟ رد شو
        for s in db.deactivate_expired():
            try:
                await bot.send_message(
                    s["user_id"],
                    "🔴 اشتراکت تمام شد. برای خرید دوباره /start را بزن.",
                )
            except Exception:
                pass
    except Exception:
        log.exception("expiry job failed")
