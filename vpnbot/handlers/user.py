"""پنل کاربری: شروع، خرید پلن، تست، تخفیف، دعوت، اشتراک‌ها، QR، تیکت.

- همه متن‌ها از texts می‌آیند و با px ارسال می‌شوند (ایموجی پریمیوم).
- گیت جوین اجباری روی ورود به خرید و تست.
"""
from __future__ import annotations

import io
import logging
import uuid

try:
    import segno  # اختیاری: اگر نصب نباشد فقط دکمه QR غیرفعال می‌شود
except ImportError:
    segno = None  # type: ignore
from aiogram import F, Router, html
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import database as db
import keyboards as kb
from config import get_config, is_admin
from database import now
from panels import PanelError, PasarPanel
from texts import T
from utils import fmt_dt, fmt_left, fmt_price, fmt_volume, panel_uname, px, px_edit

log = logging.getLogger("vpnbot.user")
router = Router()


class Buy(StatesGroup):
    """خرید: انتظار کد تخفیف / رسید پرداخت."""
    waiting_code = State()
    waiting_receipt = State()


class Ticket(StatesGroup):
    """وضعیت نوشتن تیکت."""
    waiting_text = State()


def _who(m: Message) -> tuple[str, str]:
    u = m.from_user
    return u.username or "", (u.full_name or u.first_name or "")


def _gids(s: str) -> list[int]:
    return [int(x) for x in (s or "").split(",") if x.strip().isdigit()]


def _menu(uid: int):
    return kb.main_menu(uid)


class _NeedJoin(Exception):
    pass


async def _force_blocked(c: CallbackQuery) -> bool:
    """True یعنی کاربر هنوز عضو کانال نیست و پیام جوین نمایش داده شد."""
    if db.get_setting("force_enabled") != "1":
        return False
    ch = (db.get_setting("force_channel") or "").strip()
    if not ch or is_admin(c.from_user.id):
        return False
    try:
        m = await c.bot.get_chat_member(ch, c.from_user.id)
        if m.status in ("left", "kicked"):
            raise _NeedJoin()
        return False
    except _NeedJoin:
        pass
    except Exception:
        log.warning("force-join check failed (fail-open)")
        return False  # اگر ربات ادمین کانال نیست، کسی قفل نشود
    url = (db.get_setting("force_url") or "").strip()
    if not url and ch.startswith("@"):
        url = f"https://t.me/{ch[1:]}"
    await px_edit(c.message, T("msg_force"), kb.force_join(url))
    await c.answer()
    return True


# ---------------------------------------------------------------- شروع
@router.message(Command("start"))
async def cmd_start(m: Message) -> None:
    db.add_or_update_user(m.from_user.id, *_who(m))
    if db.is_banned(m.from_user.id):
        await m.answer(T("msg_banned"))
        return
    # لینک دعوت: /start ref123
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("ref") and parts[1][3:].isdigit():
        ref_id = int(parts[1][3:])
        if ref_id != m.from_user.id and db.get_user(ref_id):
            db.set_referred(m.from_user.id, ref_id)
    name = html.quote(m.from_user.first_name or "دوست")
    await px(m.bot, m.chat.id, T("msg_welcome").replace("{name}", name),
             _menu(m.from_user.id))


@router.message(Command("id"))
async def cmd_id(m: Message) -> None:
    """نمایش آیدی عددی (برای عیب‌یابی دسترسی ادمین)."""
    await m.answer(f"🆔 آیدی تو: <code>{m.from_user.id}</code>")


@router.message(Command("cancel"))
async def cmd_cancel(m: Message, state: FSMContext) -> None:
    """انصراف از هر عملیات نیمه‌تمام (خرید، تیکت، ...)."""
    await state.clear()
    await px(m.bot, m.chat.id, T("msg_cancelled"), _menu(m.from_user.id))


