"""پنل ادمین: پلن‌ها، کاربران، سفارش‌ها، تیکت‌ها، آمار، پیام همگانی،
تنظیم پرداخت، سرورها/کانفیگ‌ها، بکاپ و ریستور. فقط برای آیدی مالک."""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram import html

import backup as backup_mod
import database as db
import keyboards as kb
from config import get_config, is_admin
from database import now
from panels import PanelError, PasarPanel
import premium
from texts import T, all_keys, label_of, reload as reload_texts
from utils import (fmt_dt, fmt_left, fmt_price, fmt_volume, panel_uname,
                   render_template, sub_email)

log = logging.getLogger("vpnbot.admin")
router = Router()


# ---------------------------------------------------------------- وضعیت‌های گفتگو
class PlanAdd(StatesGroup):
    title = State(); days = State(); volume = State(); price = State()


class PlanEdit(StatesGroup):
    value = State()


class FindUser(StatesGroup):
    query = State()


class AddDays(StatesGroup):
    days = State()


class Broadcast(StatesGroup):
    message = State(); confirm = State()


class PaySet(StatesGroup):
    value = State()


class ServerAdd(StatesGroup):
    name = State(); template = State()


class ConfigAdd(StatesGroup):
    text = State()


class TicketAnswer(StatesGroup):
    text = State()


class Restore(StatesGroup):
    file = State()


async def _admin_ok(ev: Message | CallbackQuery) -> bool:
    """گارد: فقط مالک. در غیر این صورت سکوت/اخطار."""
    if is_admin(ev.from_user.id):
        return True
    if isinstance(ev, Message):
        await ev.answer("⛔")
    else:
        await ev.answer("⛔", show_alert=True)
    return False


def _panel_text() -> tuple[str, object]:
    n_orders = len(db.list_pending_orders())
    n_tickets = db.count_open_tickets()
    return (f"👑 <b>پنل مدیریت</b>\n\n🧾 سفارش در انتظار: {n_orders}\n🎫 تیکت باز: {n_tickets}",
            kb.admin_menu(n_orders, n_tickets))


# ---------------------------------------------------------------- ورود و آمار
@router.message(Command("admin"))
async def cmd_admin(m: Message) -> None:
    if not await _admin_ok(m):
        return
    txt, markup = _panel_text()
    await m.answer(txt, reply_markup=markup)


