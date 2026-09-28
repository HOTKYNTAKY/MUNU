"""پنل کاربری: شروع، خرید پلن، اشتراک‌ها، کانفیگ، تمدید، تیکت پشتیبانی."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram import html

import database as db
import keyboards as kb
from config import get_config
from database import now
from utils import fmt_dt, fmt_left, fmt_price, fmt_volume

log = logging.getLogger("vpnbot.user")
router = Router()


class Buy(StatesGroup):
    """وضعیت انتظار رسید پرداخت."""
    waiting_receipt = State()


class Ticket(StatesGroup):
    """وضعیت نوشتن تیکت."""
    waiting_text = State()


WELCOME = (
    "👋 سلام {name}!\n"
    "به ربات فروش فیلترشکن خوش اومدی 🚀\n\n"
    "از منوی زیر انتخاب کن:"
)


def _who(m: Message) -> tuple[str, str]:
    u = m.from_user
    return u.username or "", (u.full_name or u.first_name or "")


# ---------------------------------------------------------------- شروع
@router.message(Command("start"))
async def cmd_start(m: Message) -> None:
    db.add_or_update_user(m.from_user.id, *_who(m))
    if db.is_banned(m.from_user.id):
        await m.answer("⛔ شما توسط مدیریت مسدود شده‌اید.")
        return
    await m.answer(WELCOME.format(name=html.quote(m.from_user.first_name or "دوست")),
                   reply_markup=kb.main_menu())


@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext) -> None:
    """انصراف از هر عملیات نیمه‌تمام (خرید، تیکت، ...)."""
    await state.clear()
    await m.answer("❌ انصراف داده شد.", reply_markup=kb.main_menu())


@router.callback_query(F.data == "cancel")
async def cb_cancel(c: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await c.message.edit_text("❌ انصراف داده شد.", reply_markup=kb.main_menu())
    await c.answer()


@router.callback_query(F.data == "back:main")
async def cb_back_main(c: CallbackQuery) -> None:
    await c.message.edit_text("🏠 منوی اصلی:", reply_markup=kb.main_menu())
    await c.answer()


@router.callback_query(F.data == "help")
async def cb_help(c: CallbackQuery) -> None:
    await c.message.edit_text(
        "❓ <b>راهنما</b>\n\n"
        "۱️⃣ از «🛒 خرید اشتراک» یک پلن انتخاب کن.\n"
        "۲️⃣ مبلغ را کارت‌به‌کارت کن و عکس رسید را بفرست.\n"
        "۳️⃣ بعد از تایید ادمین، کانفیگ برایت ارسال می‌شود.\n"
        "۴️⃣ کانفیگ را در اپ V2RayNG (اندروید) یا Streisand / FoXray (آیفون) وارد کن.\n\n"
        f"{html.quote(db.get_setting('support_text'))}",
        reply_markup=kb.back_main(),
    )
    await c.answer()


# ---------------------------------------------------------------- خرید
@router.callback_query(F.data == "plans")
async def cb_plans(c: CallbackQuery) -> None:
    plans = db.list_plans(active_only=True)
    if not plans:
        await c.message.edit_text("😔 فعلاً پلن فعالی وجود ندارد. بعداً سر بزن.",
                                  reply_markup=kb.back_main())
        await c.answer()
        return
    await c.message.edit_text("🛒 <b>پلن‌ها</b> — یکی را انتخاب کن:",
                              reply_markup=kb.plans_list(plans))
    await c.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(c: CallbackQuery) -> None:
    p = db.get_plan(int(c.data.split(":")[1]))
    if not p or not p["active"]:
        await c.answer("این پلن موجود نیست.", show_alert=True)
        return
    await c.message.edit_text(
        f"💎 <b>{html.quote(p['title'])}</b>\n\n"
        f"⏱️ مدت: {p['days']} روز\n"
        f"📊 حجم: {fmt_volume(p['volume_gb'])}\n"
        f"💰 قیمت: {fmt_price(p['price'])}\n\n"
        "💡 اگر اشتراک فعال داشته باشی، این پلن به همان اضافه (تمدید) می‌شود.",
        reply_markup=kb.plan_detail(p["id"]),
    )
    await c.answer()


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(c: CallbackQuery, state: FSMContext) -> None:
    """نمایش کارت + رفتن به وضعیت انتظار رسید."""
    p = db.get_plan(int(c.data.split(":")[1]))
    if not p or not p["active"]:
        await c.answer("این پلن موجود نیست.", show_alert=True)
        return
    card = db.get_setting("card_number")
    holder = db.get_setting("card_holder")
    if not card:
        await c.message.edit_text("😔 پرداخت آنلاین فعلاً فعال نیست. با پشتیبانی در تماس باش.",
                                  reply_markup=kb.back_main())
        await c.answer()
        return
    await state.set_state(Buy.waiting_receipt)
    await state.update_data(plan_id=p["id"])
    await c.message.edit_text(
        f"💳 <b>پرداخت — {html.quote(p['title'])}</b>\n\n"
        f"💰 مبلغ: {fmt_price(p['price'])}\n"
        f"💳 کارت: <code>{html.quote(card)}</code>\n"
        f"👤 به نام: {html.quote(holder or '-')}\n\n"
        "بعد از واریز، <b>عکس رسید</b> یا شماره پیگیری را همین‌جا بفرست:",
        reply_markup=kb.cancel_state(),
    )
    await c.answer()


@router.message(Buy.waiting_receipt, F.photo)
async def msg_receipt_photo(m: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await _submit_order(m, state, receipt_file_id=m.photo[-1].file_id,
                        plan_id=data.get("plan_id"))


@router.message(Buy.waiting_receipt, F.text)
async def msg_receipt_text(m: Message, state: FSMContext) -> None:
    if len(m.text.strip()) < 4:
        await m.answer("متن کوتاه است؛ شماره پیگیری یا توضیح رسید را کامل بفرست:")
        return
    data = await state.get_data()
    await _submit_order(m, state, receipt_text=m.text.strip(),
                        plan_id=data.get("plan_id"))


async def _submit_order(m: Message, state: FSMContext, plan_id: int,
                        receipt_file_id: str = "", receipt_text: str = "") -> None:
    """ثبت سفارش + اطلاع به ادمین."""
    p = db.get_plan(plan_id)
    await state.clear()
    if not p or not p["active"]:
        await m.answer("❌ این پلن دیگر موجود نیست.", reply_markup=kb.main_menu())
        return
    oid = db.create_order(m.from_user.id, p["id"], p["price"],
                          receipt_file_id, receipt_text)
    # پیام به ادمین با دکمه تایید/رد
    admin_id = get_config(interactive=False).admin_id
    uname, fname = _who(m)
    cap = (f"🧾 <b>سفارش جدید #{oid}</b>\n\n"
           f"👤 {html.quote(fname)} (@{html.quote(uname or '-')}) — <code>{m.from_user.id}</code>\n"
           f"💎 {html.quote(p['title'])} — {fmt_price(p['price'])}")
    try:
        if receipt_file_id:
            await m.bot.send_photo(admin_id, receipt_file_id, caption=cap,
                                   reply_markup=kb.order_decide(oid))
        else:
            await m.bot.send_message(admin_id, cap + f"\n📝 رسید: {html.quote(receipt_text)}",
                                     reply_markup=kb.order_decide(oid))
    except Exception:
        log.exception("notify admin for order %d failed", oid)
    await m.answer("✅ سفارشت ثبت شد و بعد از تایید ادمین، کانفیگ ارسال می‌شود.",
                   reply_markup=kb.main_menu())


# ---------------------------------------------------------------- اشتراک‌ها و کانفیگ
@router.callback_query(F.data == "mysub")
async def cb_mysub(c: CallbackQuery) -> None:
    subs = db.active_subscriptions(c.from_user.id)
    if not subs:
        await c.message.edit_text("📦 اشتراک فعالی نداری. از «🛒 خرید اشتراک» شروع کن.",
                                  reply_markup=kb.back_main())
        await c.answer()
        return
    await c.message.edit_text("📦 <b>اشتراک‌های فعالت:</b>",
                              reply_markup=kb.my_subs(subs))
    await c.answer()


@router.callback_query(F.data.startswith("sub:"))
async def cb_sub(c: CallbackQuery) -> None:
    s = db.get_subscription(int(c.data.split(":")[1]))
    if not s or s["user_id"] != c.from_user.id or not s["active"]:
        await c.answer("یافت نشد.", show_alert=True)
        return
    t = now()
    await c.message.edit_text(
        f"📦 <b>{html.quote(s['plan_title'] or 'اشتراک')}</b>\n\n"
        f"🖥️ سرور: {html.quote(s['server_name'])}\n"
        f"📅 شروع: {fmt_dt(s['starts_at'])}\n"
        f"⏳ پایان: {fmt_dt(s['expires_at'])}\n"
        f"⏰ باقی‌مانده: {fmt_left(s['expires_at'], t)}\n\n"
        "💡 برای تمدید، از لیست پلن‌ها خرید کن تا به همین اشتراک اضافه شود.",
        reply_markup=kb.sub_detail(s["id"]),
    )
    await c.answer()


@router.callback_query(F.data.startswith("cfg:"))
async def cb_cfg(c: CallbackQuery) -> None:
    s = db.get_subscription(int(c.data.split(":")[1]))
    if not s or s["user_id"] != c.from_user.id:
        await c.answer("یافت نشد.", show_alert=True)
        return
    if not s["config_text"]:
        await c.answer("کانفیگی ثبت نشده؛ با پشتیبانی در تماس باش.", show_alert=True)
        return
    # کانفیگ در پیام جدا تا کپی راحت باشد + تا ۴۰۰۰ کاراکتر تلگرام
    await c.message.answer(
        f"📋 کانفیگ <b>{html.quote(s['plan_title'] or '')}</b> — {html.quote(s['server_name'])}\n"
        f"<code>{html.quote(s['config_text'][:3800])}</code>")
    await c.answer("ارسال شد ✅")


# ---------------------------------------------------------------- پشتیبانی / تیکت
@router.callback_query(F.data == "support")
async def cb_support(c: CallbackQuery) -> None:
    await c.message.edit_text(f"🆘 <b>پشتیبانی</b>\n\n{html.quote(db.get_setting('support_text'))}",
                              reply_markup=kb.support_menu())
    await c.answer()


@router.callback_query(F.data == "tk:new")
async def cb_ticket_new(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Ticket.waiting_text)
    await c.message.edit_text("✍️ مشکل یا سوالت را در یک پیام بنویس:",
                              reply_markup=kb.cancel_state())
    await c.answer()


@router.message(Ticket.waiting_text, F.text)
async def msg_ticket_text(m: Message, state: FSMContext) -> None:
    if len(m.text.strip()) < 5:
        await m.answer("کمی کامل‌تر بنویس:")
        return
    tid = db.create_ticket(m.from_user.id, m.text.strip())
    await state.clear()
    # اطلاع به ادمین
    uname, fname = _who(m)
    try:
        await m.bot.send_message(
            get_config(interactive=False).admin_id,
            f"🎫 <b>تیکت جدید #{tid}</b>\n👤 {html.quote(fname)} (@{html.quote(uname or '-')})\n\n"
            f"{html.quote(m.text.strip()[:500])}",
            reply_markup=kb.admin_ticket_detail(tid))
    except Exception:
        log.exception("notify admin for ticket failed")
    await m.answer(f"✅ تیکت #{tid} ثبت شد. جوابش همین‌جا می‌آید.",
                   reply_markup=kb.main_menu())


@router.callback_query(F.data == "tk:my")
async def cb_ticket_my(c: CallbackQuery) -> None:
    ts = db.list_user_tickets(c.from_user.id)
    if not ts:
        await c.message.edit_text("📨 هنوز تیکتی ثبت نکردی.", reply_markup=kb.support_menu())
        await c.answer()
        return
    await c.message.edit_text("📨 <b>تیکت‌های تو:</b>", reply_markup=kb.my_tickets(ts))
    await c.answer()


@router.callback_query(F.data.startswith("tk:"))
async def cb_ticket_view(c: CallbackQuery) -> None:
    """نمایش یک تیکت کاربر (دقت: tk:adm و tk:ans و tk:cls مال ادمین‌اند)."""
    if c.data.startswith(("tk:adm", "tk:ans", "tk:cls")):
        return  # مال روتر ادمین است
    t = db.get_ticket(int(c.data.split(":")[1]))
    if not t or t["user_id"] != c.from_user.id:
        await c.answer("یافت نشد.", show_alert=True)
        return
    status = {"open": "🟢 باز", "answered": "✅ پاسخ داده شد", "closed": "🔒 بسته"}.get(t["status"], t["status"])
    txt = (f"🎫 <b>تیکت #{t['id']}</b> — {status}\n\n📝 {html.quote(t['text'])}")
    if t["answer"]:
        txt += f"\n\n💬 <b>پاسخ پشتیبانی:</b>\n{html.quote(t['answer'])}"
    await c.message.edit_text(txt, reply_markup=kb.support_menu())
    await c.answer()
