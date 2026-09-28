"""تحویل سفارش — منطق مشترک خرید کارتی (با تایید ادمین) و خرید کیف‌پولی (فوری).

- deliver() یک سفارش pending را تحویل می‌دهد و approved می‌کند.
- در صورت شکست (خطای پنل / نبود کانفیگ) سفارش pending می‌ماند و False برمی‌گردد
  تا صداکننده تصمیم بگیرد (ادمین: پاپ‌آپ خطا / کیف پول: برگشت مبلغ).
"""
from __future__ import annotations

import logging

from aiogram import html

import database as db
from database import now
from panels import PanelError, PasarPanel
from texts import T
from utils import (fmt_dt, fmt_left, fmt_price, panel_uname,
                   render_template, sub_email)

log = logging.getLogger("vpnbot.delivery")


async def _reward_referrer(bot, ref_id: int) -> None:
    """هدیه اولین خرید دعوتی: تمدید اشتراک فعال، وگرنه بونوس محفوظ."""
    days = int(db.get_setting("referral_days") or 3)
    if db.get_setting("referral_enabled") != "1" or days <= 0:
        return
    subs = db.active_subscriptions(ref_id)
    if subs:
        db.extend_subscription(subs[-1]["id"], days)
        extra = ""
    else:
        db.add_bonus_days(ref_id, days)
        extra = "\nچون اشتراک فعالی نداری، این هدیه محفوظ ماند و به خرید بعدیت اضافه می‌شود 🎖️"
    try:
        await bot.send_message(ref_id, T("msg_ref_bonus", days=days) + extra)
    except Exception:
        log.warning("cannot notify referrer %d", ref_id)


async def deliver(bot, order_id: int) -> tuple[bool, str]:
    """تحویل سفارش. برمی‌گرداند: (موفق؟, پیام کاربر یا علت شکست)."""
    o = db.get_order(order_id)
    if not o or o["status"] != "pending":
        return False, "سفارش معتبر نیست."
    plan = db.get_plan(o["plan_id"])
    panel = db.get_panel(plan["panel_id"]) if plan and plan["panel_id"] else None
    if panel and not panel["active"]:
        panel = None
    first_buy = not db.has_approved_order(o["user_id"])
    bonus = db.take_bonus_days(o["user_id"])  # هدیه‌های دعوت محفوظ
    total_days = o["plan_days"] + bonus

    # ۱) اگر اشتراک فعال دارد → تمدید همان (+ تمدید در پنل)
    subs = db.active_subscriptions(o["user_id"])
    if subs:
        sub = subs[-1]  # دیرترین انقضا
        db.extend_subscription(sub["id"], total_days)
        s = db.get_subscription(sub["id"])
        if panel and sub["panel_id"] == panel["id"] and sub["panel_username"]:
            try:
                cli = PasarPanel(panel["base_url"], panel["api_key"],
                                 panel["username"], panel["password"])
                await cli.extend_user(sub["panel_username"], s["expires_at"])
            except PanelError as e:
                log.warning("panel extend failed for order %d: %s", o["id"], e)
        db.set_order_status(o["id"], "approved")
        user_msg = (f"✅ پرداختت تایید و اشتراکت <b>تمدید</b> شد!\n\n"
                    f"⏳ انقضای جدید: {fmt_dt(s['expires_at'])}\n"
                    f"⏰ باقی‌مانده: {fmt_left(s['expires_at'], now())}"
                    + (f"\n\n🎖️ {bonus} روز هدیه دعوت هم بهش اضافه شد!" if bonus else ""))
    elif panel:
        # ۲) ساخت خودکار یوزر در پنل پاسارگارد
        uname = panel_uname(o["user_id"], f"o{o['id']}")
        try:
            cli = PasarPanel(panel["base_url"], panel["api_key"],
                             panel["username"], panel["password"])
            gids = [int(x) for x in (panel["group_ids"] or "").split(",") if x.strip().isdigit()]
            resp = await cli.create_user(
                uname, now() + total_days * 86400,
                int((plan["volume_gb"] or 0) * 1024 ** 3),
                note=f"order {o['id']} user {o['user_id']}", group_ids=gids)
        except PanelError as e:
            db.add_bonus_days(o["user_id"], bonus)  # برگرداندن بونوس
            return False, f"❌ خطای پنل: {e}"
        link = cli.absolute_sub_url(resp)
        db.create_subscription(o["user_id"], o["plan_id"], panel["name"], link,
                               total_days, panel_id=panel["id"],
                               panel_username=uname, sub_link=link)
        db.set_order_status(o["id"], "approved")
        user_msg = (f"✅ پرداختت تایید شد! اشتراک فعال شد 🎉\n\n"
                    f"💎 {html.quote(o['plan_title'])}\n"
                    f"🖥️ سرور: {html.quote(panel['name'])}\n"
                    f"⏳ انقضا: {fmt_left(now() + total_days * 86400, now())}"
                    + (f"\n🎖️ شامل {bonus} روز هدیه دعوت!" if bonus else "") + "\n\n"
                    f"🔗 لینک اشتراکت:\n<code>{html.quote(link)}</code>\n\n"
                    "از بخش «📦 اشتراک‌های من» هم می‌توانی QR آن را بگیری 📷")
    else:
        # ۳) دستی: اول از استخر آماده، بعد از قالب سرور
        cfg, server_name = None, ""
        free = db.get_free_config()
        if free:
            db.assign_config(free["id"], o["user_id"])
            cfg, server_name = free["config_text"], free["server_name"]
        else:
            srv = db.template_server()
            if srv:
                cfg = render_template(srv["template"], sub_email(o["user_id"]))
                server_name = srv["name"]
        if not cfg:
            db.add_bonus_days(o["user_id"], bonus)  # برگرداندن بونوس
            return False, "❌ کانفیگ آزادی نیست! اول از «سرورها» کانفیگ اضافه کن."
        db.create_subscription(o["user_id"], o["plan_id"], server_name, cfg, total_days)
        db.set_order_status(o["id"], "approved")
        user_msg = (f"✅ پرداختت تایید شد! اشتراک فعال شد 🎉\n\n"
                    f"💎 {html.quote(o['plan_title'])}\n"
                    f"🖥️ سرور: {html.quote(server_name)}\n"
                    f"⏳ انقضا: {fmt_left(now() + total_days * 86400, now())}"
                    + (f"\n🎖️ شامل {bonus} روز هدیه دعوت!" if bonus else "") + "\n\n"
                    f"📋 کانفیگت:\n<code>{html.quote(cfg[:3800])}</code>")

    # ۴) هدیه دعوت‌کننده در اولین خرید
    if first_buy:
        u = db.get_user(o["user_id"])
        if u and u["referred_by"]:
            await _reward_referrer(bot, u["referred_by"])

    try:
        await bot.send_message(o["user_id"], user_msg)
    except Exception as e:
        log.warning("cannot notify user %d: %s", o["user_id"], e)
    return True, user_msg