@router.callback_query(F.data == "cancel")
async def cb_cancel(c: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await px_edit(c.message, T("msg_cancelled"), _menu(c.from_user.id))
    await c.answer()


@router.callback_query(F.data == "back:main")
async def cb_back_main(c: CallbackQuery) -> None:
    await px_edit(c.message, T("msg_main"), _menu(c.from_user.id))
    await c.answer()


@router.callback_query(F.data == "help")
async def cb_help(c: CallbackQuery) -> None:
    txt = T("msg_help") + "\n\n" + html.quote(db.get_setting("support_text"))
    await px_edit(c.message, txt, kb.back_main())
    await c.answer()


# ---------------------------------------------------------------- خرید
@router.callback_query(F.data == "plans")
async def cb_plans(c: CallbackQuery) -> None:
    if await _force_blocked(c):
        return
    plans = db.list_plans(active_only=True)
    if not plans:
        await px_edit(c.message, T("msg_plans_empty"), kb.back_main())
        await c.answer()
        return
    await px_edit(c.message, T("msg_plans"), kb.plans_list(plans))
    await c.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(c: CallbackQuery) -> None:
    p = db.get_plan(int(c.data.split(":")[1]))
    if not p or not p["active"]:
        await c.answer("این پلن موجود نیست.", show_alert=True)
        return
    await px_edit(
        c.message,
        f"💎 <b>{html.quote(p['title'])}</b>\n\n"
        f"⏱️ مدت: {p['days']} روز\n"
        f"📊 حجم: {fmt_volume(p['volume_gb'])}\n"
        f"💰 قیمت: {fmt_price(p['price'])}\n\n"
        "💡 اگر اشتراک فعال داشته باشی، این پلن به همان اضافه (تمدید) می‌شود.\n"
        "🎟️ کد تخفیف داری؟ دکمه «کد تخفیف» را بزن.",
        kb.plan_detail(p["id"]),
    )
    await c.answer()


def _pay_text(p: dict, amount: int, code: str, card: str, holder: str) -> str:
    lines = [f"💳 <b>پرداخت — {html.quote(p['title'])}</b>", "",
             f"💰 مبلغ: {fmt_price(amount)}"]
    if code:
        lines.append(f"🎟️ کد تخفیف: <code>{html.quote(code)}</code> ✅")
    lines += ["", f"💳 کارت: <code>{html.quote(card)}</code>",
              f"👤 به نام: {html.quote(holder or '-')}", "",
              "بعد از واریز، <b>عکس رسید</b> یا شماره پیگیری را همین‌جا بفرست:"]
    return "\n".join(lines)


async def _show_payment(c: CallbackQuery, state: FSMContext, p: dict,
                        amount: int, code: str = "") -> None:
    card = db.get_setting("card_number")
    holder = db.get_setting("card_holder")
    if not card:
        await px_edit(c.message, T("msg_pay_off"), kb.back_main())
        await c.answer()
        return
    await state.set_state(Buy.waiting_receipt)
    await state.update_data(plan_id=p["id"], amount=amount, code=code)
    await px_edit(c.message, _pay_text(p, amount, code, card, holder),
                  kb.cancel_state())
    await c.answer()


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(c: CallbackQuery, state: FSMContext) -> None:
    """پرداخت با قیمت کامل + رفتن به وضعیت انتظار رسید."""
    p = db.get_plan(int(c.data.split(":")[1]))
    if not p or not p["active"]:
        await c.answer("این پلن موجود نیست.", show_alert=True)
        return
    await _show_payment(c, state, p, p["price"])


@router.callback_query(F.data.startswith("disc:"))
async def cb_discount_ask(c: CallbackQuery, state: FSMContext) -> None:
    p = db.get_plan(int(c.data.split(":")[1]))
    if not p or not p["active"]:
        await c.answer("این پلن موجود نیست.", show_alert=True)
        return
    await state.set_state(Buy.waiting_code)
    await state.update_data(plan_id=p["id"])
    await px_edit(c.message, T("msg_discount_ask"), kb.discount_ask(p["id"]))
    await c.answer()


@router.message(Buy.waiting_code, F.text)
async def msg_discount_code(m: Message, state: FSMContext) -> None:
    data = await state.get_data()
    p = db.get_plan(data.get("plan_id") or 0)
    if not p or not p["active"]:
        await state.clear()
        await px(m.bot, m.chat.id, "❌ این پلن دیگر موجود نیست.", _menu(m.from_user.id))
        return
    d = db.valid_discount(m.text.strip())
    if not d:
        await m.answer(T("msg_discount_bad"))
        return  # در همان وضعیت می‌ماند تا دوباره تلاش کند یا انصراف بزند
    amount = max(0, round(p["price"] * (100 - d["percent"]) / 100))
    card = db.get_setting("card_number")
    if not card:
        await state.clear()
        await px(m.bot, m.chat.id, T("msg_pay_off"), kb.back_main())
        return
    await state.set_state(Buy.waiting_receipt)
    await state.update_data(plan_id=p["id"], amount=amount, code=d["code"])
    await px(m.bot, m.chat.id,
             T("msg_discount_ok", percent=d["percent"], price=fmt_price(amount)) + "\n\n"
             + _pay_text(p, amount, d["code"], card, db.get_setting("card_holder")),
             kb.cancel_state())


@router.message(Buy.waiting_receipt, F.photo)
async def msg_receipt_photo(m: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await _submit_order(m, state, receipt_file_id=m.photo[-1].file_id,
                        plan_id=data.get("plan_id"), amount=data.get("amount"),
                        code=data.get("code") or "")


@router.message(Buy.waiting_receipt, F.text)
async def msg_receipt_text(m: Message, state: FSMContext) -> None:
    if len(m.text.strip()) < 4:
        await m.answer("متن کوتاه است؛ شماره پیگیری یا توضیح رسید را کامل بفرست:")
        return
    data = await state.get_data()
    await _submit_order(m, state, receipt_text=m.text.strip(),
                        plan_id=data.get("plan_id"), amount=data.get("amount"),
                        code=data.get("code") or "")


async def _submit_order(m: Message, state: FSMContext, plan_id: int,
                        amount: int | None = None, code: str = "",
                        receipt_file_id: str = "", receipt_text: str = "") -> None:
    """ثبت سفارش + اطلاع به ادمین."""
    p = db.get_plan(plan_id)
    await state.clear()
    if not p or not p["active"]:
        await px(m.bot, m.chat.id, "❌ این پلن دیگر موجود نیست.", _menu(m.from_user.id))
        return
    # اعتبارسنجی دوباره کد (ممکن است ظرفیتش تمام شده باشد)
    if code:
        d = db.valid_discount(code)
        if not d:
            code, amount = "", None
        else:
            amount = max(0, round(p["price"] * (100 - d["percent"]) / 100))
    amount = p["price"] if amount is None else amount
    oid = db.create_order(m.from_user.id, p["id"], amount,
                          receipt_file_id, receipt_text, code)
    if code:
        db.use_discount(code)
    # پیام به همه ادمین‌ها با دکمه تایید/رد
    admin_ids = [get_config(interactive=False).admin_id] + db.list_admins()
    uname, fname = _who(m)
    cap = (f"🧾 <b>سفارش جدید #{oid}</b>\n\n"
           f"👤 {html.quote(fname)} (@{html.quote(uname or '-')}) — <code>{m.from_user.id}</code>\n"
           f"💎 {html.quote(p['title'])} — {fmt_price(amount)}"
           + (f"\n🎟️ کد: <code>{html.quote(code)}</code>" if code else ""))
    for admin_id in admin_ids:
        try:
            if receipt_file_id:
                await m.bot.send_photo(admin_id, receipt_file_id, caption=cap,
                                       reply_markup=kb.order_decide(oid))
            else:
                await m.bot.send_message(admin_id, cap + f"\n📝 رسید: {html.quote(receipt_text)}",
                                         reply_markup=kb.order_decide(oid))
        except Exception:
            log.warning("notify admin %d for order %d failed", admin_id, oid)
    await px(m.bot, m.chat.id, T("msg_order_ok"), _menu(m.from_user.id))


# ---------------------------------------------------------------- تست رایگان
@router.callback_query(F.data == "trial")
async def cb_trial(c: CallbackQuery) -> None:
    if await _force_blocked(c):
        return
    uid = c.from_user.id
    u = db.get_user(uid)
    days = int(db.get_setting("trial_days") or 1)
    if db.get_setting("trial_enabled") != "1" or not u or u["trial_used"] \
            or db.active_subscriptions(uid):
        await c.answer(T("msg_trial_no"), show_alert=True)
        return
    vol_gb = int(db.get_setting("trial_volume_gb") or 5)
    panel = db.first_active_panel()
    server_name, cfg_text, panel_id, panel_user, sub_link = "", "", 0, "", ""
    if panel:
        try:
            cli = PasarPanel(panel["base_url"], panel["api_key"],
                             panel["username"], panel["password"])
            resp = await cli.create_user(panel_uname(uid, "trial"), now() + days * 86400,
                                         int(vol_gb * 1024 ** 3),
                                         note=f"trial {uid}", group_ids=_gids(panel["group_ids"]))
            sub_link = cli.absolute_sub_url(resp)
            cfg_text = sub_link
            server_name, panel_id = panel["name"], panel["id"]
            panel_user = panel_uname(uid, "trial")
        except PanelError as e:
            log.warning("trial panel failed: %s", e)
            await c.answer(f"❌ خطای پنل: {e}", show_alert=True)
            return
    else:
        cfg = db.get_free_config()
        if cfg:
            db.assign_config(cfg["id"], uid)
            server_name, cfg_text = cfg["server_name"], cfg["config_text"]
        else:
            tpl = db.template_server()
            if not tpl or not tpl["template"]:
                await c.answer(T("msg_trial_empty"), show_alert=True)
                return
            cfg_text = tpl["template"].replace("{UUID}", str(uuid.uuid4())).replace(
                "{EMAIL}", f"u{uid}-trial")
            server_name = tpl["name"]
    sid = db.create_subscription(uid, 0, server_name, cfg_text, days,
                                 panel_id=panel_id, panel_username=panel_user,
                                 sub_link=sub_link)
    db.set_trial_used(uid)
    await px_edit(c.message, T("msg_trial_ok").replace("{days}", str(days)),
                  kb.sub_detail(sid, has_link=bool(sub_link or cfg_text)))
    await c.answer("🎉")


# ---------------------------------------------------------------- دعوت دوستان
@router.callback_query(F.data == "invite")
async def cb_invite(c: CallbackQuery) -> None:
    if db.get_setting("referral_enabled") != "1":
        await c.answer("بخش دعوت فعلاً خاموش است.", show_alert=True)
        return
    me = await c.bot.me()
    link = f"https://t.me/{me.username}?start=ref{c.from_user.id}"
    txt = (T("msg_invite")
           .replace("{count}", str(db.count_referrals(c.from_user.id)))
           .replace("{days}", db.get_setting("referral_days") or "3")
           .replace("{link}", link))
    await px_edit(c.message, txt, kb.back_main())
    await c.answer()


# ---------------------------------------------------------------- اشتراک‌ها و کانفیگ
@router.callback_query(F.data == "mysub")
async def cb_mysub(c: CallbackQuery) -> None:
    subs = db.active_subscriptions(c.from_user.id)
    if not subs:
        await px_edit(c.message, T("msg_no_sub"), kb.back_main())
        await c.answer()
        return
    await px_edit(c.message, T("msg_my_subs"), kb.my_subs(subs))
    await c.answer()


@router.callback_query(F.data.startswith("sub:"))
async def cb_sub(c: CallbackQuery) -> None:
    s = db.get_subscription(int(c.data.split(":")[1]))
    if not s or s["user_id"] != c.from_user.id or not s["active"]:
        await c.answer("یافت نشد.", show_alert=True)
        return
    t = now()
    link = (s["sub_link"] or "").strip()
    txt = (f"📦 <b>{html.quote(s['plan_title'] or 'اشتراک')}</b>\n\n"
           f"🖥️ سرور: {html.quote(s['server_name'])}\n"
           f"📅 شروع: {fmt_dt(s['starts_at'])}\n"
           f"⏳ پایان: {fmt_dt(s['expires_at'])}\n"
           f"⏰ باقی‌مانده: {fmt_left(s['expires_at'], t)}")
    if link:
        txt += f"\n\n🔗 <b>لینک اشتراک:</b>\n<code>{html.quote(link)}</code>"
    txt += "\n\n💡 برای تمدید، از لیست پلن‌ها خرید کن تا به همین اشتراک اضافه شود."
    await px_edit(c.message, txt,
                  kb.sub_detail(s["id"], has_link=bool(link or s["config_text"])))
    await c.answer()


@router.callback_query(F.data.startswith("cfg:"))
async def cb_cfg(c: CallbackQuery) -> None:
    s = db.get_subscription(int(c.data.split(":")[1]))
    if not s or s["user_id"] != c.from_user.id:
        await c.answer("یافت نشد.", show_alert=True)
        return
    cfg = (s["config_text"] or "").strip()
    if not cfg:
        await c.answer("کانفیگی ثبت نشده؛ با پشتیبانی در تماس باش.", show_alert=True)
        return
    title = html.quote(s["plan_title"] or "")
    # لینک اشتراک تکی → پیام متنی برای کپی راحت؛ چندخطی → بلوک کد
    if cfg.startswith("http") and "\n" not in cfg:
        await px(c.bot, c.message.chat.id,
                 f"🔗 لینک اشتراک <b>{title}</b>:\n<code>{html.quote(cfg)}</code>\n\n"
                 "آن را در اپ کپی کن یا با دکمه QR اسکنش کن 📷")
    else:
        await c.message.answer(
            f"📋 کانفیگ <b>{title}</b> — {html.quote(s['server_name'])}\n"
            f"<code>{html.quote(cfg[:3800])}</code>")
    await c.answer("ارسال شد ✅")


@router.callback_query(F.data.startswith("qr:"))
async def cb_qr(c: CallbackQuery) -> None:
    s = db.get_subscription(int(c.data.split(":")[1]))
    if not s or s["user_id"] != c.from_user.id:
        await c.answer("یافت نشد.", show_alert=True)
        return
    link = (s["sub_link"] or "").strip() or (s["config_text"] or "").strip()
    if not link or "\n" in link or len(link) > 2000:
        await c.answer("برای این اشتراک QR موجود نیست.", show_alert=True)
        return
    if segno is None:
        await c.answer("QR فعلاً در دسترس نیست (کتابخانه‌اش نصب نشده).", show_alert=True)
        return
    buf = io.BytesIO()
    segno.make(link).save(buf, kind="png", scale=6)
    buf.seek(0)
    await c.message.answer_photo(
        BufferedInputFile(buf.getvalue(), filename="sub-qr.png"),
        caption=f"📷 QR اشتراک <b>{html.quote(s['plan_title'] or '')}</b>\n"
                "با دوربین اپ V2RayNG / Streisand اسکن کن.")
    await c.answer()


# ---------------------------------------------------------------- پشتیبانی / تیکت
@router.callback_query(F.data == "support")
async def cb_support(c: CallbackQuery) -> None:
    txt = f"🆘 <b>پشتیبانی</b>\n\n{html.quote(db.get_setting('support_text'))}"
    await px_edit(c.message, txt, kb.support_menu())
    await c.answer()


@router.callback_query(F.data == "tk:new")
async def cb_ticket_new(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Ticket.waiting_text)
    await px_edit(c.message, "✍️ مشکل یا سوالت را در یک پیام بنویس:",
                  kb.cancel_state())
    await c.answer()


@router.message(Ticket.waiting_text, F.text)
async def msg_ticket_text(m: Message, state: FSMContext) -> None:
    if len(m.text.strip()) < 5:
        await m.answer("کمی کامل‌تر بنویس:")
        return
    tid = db.create_ticket(m.from_user.id, m.text.strip())
    await state.clear()
    # اطلاع به همه ادمین‌ها
    uname, fname = _who(m)
    for admin_id in [get_config(interactive=False).admin_id] + db.list_admins():
        try:
            await m.bot.send_message(
                admin_id,
                f"🎫 <b>تیکت جدید #{tid}</b>\n👤 {html.quote(fname)} (@{html.quote(uname or '-')})\n\n"
                f"{html.quote(m.text.strip()[:500])}",
                reply_markup=kb.admin_ticket_detail(tid))
        except Exception:
            log.warning("notify admin %d for ticket failed", admin_id)
    await px(m.bot, m.chat.id, T("msg_ticket_done", id=tid),
             _menu(m.from_user.id))


@router.callback_query(F.data == "tk:my")
async def cb_ticket_my(c: CallbackQuery) -> None:
    ts = db.list_user_tickets(c.from_user.id)
    if not ts:
        await px_edit(c.message, "📨 هنوز تیکتی ثبت نکردی.", kb.support_menu())
        await c.answer()
        return
    await px_edit(c.message, "📨 <b>تیکت‌های تو:</b>", kb.my_tickets(ts))
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
    await px_edit(c.message, txt, kb.support_menu())
    await c.answer()
    await px_edit(c.message, txt, kb.support_menu())
    await c.answer()
