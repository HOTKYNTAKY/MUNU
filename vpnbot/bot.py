#!/usr/bin/env python3
"""نقطه ورود ربات فروش فیلترشکن.

اجرا:  python3 bot.py
در اجرای اول اگر فایل .env نباشد، ویزارد تعاملی توکن و آیدی ادمین را می‌گیرد.
"""
from __future__ import annotations

import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, ErrorEvent, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import backup as backup_mod
import database as db
from config import BASE_DIR, get_config
from handlers import admin, user


def setup_logging() -> None:
    """لاگ هم در کنسول (برای systemd) هم در فایل."""
    os.makedirs(BASE_DIR / "data", exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)
    fh = RotatingFileHandler(BASE_DIR / "data" / "bot.log", maxBytes=2_000_000,
                             backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


class BanMiddleware(BaseMiddleware):
    """جلوگیری از استفاده کاربران مسدود (هم پیام، هم دکمه)."""

    async def __call__(self, handler, event, data):
        from_user = data.get("event_from_user")
        if from_user and db.is_banned(from_user.id):
            if isinstance(event, Message):
                await event.answer("⛔ شما توسط مدیریت مسدود شده‌اید.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ مسدود هستی.", show_alert=True)
            return None
        return await handler(event, data)


async def main() -> None:
    setup_logging()
    log = logging.getLogger("vpnbot")

    cfg = get_config(interactive=True)   # ویزارد اجرای اول (در صورت نیاز)
    db.init_db(cfg.db_path)
    os.makedirs(cfg.backup_dir, exist_ok=True)

    bot = Bot(token=cfg.bot_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # ترتیب مهم است: روتر ادمین اول تا کال‌بک‌های مدیریتی اولویت بگیرند
    dp.include_routers(admin.router, user.router)
    dp.message.middleware(BanMiddleware())
    dp.callback_query.middleware(BanMiddleware())

    @dp.errors()
    async def on_error(event: ErrorEvent) -> None:
        log.exception("update failed: %s", event.exception)

    # جاب‌های روزانه (ساعت تهران)
    scheduler = AsyncIOScheduler(timezone="Asia/Tehran")
    scheduler.add_job(backup_mod.backup_job, "cron", hour=0, minute=0, args=[bot])
    scheduler.add_job(backup_mod.expiry_job, "cron", hour=0, minute=5, args=[bot])
    scheduler.start()

    me = await bot.get_me()
    log.info("bot started as @%s (admin=%d)", me.username, cfg.admin_id)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