@router.callback_query(F.data == "adm")
async def cb_adm(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    txt, markup = _panel_text()
    await c.message.edit_text(txt, reply_markup=markup)
    await c.answer()


@router.message(Command("stats"))
async def cmd_stats(m: Message) -> None:
    if not await _admin_ok(m):
        return
    await m.answer(_stats_text(), reply_markup=kb.back_admin())


@router.callback_query(F.data == "adm:stats")
async def cb_stats(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    await c.message.edit_text(_stats_text(), reply_markup=kb.back_admin())
    await c.answer()


def _stats_text() -> str:
    month_ago = now() - 30 * 86400
    return (
        "📊 <b>آمار ربات</b>\n\n"
        f"👥 کاربران: {db.count_users()}\n"
        f"📦 اشتراک‌های فعال: {db.count_active_subs()}\n"
        f"💎 پلن‌ها: {len(db.list_plans())}\n"
        f"🧾 سفارش در انتظار: {len(db.list_pending_orders())}\n"
        f"🎫 تیکت باز: {db.count_open_tickets()}\n"
        f"💰 فروش کل: {fmt_price(db.revenue_total())}\n"
        f"💰 فروش ۳۰ روز: {fmt_price(db.revenue_total(month_ago))}"
    )


# ---------------------------------------------------------------- سفارش‌ها
@router.callback_query(F.data == "adm:orders")
async def cb_orders(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    orders = db.list_pending_orders()
    if not orders:
        await c.message.edit_text("🧾 سفارش در انتظاری نیست. 🎉", reply_markup=kb.back_admin())
    else:
        await c.message.edit_text("🧾 <b>سفارش‌های در انتظار:</b>",
                                  reply_markup=kb.admin_orders(orders))
    await c.answer()


@router.callback_query(F.data.startswith("ord:view:"))
async def cb_order_view(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    o = db.get_order(int(c.data.split(":")[2]))
    if not o:
        await c.answer("یافت نشد.", show_alert=True)
        return
    if o["receipt_file_id"]:
        await c.message.answer_photo(o["receipt_file_id"],
                                     caption=f"🧾 رسید سفارش #{o['id']}")
    elif o["receipt_text"]:
        await c.message.answer(f"🧾 رسید سفارش #{o['id']}:\n{html.quote(o['receipt_text'])}")
    else:
        await c.answer("رسیدی ثبت نشده.", show_alert=True)
        return
    await c.answer()


@router.callback_query(F.data.startswith("ord:"))
async def cb_order_detail(c: CallbackQuery) -> None:
    """نمایش سفارش (ord:{id}) — تایید/رد جدا هندل می‌شوند."""
    if not await _admin_ok(c):
        return
    parts = c.data.split(":")
    if parts[1] in ("ok", "no", "view"):
        return  # هندلرهای مخصوص خودشان
    o = db.get_order(int(parts[1]))
    if not o:
        await c.answer("یافت نشد.", show_alert=True)
        return
    await c.message.edit_text(
        f"🧾 <b>سفارش #{o['id']}</b> — {o['status']}\n\n"
        f"👤 {html.quote(o['full_name'] or '')} (@{html.quote(o['username'] or '-')}) <code>{o['user_id']}</code>\n"
        f"💎 {html.quote(o['plan_title'])} — {fmt_price(o['amount'])}"
        + (f"\n🎟️ کد: <code>{html.quote(o['code'])}</code>" if o["code"] else "") + "\n"
        f"🕐 {fmt_dt(o['created_at'])}",
        reply_markup=kb.order_decide(o["id"]),
    )
    await c.answer()


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


@router.callback_query(F.data.startswith("ord:ok:"))
async def cb_order_ok(c: CallbackQuery) -> None:
    """تایید سفارش: تمدید یا ساخت تازه + تحویل دستی/پنلی + هدیه دعوت."""
    if not await _admin_ok(c):
        return
    o = db.get_order(int(c.data.split(":")[2]))
    if not o or o["status"] != "pending":
        await c.answer("این سفارش قبلاً تعیین‌تکلیف شده.", show_alert=True)
        return
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
            await c.answer(f"❌ خطای پنل: {e}", show_alert=True)
            return
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
            await c.answer("❌ کانفیگ آزادی نیست! اول از «سرورها» کانفیگ اضافه کن.",
                           show_alert=True)
            return
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
            await _reward_referrer(c.bot, u["referred_by"])

    try:
        await c.bot.send_message(o["user_id"], user_msg)
    except Exception:
        log.warning("cannot notify user %d", o["user_id"])
    try:
        if c.message.photo:  # نوتیف رسید عکس‌دار است → کپشن ویرایش می‌شود
            await c.message.edit_caption(caption=f"✅ سفارش #{o['id']} تایید و تحویل داده شد.",
                                         reply_markup=kb.back_admin())
        else:
            await c.message.edit_text(f"✅ سفارش #{o['id']} تایید و تحویل داده شد.",
                                      reply_markup=kb.back_admin())
    except Exception:
        await c.message.answer(f"✅ سفارش #{o['id']} تایید و تحویل داده شد.",
                               reply_markup=kb.back_admin())
    await c.answer("تایید شد ✅")


@router.callback_query(F.data.startswith("ord:no:"))
async def cb_order_no(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    o = db.get_order(int(c.data.split(":")[2]))
    if not o or o["status"] != "pending":
        await c.answer("قبلاً تعیین‌تکلیف شده.", show_alert=True)
        return
    db.set_order_status(o["id"], "rejected")
    try:
        await c.bot.send_message(o["user_id"],
                                 f"❌ سفارش #{o['id']} ({html.quote(o['plan_title'])}) رد شد.\n"
                                 "اگر واریز کرده‌ای، با پشتیبانی در تماس باش.")
    except Exception as e:
        log.warning("cannot notify user %d (order %d rejected): %s", o["user_id"], o["id"], e)
    try:
        if c.message.photo:
            await c.message.edit_caption(caption=f"❌ سفارش #{o['id']} رد شد.",
                                         reply_markup=kb.back_admin())
        else:
            await c.message.edit_text(f"❌ سفارش #{o['id']} رد شد.", reply_markup=kb.back_admin())
    except Exception:
        await c.message.answer(f"❌ سفارش #{o['id']} رد شد.", reply_markup=kb.back_admin())
    await c.answer()


# ---------------------------------------------------------------- پلن‌ها
@router.callback_query(F.data == "adm:plans")
async def cb_plans(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    await c.message.edit_text("💎 <b>مدیریت پلن‌ها:</b>",
                              reply_markup=kb.admin_plans(db.list_plans()))
    await c.answer()


@router.callback_query(F.data == "pl:add")
async def cb_plan_add(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    await state.set_state(PlanAdd.title)
    await c.message.edit_text("➕ <b>پلن جدید</b>\n\n۱️⃣ عنوان پلن؟ (مثلا: ماهانه ۳۰ گیگ)",
                              reply_markup=kb.cancel_state())
    await c.answer()


@router.message(PlanAdd.title, F.text)
async def st_plan_title(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    await state.update_data(title=m.text.strip()[:60])
    await state.set_state(PlanAdd.days)
    await m.answer("۲️⃣ مدت به روز؟ (عدد، مثلا 30)")


@router.message(PlanAdd.days, F.text)
async def st_plan_days(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    if not m.text.strip().isdigit() or int(m.text) <= 0:
        await m.answer("فقط عدد مثبت:")
        return
    await state.update_data(days=int(m.text))
    await state.set_state(PlanAdd.volume)
    await m.answer("۳️⃣ حجم به گیگ؟ (عدد، ۰ = نامحدود)")


@router.message(PlanAdd.volume, F.text)
async def st_plan_volume(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    try:
        vol = float(m.text.strip().replace("٫", "."))
        assert vol >= 0
    except (ValueError, AssertionError):
        await m.answer("عدد معتبر (۰ = نامحدود):")
        return
    await state.update_data(volume=vol)
    await state.set_state(PlanAdd.price)
    await m.answer("۴️⃣ قیمت به تومان؟ (عدد)")


@router.message(PlanAdd.price, F.text)
async def st_plan_price(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    num = m.text.strip().replace(",", "").replace("٬", "")
    if not num.isdigit():
        await m.answer("فقط عدد:")
        return
    d = await state.get_data()
    pid = db.add_plan(d["title"], d["days"], d["volume"], int(num))
    await state.clear()
    await m.answer(f"✅ پلن «{html.quote(d['title'])}» ساخته شد (#{pid}).",
                   reply_markup=kb.admin_plans(db.list_plans()))


@router.callback_query(F.data.startswith("pl:"))
async def cb_plan_router(c: CallbackQuery, state: FSMContext) -> None:
    """جزئیات/تاگل/حذف/ویرایش پلن."""
    if not await _admin_ok(c):
        return
    if c.data == "pl:add":
        return  # هندلر خودش
    parts = c.data.split(":")
    action = parts[1]
    if action == "ef":  # شروع ویرایش یک فیلد
        pid, field = int(parts[2]), parts[3]
        names = {"title": "عنوان", "days": "مدت (روز)", "volume_gb": "حجم (گیگ)",
                 "price": "قیمت (تومان)"}
        await state.set_state(PlanEdit.value)
        await state.update_data(plan_id=pid, field=field)
        await c.message.edit_text(f"✏️ مقدار جدید «{names[field]}»؟",
                                  reply_markup=kb.cancel_state())
        await c.answer()
        return
    if action == "edit":
        await c.message.edit_text("✏️ کدام فیلد؟",
                                  reply_markup=kb.plan_edit_fields(int(parts[2])))
        await c.answer()
        return
    if action == "panel":
        p = db.get_plan(int(parts[2]))
        if not p:
            await c.answer("یافت نشد.", show_alert=True)
            return
        await c.message.edit_text("🛡️ تحویل خودکار این پلن از کدام پنل انجام شود؟",
                                  reply_markup=kb.plan_panel_select(
                                      p["id"], db.list_panels(), p["panel_id"] or 0))
        await c.answer()
        return
    if action == "pset":
        db.update_plan(int(parts[2]), panel_id=int(parts[3]))
        p = db.get_plan(int(parts[2]))
        pn = db.get_panel(p["panel_id"]) if p["panel_id"] else None
        await c.message.edit_text(
            f"💎 <b>{html.quote(p['title'])}</b>\n⏱️ {p['days']} روز | 📊 {fmt_volume(p['volume_gb'])} | "
            f"💰 {fmt_price(p['price'])}\n{'✅ فعال' if p['active'] else '🚫 غیرفعال'}"
            f"\n🛡️ تحویل: {html.quote(pn['name']) if pn else '🤝 دستی'}",
            reply_markup=kb.admin_plan_detail(p))
        await c.answer("ذخیره شد ✅")
        return
    p = None
    if action in ("tgl", "del"):
        pid = int(parts[2])
        if action == "del":
            db.delete_plan(pid)
            await c.message.edit_text("🗑️ پلن حذف شد.", reply_markup=kb.admin_plans(db.list_plans()))
            await c.answer()
            return
        p = db.get_plan(pid)
        db.update_plan(pid, active=0 if p["active"] else 1)
        p = db.get_plan(pid)
    else:
        p = db.get_plan(int(parts[1]))
    if not p:
        await c.answer("یافت نشد.", show_alert=True)
        return
    pn = db.get_panel(p["panel_id"]) if p["panel_id"] else None
    await c.message.edit_text(
        f"💎 <b>{html.quote(p['title'])}</b>\n⏱️ {p['days']} روز | 📊 {fmt_volume(p['volume_gb'])} | "
        f"💰 {fmt_price(p['price'])}\n{'✅ فعال' if p['active'] else '🚫 غیرفعال'}"
        f"\n🛡️ تحویل: {html.quote(pn['name']) if pn else '🤝 دستی'}",
        reply_markup=kb.admin_plan_detail(p))
    await c.answer()


@router.message(PlanEdit.value, F.text)
async def st_plan_edit_value(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    d = await state.get_data()
    field, val = d["field"], m.text.strip()
    try:
        if field == "title":
            new = val[:60]
        elif field in ("days", "price"):
            new = int(val.replace(",", "").replace("٬", ""))
            assert new > 0
        else:  # volume_gb
            new = float(val.replace("٫", "."))
            assert new >= 0
    except (ValueError, AssertionError):
        await m.answer("مقدار نامعتبر، دوباره:")
        return
    db.update_plan(d["plan_id"], **{field: new})
    await state.clear()
    p = db.get_plan(d["plan_id"])
    await m.answer("✅ ذخیره شد.", reply_markup=kb.admin_plan_detail(p))


# ---------------------------------------------------------------- کاربران
@router.callback_query(F.data == "adm:users")
async def cb_users(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    users = db.list_users()
    await c.message.edit_text(f"👥 <b>کاربران</b> (کل: {db.count_users()} — ۱۵ تای آخر):",
                              reply_markup=kb.admin_users(users))
    await c.answer()


@router.callback_query(F.data == "usr:find")
async def cb_user_find(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    await state.set_state(FindUser.query)
    await c.message.edit_text("🔎 آیدی عددی یا @یوزرنیم کاربر؟", reply_markup=kb.cancel_state())
    await c.answer()


@router.message(FindUser.query, F.text)
async def st_user_find(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    q = m.text.strip()
    u = db.get_user(int(q)) if q.isdigit() else db.find_user_by_name(q)
    await state.clear()
    if not u:
        await m.answer("❌ کاربر پیدا نشد.", reply_markup=kb.back_admin())
        return
    await m.answer(_user_text(u), reply_markup=kb.admin_user_detail(u))


def _user_text(u: dict) -> str:
    subs = db.active_subscriptions(u["id"])
    sub_lines = [f"• {(s['plan_title'] or '')} تا {fmt_dt(s['expires_at'])}" for s in subs] or ["—"]
    return (
        f"👤 <b>{html.quote(u['full_name'] or '-')}</b> (@{html.quote(u['username'] or '-')})\n"
        f"🆔 <code>{u['id']}</code>\n"
        f"{'🚫 مسدود' if u['banned'] else '✅ عادی'}\n"
        f"🕐 عضویت: {fmt_dt(u['created_at'])}\n"
        f"🎁 تست: {'گرفته ✅' if u['trial_used'] else 'نگرفته'} | "
        f"🎖️ بونوس محفوظ: {u['bonus_days']} روز | 👥 دعوتی‌ها: {db.count_referrals(u['id'])}\n"
        f"📦 اشتراک‌های فعال:\n" + "\n".join(sub_lines)
    )


@router.callback_query(F.data.startswith("usr:"))
async def cb_user_router(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    if c.data == "usr:find":
        return
    parts = c.data.split(":")
    action = parts[1]
    if action == "days":
        await state.set_state(AddDays.days)
        await state.update_data(user_id=int(parts[2]))
        await c.message.edit_text("➕ چند روز اضافه شود؟ (به همه اشتراک‌های فعال)",
                                  reply_markup=kb.cancel_state())
        await c.answer()
        return
    if action == "ban":
        u = db.get_user(int(parts[2]))
        if u and u["id"] == c.from_user.id:
            await c.answer("خودت را نمی‌توانی مسدود کنی! 😅", show_alert=True)
            return
        db.set_banned(u["id"], not u["banned"])
        u = db.get_user(u["id"])
        await c.message.edit_text(_user_text(u), reply_markup=kb.admin_user_detail(u))
        await c.answer("انجام شد ✅")
        return
    u = db.get_user(int(parts[1]))
    if not u:
        await c.answer("یافت نشد.", show_alert=True)
        return
    await c.message.edit_text(_user_text(u), reply_markup=kb.admin_user_detail(u))
    await c.answer()


@router.message(AddDays.days, F.text)
async def st_add_days(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    if not m.text.strip().isdigit() or int(m.text) <= 0:
        await m.answer("فقط عدد مثبت:")
        return
    d = await state.get_data()
    subs = db.active_subscriptions(d["user_id"])
    for s in subs:
        db.extend_subscription(s["id"], int(m.text))
    await state.clear()
    await m.answer(f"✅ {m.text} روز به {len(subs)} اشتراک اضافه شد.",
                   reply_markup=kb.back_admin())


# ---------------------------------------------------------------- تیکت‌ها
@router.callback_query(F.data == "adm:tickets")
async def cb_tickets(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    ts = db.list_open_tickets()
    if not ts:
        await c.message.edit_text("🎫 تیکت بازی نیست. 🎉", reply_markup=kb.back_admin())
    else:
        await c.message.edit_text("🎫 <b>تیکت‌های باز:</b>", reply_markup=kb.admin_tickets(ts))
    await c.answer()


@router.callback_query(F.data.startswith("tk:adm:"))
async def cb_ticket_view(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    t = db.get_ticket(int(c.data.split(":")[2]))
    if not t:
        await c.answer("یافت نشد.", show_alert=True)
        return
    await c.message.edit_text(
        f"🎫 <b>تیکت #{t['id']}</b>\n👤 {html.quote(t['full_name'] or '')} "
        f"(@{html.quote(t['username'] or '-')}) <code>{t['user_id']}</code>\n"
        f"🕐 {fmt_dt(t['created_at'])}\n\n📝 {html.quote(t['text'])}",
        reply_markup=kb.admin_ticket_detail(t["id"]))
    await c.answer()


@router.callback_query(F.data.startswith("tk:ans:"))
async def cb_ticket_ans(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    await state.set_state(TicketAnswer.text)
    await state.update_data(ticket_id=int(c.data.split(":")[2]))
    await c.message.edit_text("✍️ پاسخت را بنویس:", reply_markup=kb.cancel_state())
    await c.answer()


@router.message(TicketAnswer.text, F.text)
async def st_ticket_answer(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    d = await state.get_data()
    t = db.get_ticket(d["ticket_id"])
    if not t:
        await state.clear()
        await m.answer("تیکت پیدا نشد.", reply_markup=kb.back_admin())
        return
    db.answer_ticket(t["id"], m.text.strip())
    await state.clear()
    try:
        await m.bot.send_message(t["user_id"],
                                 f"💬 <b>پاسخ تیکت #{t['id']}:</b>\n{html.quote(m.text.strip())}")
        await m.answer("✅ پاسخ ارسال شد.", reply_markup=kb.back_admin())
    except Exception:
        await m.answer("⚠️ ذخیره شد ولی ارسال به کاربر ناموفق بود.", reply_markup=kb.back_admin())


@router.callback_query(F.data.startswith("tk:cls:"))
async def cb_ticket_close(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    db.close_ticket(int(c.data.split(":")[2]))
    await c.message.edit_text("🔒 تیکت بسته شد.", reply_markup=kb.back_admin())
    await c.answer()


# ---------------------------------------------------------------- پیام همگانی
@router.callback_query(F.data == "adm:bc")
async def cb_broadcast(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    await state.set_state(Broadcast.message)
    await c.message.edit_text("📣 پیامت را بفرست (متن، عکس، ویدیو... هر چیزی):",
                              reply_markup=kb.cancel_state())
    await c.answer()


@router.message(Broadcast.message)
async def st_broadcast_msg(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    await state.update_data(chat_id=m.chat.id, message_id=m.message_id)
    await state.set_state(Broadcast.confirm)
    await m.answer(f"👥 ارسال به {len(db.broadcast_targets())} کاربر؟",
                   reply_markup=kb.broadcast_confirm())


@router.callback_query(F.data == "bc:yes")
async def cb_broadcast_yes(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    d = await state.get_data()
    await state.clear()
    if not d:
        await c.answer("منقضی شد؛ دوباره.", show_alert=True)
        return
    await c.message.edit_text("📣 در حال ارسال...")
    ok, fail = 0, 0
    for uid in db.broadcast_targets():
        try:
            await c.bot.copy_message(uid, d["chat_id"], d["message_id"])
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)  # ضد محدودیت تلگرام
    await c.message.edit_text(f"📣 تمام شد.\n✅ موفق: {ok}\n❌ ناموفق: {fail}",
                              reply_markup=kb.back_admin())
    await c.answer()


# ---------------------------------------------------------------- تنظیمات پرداخت
@router.callback_query(F.data == "adm:pay")
async def cb_pay(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    await c.message.edit_text(
        f"💳 <b>تنظیمات پرداخت دستی</b>\n\n💳 کارت: <code>{html.quote(db.get_setting('card_number') or '-')}</code>\n"
        f"👤 صاحب کارت: {html.quote(db.get_setting('card_holder') or '-')}",
        reply_markup=kb.pay_settings())
    await c.answer()


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay_set(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    field = "card_number" if c.data == "pay:card" else "card_holder"
    await state.set_state(PaySet.value)
    await state.update_data(field=field)
    await c.message.edit_text("شماره کارت (۱۶ رقم):" if field == "card_number" else "نام صاحب کارت:",
                              reply_markup=kb.cancel_state())
    await c.answer()


@router.message(PaySet.value, F.text)
async def st_pay_value(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    d = await state.get_data()
    val = m.text.strip().replace(" ", "").replace("-", "")
    if d["field"] == "card_number" and (not val.isdigit() or len(val) != 16):
        await m.answer("شماره کارت باید ۱۶ رقم باشد:")
        return
    db.set_setting(d["field"], m.text.strip())
    await state.clear()
    await m.answer("✅ ذخیره شد.", reply_markup=kb.back_admin())


# ---------------------------------------------------------------- سرورها و کانفیگ‌ها
@router.callback_query(F.data == "adm:srv")
async def cb_servers(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    await c.message.edit_text("🖥️ <b>سرورها و کانفیگ‌ها:</b>\n(عدد داخل پرانتز = کانفیگ آماده آزاد)",
                              reply_markup=kb.admin_servers(db.list_servers()))
    await c.answer()


@router.callback_query(F.data == "srv:add")
async def cb_server_add(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    await state.set_state(ServerAdd.name)
    await c.message.edit_text("➕ <b>سرور جدید</b>\n\n۱️⃣ نام سرور؟ (مثلا: آلمان 🇩🇪)",
                              reply_markup=kb.cancel_state())
    await c.answer()


@router.message(ServerAdd.name, F.text)
async def st_server_name(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    await state.update_data(name=m.text.strip()[:60])
    await state.set_state(ServerAdd.template)
    await m.answer("۲️⃣ قالب ساخت خودکار کانفیگ؟\n"
                   "اگر داری بفرست (با <code>{UUID}</code> و <code>{EMAIL}</code>)،\n"
                   "وگرنه بنویس <code>-</code> تا فقط از کانفیگ‌های آماده استفاده شود:")


@router.message(ServerAdd.template, F.text)
async def st_server_template(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    d = await state.get_data()
    tpl = "" if m.text.strip() == "-" else m.text.strip()
    sid = db.add_server(d["name"], tpl)
    await state.clear()
    await m.answer(f"✅ سرور «{html.quote(d['name'])}» ساخته شد (#{sid}).",
                   reply_markup=kb.admin_servers(db.list_servers()))


@router.callback_query(F.data.startswith("srv:"))
async def cb_server_router(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    if c.data == "srv:add":
        return
    parts = c.data.split(":")
    action = parts[1]
    if action in ("tgl", "del"):
        sid = int(parts[2])
        if action == "del":
            db.delete_server(sid)
            await c.message.edit_text("🗑️ سرور و کانفیگ‌هایش حذف شدند.",
                                      reply_markup=kb.admin_servers(db.list_servers()))
        else:
            s = db.get_server(sid)
            db.update_server(sid, active=0 if s["active"] else 1)
            s = db.get_server(sid)
            await c.message.edit_text(f"🖥️ <b>{html.quote(s['name'])}</b>\n"
                                      f"{'✅ فعال' if s['active'] else '🚫 غیرفعال'}",
                                      reply_markup=kb.admin_server_detail(s))
        await c.answer()
        return
    s = db.get_server(int(parts[1]))
    if not s:
        await c.answer("یافت نشد.", show_alert=True)
        return
    await c.message.edit_text(f"🖥️ <b>{html.quote(s['name'])}</b>\n"
                              f"{'✅ فعال' if s['active'] else '🚫 غیرفعال'}\n"
                              f"📝 قالب خودکار: {'دارد' if s['template'] else 'ندارد'}",
                              reply_markup=kb.admin_server_detail(s))
    await c.answer()


@router.callback_query(F.data.startswith("cfg:add:"))
async def cb_config_add(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    await state.set_state(ConfigAdd.text)
    await state.update_data(server_id=int(c.data.split(":")[2]))
    await c.message.edit_text("📋 متن کامل کانفیگ آماده را بفرست (vmess://... / vless://...):",
                              reply_markup=kb.cancel_state())
    await c.answer()


@router.message(ConfigAdd.text, F.text)
async def st_config_text(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    if len(m.text.strip()) < 20:
        await m.answer("کانفیگ کوتاه است؛ کاملش را بفرست:")
        return
    d = await state.get_data()
    db.add_config(d["server_id"], m.text.strip())
    await state.clear()
    await m.answer("✅ کانفیگ به استخر اضافه شد.", reply_markup=kb.back_admin())


# ---------------------------------------------------------------- بکاپ و ریستور
@router.message(Command("backup"))
async def cmd_backup(m: Message) -> None:
    if not await _admin_ok(m):
        return
    await m.answer("💾 در حال تهیه بکاپ...")
    try:
        from config import get_config as _cfg
        cfg = _cfg(interactive=False)
        path = backup_mod.make_backup(cfg.db_path, cfg.backup_dir)
        await backup_mod.send_backup_to_admin(m.bot, path)
        await m.answer("✅ بکاپ ارسال شد.")
    except Exception as e:
        log.exception("manual backup failed")
        await m.answer(f"❌ خطا: {e}")


@router.callback_query(F.data == "adm:backup")
async def cb_backup(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    await c.message.edit_text("💾 در حال تهیه بکاپ...")
    try:
        from config import get_config as _cfg
        cfg = _cfg(interactive=False)
        path = backup_mod.make_backup(cfg.db_path, cfg.backup_dir)
        await backup_mod.send_backup_to_admin(c.bot, path)
        await c.message.edit_text("✅ بکاپ ارسال شد.", reply_markup=kb.back_admin())
    except Exception as e:
        log.exception("manual backup failed")
        await c.message.edit_text(f"❌ خطا: {e}", reply_markup=kb.back_admin())
    await c.answer()


@router.message(Command("restore"))
async def cmd_restore(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    await state.set_state(Restore.file)
    await m.answer("♻️ فایل بکاپ (.db) را همین‌جا ارسال کن:", reply_markup=kb.cancel_state())


@router.callback_query(F.data == "adm:restore")
async def cb_restore(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    await state.set_state(Restore.file)
    await c.message.edit_text("♻️ فایل بکاپ (.db) را همین‌جا ارسال کن:",
                              reply_markup=kb.cancel_state())
    await c.answer()


@router.message(Restore.file, F.document)
async def msg_restore_file(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    if not (m.document.file_name or "").endswith(".db"):
        await m.answer("فقط فایل با پسوند .db قبول است:")
        return
    await m.answer("⏳ در حال بررسی و ریستور...")
    tmp = os.path.join(tempfile.gettempdir(), f"restore-{m.document.file_id[-12:]}.db")
    try:
        await m.bot.download(m.document.file_id, destination=tmp)
        ok, why = backup_mod.validate_backup(tmp)
        if not ok:
            await m.answer(f"❌ فایل معتبر نیست:\n{html.quote(why)}", reply_markup=kb.back_admin())
            return
        from config import get_config as _cfg
        backup_mod.restore_backup(tmp, _cfg(interactive=False).db_path)
        await state.clear()
        await m.answer("✅ ریستور انجام شد! (از دیتابیس قبلی هم یک بکاپ اضطراری گرفته شد)",
                       reply_markup=kb.back_admin())
    except Exception as e:
        log.exception("restore failed")
        await m.answer(f"❌ خطا در ریستور: {e}", reply_markup=kb.back_admin())
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------- متن‌ها و دکمه‌ها
class TextEdit(StatesGroup):
    value = State()


@router.callback_query(F.data == "adm:texts")
async def cb_texts(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    await c.message.edit_text("✏️ <b>ویرایش متن‌ها</b>\nکدام دسته؟\n\n💡 در متن‌ها می‌توانی از <code>{e:name}</code> برای ایموجی پریمیوم استفاده کنی.",
                              reply_markup=kb.texts_cats())
    await c.answer()


@router.callback_query(F.data.startswith("txtc:"))
async def cb_texts_cat(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    prefix = "btn_" if c.data == "txtc:btn" else "msg_"
    keys = [k for k in all_keys() if k.startswith(prefix)]
    await c.message.edit_text("✏️ یکی را انتخاب کن:", reply_markup=kb.texts_list(
        keys, {k: label_of(k) for k in keys}))
    await c.answer()


@router.callback_query(F.data.startswith("txt:"))
async def cb_text_edit(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    key = c.data.split(":")[1]
    if key not in all_keys():
        await c.answer("یافت نشد.", show_alert=True)
        return
    await state.set_state(TextEdit.value)
    await state.update_data(key=key)
    cur = db.get_text(key) or T(key)
    await c.message.edit_text(
        f"✏️ <b>{label_of(key)}</b> — <code>{key}</code>\n\nمتن فعلی:\n{html.quote(cur)}\n\n"
        "متن جدید را بفرست (placeholderهایی مثل {name} را نگه دار):",
        reply_markup=kb.cancel_state())
    await c.answer()


@router.message(TextEdit.value, F.text)
async def st_text_value(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    if len(m.text) > 2000:
        await m.answer("خیلی طولانی است (حداکثر ۲۰۰۰ کاراکتر):")
        return
    d = await state.get_data()
    db.set_text(d["key"], m.text.strip())
    reload_texts()
    await state.clear()
    await m.answer(f"✅ «{label_of(d['key'])}» ذخیره شد.", reply_markup=kb.back_admin())


# ---------------------------------------------------------------- دکمه‌های شیشه‌ای
class MBtnAdd(StatesGroup):
    text = State(); url = State()


@router.callback_query(F.data == "adm:mbtn")
async def cb_mbtn(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    await c.message.edit_text("🔗 <b>دکمه‌های شیشه‌ای منوی اصلی</b>\n(لینک‌دار: کانال، پشتیبانی، سایت...)",
                              reply_markup=kb.menu_buttons_list(db.list_menu_buttons()))
    await c.answer()


@router.callback_query(F.data == "mbtn:add")
async def cb_mbtn_add(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    await state.set_state(MBtnAdd.text)
    await c.message.edit_text("۱️⃣ متن دکمه؟", reply_markup=kb.cancel_state())
    await c.answer()


@router.message(MBtnAdd.text, F.text)
async def st_mbtn_text(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    await state.update_data(text=m.text.strip()[:60])
    await state.set_state(MBtnAdd.url)
    await m.answer("۲️⃣ لینک دکمه؟ (https://... یا tg://...)")


@router.message(MBtnAdd.url, F.text)
async def st_mbtn_url(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    url = m.text.strip()
    if not url.startswith(("http://", "https://", "tg://")):
        await m.answer("لینک معتبر نیست (با http یا tg شروع شود):")
        return
    d = await state.get_data()
    db.add_menu_button(d["text"], url)
    await state.clear()
    await m.answer("✅ دکمه اضافه شد.", reply_markup=kb.menu_buttons_list(db.list_menu_buttons()))


@router.callback_query(F.data.startswith("mbtn:"))
async def cb_mbtn_router(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    if c.data == "mbtn:add":
        return
    parts = c.data.split(":")
    if parts[1] in ("tgl", "del"):
        bid = int(parts[2])
        if parts[1] == "del":
            db.delete_menu_button(bid)
            await c.message.edit_text("🗑️ حذف شد.", reply_markup=kb.menu_buttons_list(db.list_menu_buttons()))
        else:
            db.toggle_menu_button(bid)
            b = db.get_menu_button(bid)
            await c.message.edit_text(f"🔗 <b>{html.quote(b['text'])}</b>\n{html.quote(b['url'])}\n"
                                      f"{'✅ فعال' if b['active'] else '🚫 غیرفعال'}",
                                      reply_markup=kb.menu_button_detail(bid))
        await c.answer()
        return
    b = db.get_menu_button(int(parts[1]))
    if not b:
        await c.answer("یافت نشد.", show_alert=True)
        return
    await c.message.edit_text(f"🔗 <b>{html.quote(b['text'])}</b>\n{html.quote(b['url'])}\n"
                              f"{'✅ فعال' if b['active'] else '🚫 غیرفعال'}",
                              reply_markup=kb.menu_button_detail(b["id"]))
    await c.answer()


# ---------------------------------------------------------------- ایموجی پریمیوم
class EmoAdd(StatesGroup):
    emoji = State(); name = State()


@router.callback_query(F.data == "adm:emoji")
async def cb_emoji(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    es = db.list_emoji()
    await c.message.edit_text(
        "✨ <b>ایموجی‌های پریمیوم</b>\n"
        f"ثبت‌شده: {len(es)}\n\nبا «افزودن»، اول یک پیام حاوی ایموجی پریمیوم بفرست/فوروارد کن، بعد یک نام کوتاه بده.\n"
        "بعد در متن‌ها با <code>{e:نام}</code> استفاده‌اش کن.",
        reply_markup=kb.emoji_list(es))
    await c.answer()


@router.callback_query(F.data == "emo:add")
async def cb_emo_add(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    await state.set_state(EmoAdd.emoji)
    await c.message.edit_text("۱️⃣ یک پیام که ایموجی پریمیوم دارد بفرست یا فوروارد کن:",
                              reply_markup=kb.cancel_state())
    await c.answer()


@router.message(EmoAdd.emoji)
async def st_emo_emoji(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    ids = premium.extract_ids(m)
    if not ids:
        await m.answer("در این پیام ایموجی پریمیومی پیدا نکردم! یکی دیگر بفرست:")
        return
    await state.update_data(emoji_id=ids[0])
    await state.set_state(EmoAdd.name)
    await m.answer("۲️⃣ یک نام کوتاه انگلیسی بده (مثلا: fire):")


@router.message(EmoAdd.name, F.text)
async def st_emo_name(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    import re
    name = m.text.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{1,24}", name):
        await m.answer("فقط حروف کوچک انگلیسی، عدد و _ (حداکثر ۲۴ کاراکتر):")
        return
    d = await state.get_data()
    db.add_emoji(name, d["emoji_id"])
    await state.clear()
    await m.answer(f"✅ ثبت شد! حالا در متن‌ها از <code>{{e:{name}}}</code> استفاده کن.",
                   reply_markup=kb.emoji_list(db.list_emoji()))


@router.callback_query(F.data.startswith("emo:del:"))
async def cb_emo_del(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    db.delete_emoji(c.data.split(":")[2])
    await c.message.edit_text("🗑️ حذف شد.", reply_markup=kb.emoji_list(db.list_emoji()))
    await c.answer()


# ---------------------------------------------------------------- کدهای تخفیف
class DiscAdd(StatesGroup):
    code = State(); percent = State(); maxuses = State()


@router.callback_query(F.data == "adm:disc")
async def cb_disc(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    await c.message.edit_text("🎟️ <b>کدهای تخفیف:</b>", reply_markup=kb.discounts_list(db.list_discounts()))
    await c.answer()


@router.callback_query(F.data == "disc:add")
async def cb_disc_add(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    await state.set_state(DiscAdd.code)
    await c.message.edit_text("۱️⃣ متن کد؟ (انگلیسی، مثلا WELCOME20)", reply_markup=kb.cancel_state())
    await c.answer()


@router.message(DiscAdd.code, F.text)
async def st_disc_code(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    import re
    code = m.text.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_]{3,24}", code):
        await m.answer("فقط حروف انگلیسی/عدد (۳ تا ۲۴ کاراکتر):")
        return
    await state.update_data(code=code)
    await state.set_state(DiscAdd.percent)
    await m.answer("۲️⃣ چند درصد؟ (۱ تا ۱۰۰)")


@router.message(DiscAdd.percent, F.text)
async def st_disc_percent(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    if not m.text.strip().isdigit() or not 1 <= int(m.text) <= 100:
        await m.answer("عدد ۱ تا ۱۰۰:")
        return
    await state.update_data(percent=int(m.text))
    await state.set_state(DiscAdd.maxuses)
    await m.answer("۳️⃣ سقف استفاده؟ (۰ = نامحدود)")


@router.message(DiscAdd.maxuses, F.text)
async def st_disc_maxuses(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    if not m.text.strip().isdigit():
        await m.answer("فقط عدد (۰ = نامحدود):")
        return
    d = await state.get_data()
    db.add_discount(d["code"], d["percent"], int(m.text))
    await state.clear()
    await m.answer(f"✅ کد <code>{d['code']}</code> (٪{d['percent']}) ساخته شد.",
                   reply_markup=kb.discounts_list(db.list_discounts()))


@router.callback_query(F.data.startswith("disc:adm:"))
async def cb_disc_view(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    d = db.get_discount(c.data.split(":")[2])
    if not d:
        await c.answer("یافت نشد.", show_alert=True)
        return
    await c.message.edit_text(
        f"🎟️ <code>{d['code']}</code>\n٪{d['percent']} | استفاده: {d['used']}/{d['max_uses'] or '∞'}\n"
        f"{'✅ فعال' if d['active'] else '🚫 غیرفعال'}",
        reply_markup=kb.discount_detail(d["code"]))
    await c.answer()


@router.callback_query(F.data.startswith(("disc:tgl:", "disc:del:")))
async def cb_disc_router(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    code = c.data.split(":")[2]
    if c.data.startswith("disc:del:"):
        db.delete_discount(code)
        await c.message.edit_text("🗑️ حذف شد.", reply_markup=kb.discounts_list(db.list_discounts()))
    else:
        db.toggle_discount(code)
        d = db.get_discount(code)
        await c.message.edit_text(
            f"🎟️ <code>{d['code']}</code>\n٪{d['percent']} | استفاده: {d['used']}/{d['max_uses'] or '∞'}\n"
            f"{'✅ فعال' if d['active'] else '🚫 غیرفعال'}",
            reply_markup=kb.discount_detail(d["code"]))
    await c.answer()


# ---------------------------------------------------------------- پنل‌های پاسارگارد
class PnlAdd(StatesGroup):
    name = State(); url = State(); key = State()
    username = State(); password = State(); groups = State()


def _panel_text(p: dict) -> str:
    auth = "🔑 کلید API" if p["api_key"] else (f"👤 یوزر/پسورد ({html.quote(p['username'] or '-')})" if p["username"] else "⚠️ بدون احراز هویت")
    n = sum(1 for x in db.list_plans() if x["panel_id"] == p["id"])
    return (f"🛡️ <b>{html.quote(p['name'])}</b>\n"
            f"🌐 <code>{html.quote(p['base_url'])}</code>\n"
            f"{auth}\n"
            f"👥 گروه‌ها: {html.quote(p['group_ids'] or '—')}\n"
            f"💎 پلن‌های متصل: {n}\n"
            f"{'✅ فعال' if p['active'] else '🚫 غیرفعال'}")


@router.callback_query(F.data == "adm:panels")
async def cb_panels(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    await c.message.edit_text("🛡️ <b>پنل‌های پاسارگارد</b>\n(ساخت خودکار یوزر + لینک سابسکرایبشن)",
                              reply_markup=kb.panels_list(db.list_panels()))
    await c.answer()


@router.callback_query(F.data == "pnl:add")
async def cb_pnl_add(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    await state.set_state(PnlAdd.name)
    await c.message.edit_text("۱️⃣ نام پنل؟ (مثلا: پاسارگارد آلمان)", reply_markup=kb.cancel_state())
    await c.answer()


@router.message(PnlAdd.name, F.text)
async def st_pnl_name(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    await state.update_data(name=m.text.strip()[:60])
    await state.set_state(PnlAdd.url)
    await m.answer("۲️⃣ آدرس پنل؟ (مثلا: https://panel.example.com:8000)")


@router.message(PnlAdd.url, F.text)
async def st_pnl_url(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    url = m.text.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        await m.answer("آدرس باید با http شروع شود:")
        return
    await state.update_data(url=url)
    await state.set_state(PnlAdd.key)
    await m.answer("۳️⃣ کلید API پنل؟ (شروعش pg_key_ است)\nاگر نداری بنویس <code>-</code> تا با یوزر/پسورد وصل شویم:")


@router.message(PnlAdd.key, F.text)
async def st_pnl_key(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    key = m.text.strip()
    if key == "-":
        await state.update_data(key="")
        await state.set_state(PnlAdd.username)
        await m.answer("۴️⃣ یوزرنیم ادمین پنل؟")
    else:
        await state.update_data(key=key, username="", password="")
        await state.set_state(PnlAdd.groups)
        await m.answer("۴️⃣ آیدی گروه‌های پنل؟ (با کاما جدا کن؛ اگر نمی‌دانی بنویس <code>-</code>)")


@router.message(PnlAdd.username, F.text)
async def st_pnl_username(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    await state.update_data(username=m.text.strip())
    await state.set_state(PnlAdd.password)
    await m.answer("۵️⃣ پسورد ادمین پنل؟")


@router.message(PnlAdd.password, F.text)
async def st_pnl_password(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    await state.update_data(password=m.text.strip())
    await state.set_state(PnlAdd.groups)
    await m.answer("۶️⃣ آیدی گروه‌های پنل؟ (با کاما جدا کن؛ اگر نمی‌دانی بنویس <code>-</code>)")


@router.message(PnlAdd.groups, F.text)
async def st_pnl_groups(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    d = await state.get_data()
    groups = "" if m.text.strip() == "-" else m.text.strip()
    pid = db.add_panel(d["name"], d["url"], d.get("key", ""),
                       d.get("username", ""), d.get("password", ""), groups)
    await state.clear()
    p = db.get_panel(pid)
    try:
        await m.bot.delete_message(m.chat.id, m.message_id - 1)
    except Exception:
        pass
    await m.answer("✅ پنل ثبت شد. حالا «تست اتصال» بزن:", reply_markup=kb.panel_detail(pid))
    await m.answer(_panel_text(p), reply_markup=kb.panel_detail(pid))


@router.callback_query(F.data.startswith("pnl:"))
async def cb_pnl_router(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    if c.data == "pnl:add":
        return
    parts = c.data.split(":")
    if parts[1] in ("tgl", "del", "test"):
        pid = int(parts[2])
        if parts[1] == "del":
            for x in db.list_plans():
                if x["panel_id"] == pid:
                    db.update_plan(x["id"], panel_id=0)
            db.delete_panel(pid)
            await c.message.edit_text("🗑️ پنل حذف شد (پلن‌هایش دستی شدند).",
                                      reply_markup=kb.panels_list(db.list_panels()))
            await c.answer()
            return
        if parts[1] == "tgl":
            p = db.get_panel(pid)
            db.update_panel(pid, active=0 if p["active"] else 1)
            await c.message.edit_text(_panel_text(db.get_panel(pid)),
                                      reply_markup=kb.panel_detail(pid))
            await c.answer()
            return
        # test
        p = db.get_panel(pid)
        await c.answer("⏳ در حال تست...", show_alert=False)
        try:
            cli = PasarPanel(p["base_url"], p["api_key"], p["username"], p["password"])
            who = await cli.test_connection()
            await c.answer(f"✅ وصل شد! ({who})", show_alert=True)
        except PanelError as e:
            await c.answer(f"❌ {e}", show_alert=True)
        return
    p = db.get_panel(int(parts[1]))
    if not p:
        await c.answer("یافت نشد.", show_alert=True)
        return
    await c.message.edit_text(_panel_text(p), reply_markup=kb.panel_detail(pid))
    await c.answer()


# ---------------------------------------------------------------- مدیران
class StaffAdd(StatesGroup):
    user_id = State()


@router.callback_query(F.data == "adm:staff")
async def cb_staff(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    owner = get_config(interactive=False).admin_id
    await c.message.edit_text("👑 <b>مدیران ربات</b>\n(مدیر کمکی به همه بخش‌های پنل دسترسی دارد)",
                              reply_markup=kb.staff_list(db.list_admins(), owner))
    await c.answer()


@router.callback_query(F.data == "staff:add")
async def cb_staff_add(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    await state.set_state(StaffAdd.user_id)
    await c.message.edit_text("آیدی عددی مدیر جدید؟", reply_markup=kb.cancel_state())
    await c.answer()


@router.message(StaffAdd.user_id, F.text)
async def st_staff_id(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    if not m.text.strip().isdigit():
        await m.answer("فقط آیدی عددی:")
        return
    uid = int(m.text)
    owner = get_config(interactive=False).admin_id
    if uid == owner:
        await m.answer("این آیدی خودِ مالک است!")
        return
    db.add_admin(uid)
    await state.clear()
    await m.answer(f"✅ {uid} مدیر شد.", reply_markup=kb.staff_list(db.list_admins(), owner))


@router.callback_query(F.data.startswith("staff:del:"))
async def cb_staff_del(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    db.remove_admin(int(c.data.split(":")[2]))
    owner = get_config(interactive=False).admin_id
    await c.message.edit_text("🗑️ دسترسی مدیر برداشته شد.",
                              reply_markup=kb.staff_list(db.list_admins(), owner))
    await c.answer()


# ---------------------------------------------------------------- تنظیمات (تست/دعوت/جوین)
class SetVal(StatesGroup):
    value = State()


_SET_KEYS = ("trial_enabled", "trial_days", "trial_volume_gb", "referral_enabled",
             "referral_days", "force_enabled", "force_channel", "force_url")


def _sets_kb():
    return kb.settings_menu({k: db.get_setting(k) for k in _SET_KEYS})


@router.callback_query(F.data == "adm:sets")
async def cb_sets(c: CallbackQuery) -> None:
    if not await _admin_ok(c):
        return
    await c.message.edit_text("⚙️ <b>تنظیمات:</b>", reply_markup=_sets_kb())
    await c.answer()


@router.callback_query(F.data.startswith("set:"))
async def cb_set_router(c: CallbackQuery, state: FSMContext) -> None:
    if not await _admin_ok(c):
        return
    action = c.data.split(":")[1]
    toggles = {"trial_tgl": "trial_enabled", "ref_tgl": "referral_enabled",
               "force_tgl": "force_enabled"}
    if action in toggles:
        k = toggles[action]
        db.set_setting(k, "0" if db.get_setting(k) == "1" else "1")
        if k == "force_enabled" and db.get_setting(k) == "1" and not db.get_setting("force_channel"):
            await c.answer("⚠️ کانال تنظیم نشده! اول «کانال» را ثبت کن.", show_alert=True)
        else:
            await c.answer("انجام شد ✅")
        await c.message.edit_text("⚙️ <b>تنظیمات:</b>", reply_markup=_sets_kb())
        return
    prompts = {"trial_days": "⏱️ مدت اکانت تست (روز)؟",
               "trial_vol": "📊 حجم اکانت تست (گیگ، ۰ = نامحدود)؟",
               "ref_days": "🎁 هدیه دعوت‌کننده (روز)؟",
               "force_ch": "📢 آیدی کانال؟ (@username یا آیدی عددی)\n⚠️ ربات باید ادمین کانال باشد.",
               "force_url": "🔗 لینک عضویت کانال؟ (https://t.me/... یا - برای خودکار)"}
    keys = {"trial_days": "trial_days", "trial_vol": "trial_volume_gb",
            "ref_days": "referral_days", "force_ch": "force_channel",
            "force_url": "force_url"}
    if action not in prompts:
        await c.answer("یافت نشد.", show_alert=True)
        return
    await state.set_state(SetVal.value)
    await state.update_data(key=keys[action])
    await c.message.edit_text(prompts[action], reply_markup=kb.cancel_state())
    await c.answer()


@router.message(SetVal.value, F.text)
async def st_set_value(m: Message, state: FSMContext) -> None:
    if not await _admin_ok(m):
        return
    d = await state.get_data()
    key, val = d["key"], m.text.strip()
    if key in ("trial_days", "trial_volume_gb", "referral_days"):
        num = val.replace("٫", ".")
        if key == "trial_volume_gb":
            try:
                num_f = float(num)
                assert num_f >= 0
            except (ValueError, AssertionError):
                await m.answer("عدد معتبر (۰ = نامحدود):")
                return
            val = str(num_f)
        else:
            if not num.isdigit() or int(num) <= 0:
                await m.answer("فقط عدد مثبت:")
                return
    elif key == "force_channel":
        if not (val.startswith("@") or (val.lstrip("-").isdigit())):
            await m.answer("با @شروع شود یا آیدی عددی باشد:")
            return
        if val.startswith("@"):
            db.set_setting("force_url", "")  # لینک خودکار t.me
    elif key == "force_url":
        if val == "-":
            val = ""
        elif not val.startswith(("http://", "https://", "tg://")):
            await m.answer("لینک معتبر نیست:")
            return
    db.set_setting(key, val)
    await state.clear()
    await m.answer("✅ ذخیره شد.", reply_markup=_sets_kb())
