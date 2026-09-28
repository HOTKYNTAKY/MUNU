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
from config import is_admin
from database import now
from utils import fmt_dt, fmt_left, fmt_price, fmt_volume, render_template, sub_email

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
        f"💎 {html.quote(o['plan_title'])} — {fmt_price(o['amount'])}\n"
        f"🕐 {fmt_dt(o['created_at'])}",
        reply_markup=kb.order_decide(o["id"]),
    )
    await c.answer()


@router.callback_query(F.data.startswith("ord:ok:"))
async def cb_order_ok(c: CallbackQuery) -> None:
    """تایید سفارش: تمدید اشتراک فعال یا ساخت اشتراک تازه + تحویل کانفیگ."""
    if not await _admin_ok(c):
        return
    o = db.get_order(int(c.data.split(":")[2]))
    if not o or o["status"] != "pending":
        await c.answer("این سفارش قبلاً تعیین‌تکلیف شده.", show_alert=True)
        return

    # ۱) اگر اشتراک فعال دارد → تمدید همان
    subs = db.active_subscriptions(o["user_id"])
    if subs:
        sub = subs[-1]  # دیرترین انقضا
        db.extend_subscription(sub["id"], o["plan_days"])
        db.set_order_status(o["id"], "approved")
        s = db.get_subscription(sub["id"])
        user_msg = (f"✅ پرداختت تایید و اشتراکت <b>تمدید</b> شد!\n\n"
                    f"⏳ انقضای جدید: {fmt_dt(s['expires_at'])}\n"
                    f"⏰ باقی‌مانده: {fmt_left(s['expires_at'], now())}")
    else:
        # ۲) وگرنه تخصیص کانفیگ: اول از استخر آماده، بعد از قالب سرور
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
            await c.answer("❌ کانفیگ آزادی نیست! اول از «سرورها» کانفیگ اضافه کن.",
                           show_alert=True)
            return
        db.create_subscription(o["user_id"], o["plan_id"], server_name, cfg, o["plan_days"])
        db.set_order_status(o["id"], "approved")
        user_msg = (f"✅ پرداختت تایید شد! اشتراک فعال شد 🎉\n\n"
                    f"💎 {html.quote(o['plan_title'])}\n"
                    f"🖥️ سرور: {html.quote(server_name)}\n"
                    f"⏳ انقضا: {fmt_left(now() + o['plan_days'] * 86400, now())}\n\n"
                    f"📋 کانفیگت:\n<code>{html.quote(cfg[:3800])}</code>")

    try:
        await c.bot.send_message(o["user_id"], user_msg)
    except Exception:
        log.warning("cannot notify user %d", o["user_id"])
    await c.message.edit_text(f"✅ سفارش #{o['id']} تایید و تحویل داده شد.",
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
    except Exception:
        pass
    await c.message.edit_text(f"❌ سفارش #{o['id']} رد شد.", reply_markup=kb.back_admin())
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
    await c.message.edit_text(
        f"💎 <b>{html.quote(p['title'])}</b>\n⏱️ {p['days']} روز | 📊 {fmt_volume(p['volume_gb'])} | "
        f"💰 {fmt_price(p['price'])}\n{'✅ فعال' if p['active'] else '🚫 غیرفعال'}",
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
