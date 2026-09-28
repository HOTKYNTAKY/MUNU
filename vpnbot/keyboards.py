"""کیبوردهای اینلاین کاربر و ادمین.

- متن همه دکمه‌ها از texts می‌آید (قابل ویرایش از پنل ادمین).
- {e:name} در لیبل دکمه → آیکون ایموجی پریمیوم.
- دکمه با لینک (http/tg) → دکمه شیشه‌ای (URL).
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import database as db
import premium
from texts import T


def _btn(label: str, data: str) -> InlineKeyboardButton:
    text, icon = premium.parse_button(label)
    kw: dict = {"text": text[:64]}
    if icon:
        kw["icon_custom_emoji_id"] = icon
    if data.startswith(("http://", "https://", "tg://")):
        kw["url"] = data
    else:
        kw["callback_data"] = data
    return InlineKeyboardButton(**kw)


def _mk(*rows: tuple[str, str], widths: tuple[int, ...] = (1,)) -> InlineKeyboardMarkup:
    btns = [_btn(t, d) for t, d in rows]
    grid: list[list[InlineKeyboardButton]] = []
    i, w = 0, list(widths)
    while i < len(btns):
        n = w[0] if len(w) == 1 else (w[len(grid)] if len(grid) < len(w) else 1)
        grid.append(btns[i:i + n])
        i += n
    return InlineKeyboardMarkup(inline_keyboard=grid)


def _glass_rows() -> list[tuple[str, str]]:
    """دکمه‌های شیشه‌ای فعال منوی اصلی."""
    return [(b["text"], b["url"]) for b in db.list_menu_buttons(active_only=True)]


# ---------------------------------------------------------- منوی کاربر
def main_menu(user_id: int = 0) -> InlineKeyboardMarkup:
    rows = [
        (T("btn_buy"), "plans"),
        (T("btn_mysub"), "mysub"),
        (T("btn_wallet"), "wallet"),
    ]
    if user_id and db.get_setting("trial_enabled") == "1":
        u = db.get_user(user_id)
        if u and not u["trial_used"] and not db.active_subscriptions(user_id):
            rows.append((T("btn_trial"), "trial"))
    if db.get_setting("referral_enabled") == "1":
        rows.append((T("btn_invite"), "invite"))
    rows += [
        (T("btn_support"), "support"),
        (T("btn_help"), "help"),
    ]
    rows += _glass_rows()
    return _mk(*rows)


def back_main() -> InlineKeyboardMarkup:
    return _mk((T("btn_back"), "back:main"))


def plans_list(plans: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"{p['title']} — {p['price']:,} تومان", f"buy:{p['id']}") for p in plans]
    rows.append((T("btn_back"), "back:main"))
    return _mk(*rows)


def plan_detail(plan_id: int) -> InlineKeyboardMarkup:
    return _mk(
        (T("btn_buy_this"), f"pay:{plan_id}"),
        (T("btn_discount"), f"disc:{plan_id}"),
        (T("btn_wpay"), f"wpay:{plan_id}"),
        (T("btn_plans"), "plans"),
    )


def discount_ask(plan_id: int) -> InlineKeyboardMarkup:
    return _mk(
        (T("btn_skip_discount"), f"pay:{plan_id}"),
        (T("btn_back"), "plans"),
    )


def my_subs(subs: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"📦 {(s['plan_title'] or 'اشتراک')} — {s['server_name']}", f"sub:{s['id']}") for s in subs]
    rows.append((T("btn_back"), "back:main"))
    return _mk(*rows)


def sub_detail(sub_id: int, has_link: bool = True) -> InlineKeyboardMarkup:
    rows = [(T("btn_get_config"), f"cfg:{sub_id}")]
    if has_link:
        rows.append((T("btn_qr"), f"qr:{sub_id}"))
    rows += [(T("btn_renew"), "plans"), (T("btn_mysub"), "mysub")]
    return _mk(*rows)


def support_menu() -> InlineKeyboardMarkup:
    return _mk(
        (T("btn_new_ticket"), "tk:new"),
        (T("btn_my_tickets"), "tk:my"),
        (T("btn_back"), "back:main"),
    )


def my_tickets(tickets: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"#{t['id']} — {'🟢 باز' if t['status'] == 'open' else '✅ پاسخ داده شد'}", f"tk:{t['id']}") for t in tickets]
    rows.append((T("btn_back"), "support"))
    return _mk(*rows)


def force_join(url: str) -> InlineKeyboardMarkup:
    rows = []
    if url:
        rows.append(("📢 عضویت در کانال", url))
    rows.append((T("btn_joined"), "plans"))
    return _mk(*rows)


# ---------------------------------------------------------- پنل ادمین
def admin_menu(n_orders: int = 0, n_tickets: int = 0, n_topups: int = 0) -> InlineKeyboardMarkup:
    return _mk(
        ("📊 آمار", "adm:stats"),
        (f"🧾 سفارش‌های در انتظار ({n_orders})", "adm:orders"),
        (f"🎫 تیکت‌های باز ({n_tickets})", "adm:tickets"),
        (f"💰 شارژهای در انتظار ({n_topups})", "adm:topups"),
        ("💎 پلن‌ها", "adm:plans"),
        ("🖥️ سرورها", "adm:srv"),
        ("🛡️ پنل‌های پاسارگارد", "adm:panels"),
        ("🎟️ کدهای تخفیف", "adm:disc"),
        ("👥 کاربران", "adm:users"),
        ("👑 مدیران", "adm:staff"),
        ("✏️ متن‌ها و دکمه‌ها", "adm:texts"),
        ("🔗 دکمه‌های شیشه‌ای", "adm:mbtn"),
        ("✨ ایموجی پریمیوم", "adm:emoji"),
        ("💳 پرداخت", "adm:pay"),
        ("📣 پیام همگانی", "adm:bc"),
        ("⚙️ تنظیمات (تست/دعوت/جوین)", "adm:sets"),
        ("💾 بکاپ فوری", "adm:backup"),
        ("♻️ ریستور", "adm:restore"),
        widths=(1, 1, 1, 1, 3, 2, 2, 2, 2, 1, 2),
    )


def back_admin() -> InlineKeyboardMarkup:
    return _mk(("🔙 پنل ادمین", "adm"))


def admin_plans(plans: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"{'✅' if p['active'] else '🚫'} {p['title']} — {p['price']:,}", f"pl:{p['id']}") for p in plans]
    rows += [("➕ افزودن پلن", "pl:add"), ("🔙 پنل ادمین", "adm")]
    return _mk(*rows)


def admin_plan_detail(p: dict) -> InlineKeyboardMarkup:
    return _mk(
        ("✏️ ویرایش", f"pl:edit:{p['id']}"),
        ("🛡️ پنل پاسارگارد", f"pl:panel:{p['id']}"),
        ("🔀 فعال/غیرفعال", f"pl:tgl:{p['id']}"),
        ("🗑️ حذف", f"pl:del:{p['id']}"),
        ("🔙 پلن‌ها", "adm:plans"),
        widths=(2, 2, 1),
    )


def plan_edit_fields(plan_id: int) -> InlineKeyboardMarkup:
    return _mk(
        ("عنوان", f"pl:ef:{plan_id}:title"),
        ("مدت (روز)", f"pl:ef:{plan_id}:days"),
        ("حجم (گیگ)", f"pl:ef:{plan_id}:volume_gb"),
        ("قیمت", f"pl:ef:{plan_id}:price"),
        ("🔙", f"pl:{plan_id}"),
        widths=(2, 2, 1),
    )


def plan_panel_select(plan_id: int, panels: list[dict], current: int) -> InlineKeyboardMarkup:
    rows = [(f"{'✅ ' if current == 0 else ''}🤝 دستی (استخر/قالب)", f"pl:pset:{plan_id}:0")]
    for s in panels:
        rows.append((f"{'✅ ' if current == s['id'] else ''}🛡️ {s['name']}", f"pl:pset:{plan_id}:{s['id']}"))
    rows.append(("🔙", f"pl:{plan_id}"))
    return _mk(*rows)


def admin_users(users: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"{'🚫' if u['banned'] else '👤'} {u['full_name'] or u['username'] or u['id']}", f"usr:{u['id']}") for u in users]
    rows += [("🔎 جستجوی کاربر", "usr:find"), ("🔙 پنل ادمین", "adm")]
    return _mk(*rows)


def admin_user_detail(u: dict) -> InlineKeyboardMarkup:
    return _mk(
        ("➕ افزایش روز اشتراک", f"usr:days:{u['id']}"),
        ("💰 تغییر موجودی", f"usr:bal:{u['id']}"),
        ("🚫 مسدود" if not u["banned"] else "✅ رفع مسدودیت", f"usr:ban:{u['id']}"),
        ("🔙 کاربران", "adm:users"),
    )


def admin_orders(orders: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"#{o['id']} {o['full_name'] or o['username']} — {o['plan_title']} — {o['amount']:,}", f"ord:{o['id']}") for o in orders]
    rows.append(("🔙 پنل ادمین", "adm"))
    return _mk(*rows)


def order_decide(order_id: int) -> InlineKeyboardMarkup:
    return _mk(
        ("✅ تایید و تحویل", f"ord:ok:{order_id}"),
        ("🧾 مشاهده رسید", f"ord:view:{order_id}"),
        ("❌ رد", f"ord:no:{order_id}"),
        ("🔙 سفارش‌ها", "adm:orders"),
        widths=(1, 2, 1),
    )


def admin_tickets(tickets: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"#{t['id']} {t['full_name'] or t['username']}", f"tk:adm:{t['id']}") for t in tickets]
    rows.append(("🔙 پنل ادمین", "adm"))
    return _mk(*rows)


def admin_ticket_detail(ticket_id: int) -> InlineKeyboardMarkup:
    return _mk(
        ("✍️ پاسخ", f"tk:ans:{ticket_id}"),
        ("🔒 بستن", f"tk:cls:{ticket_id}"),
        ("🔙 تیکت‌ها", "adm:tickets"),
    )


def admin_servers(servers: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"{'✅' if s['active'] else '🚫'} {s['name']} (آزاد: {s['free']})", f"srv:{s['id']}") for s in servers]
    rows += [("➕ افزودن سرور", "srv:add"), ("🔙 پنل ادمین", "adm")]
    return _mk(*rows)


def admin_server_detail(s: dict) -> InlineKeyboardMarkup:
    return _mk(
        ("➕ افزودن کانفیگ آماده", f"cfg:add:{s['id']}"),
        ("🔀 فعال/غیرفعال", f"srv:tgl:{s['id']}"),
        ("🗑️ حذف سرور", f"srv:del:{s['id']}"),
        ("🔙 سرورها", "adm:srv"),
        widths=(1, 2, 1),
    )


def pay_settings() -> InlineKeyboardMarkup:
    return _mk(
        ("💳 ثبت شماره کارت", "pay:card"),
        ("👤 ثبت نام صاحب کارت", "pay:holder"),
        ("🔙 پنل ادمین", "adm"),
    )


def broadcast_confirm() -> InlineKeyboardMarkup:
    return _mk(
        ("📣 بله، ارسال شود", "bc:yes"),
        ("❌ انصراف", "adm"),
        widths=(2,),
    )


def cancel_state() -> InlineKeyboardMarkup:
    return _mk((T("btn_cancel"), "cancel"), widths=(1,))


# ---------------------------------------------------------- بخش‌های جدید ادمین
def texts_cats() -> InlineKeyboardMarkup:
    return _mk(
        ("🔘 دکمه‌ها", "txtc:btn"),
        ("💬 پیام‌ها", "txtc:msg"),
        ("🔙 پنل ادمین", "adm"),
        widths=(2, 1),
    )


def texts_list(keys: list[str], labels: dict[str, str]) -> InlineKeyboardMarkup:
    rows = [(labels[k], f"txt:{k}") for k in keys]
    rows.append(("🔙 متن‌ها", "adm:texts"))
    return _mk(*rows)


def menu_buttons_list(btns: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"{'✅' if b['active'] else '🚫'} {b['text']}", f"mbtn:{b['id']}") for b in btns]
    rows += [("➕ افزودن دکمه", "mbtn:add"), ("🔙 پنل ادمین", "adm")]
    return _mk(*rows)


def menu_button_detail(bid: int) -> InlineKeyboardMarkup:
    return _mk(
        ("🔀 فعال/غیرفعال", f"mbtn:tgl:{bid}"),
        ("🗑️ حذف", f"mbtn:del:{bid}"),
        ("🔙 دکمه‌ها", "adm:mbtn"),
        widths=(2, 1),
    )


def emoji_list(emojis: list[dict]) -> InlineKeyboardMarkup:
    rows = [("{e:%s} %s" % (e["name"], e["name"]), f"emo:del:{e['name']}") for e in emojis]
    rows += [("➕ افزودن (فوروارد ایموجی)", "emo:add"), ("🔙 پنل ادمین", "adm")]
    return _mk(*rows)


def discounts_list(codes: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"{'✅' if c['active'] else '🚫'} {c['code']} ٪{c['percent']} ({c['used']}/{c['max_uses'] or '∞'})",
             f"disc:adm:{c['code']}") for c in codes]
    rows += [("➕ کد جدید", "disc:add"), ("🔙 پنل ادمین", "adm")]
    return _mk(*rows)


def discount_detail(code: str) -> InlineKeyboardMarkup:
    return _mk(
        ("🔀 فعال/غیرفعال", f"disc:tgl:{code}"),
        ("🗑️ حذف", f"disc:del:{code}"),
        ("🔙 کدها", "adm:disc"),
        widths=(2, 1),
    )


def panels_list(panels: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"{'✅' if p['active'] else '🚫'} 🛡️ {p['name']}", f"pnl:{p['id']}") for p in panels]
    rows += [("➕ افزودن پنل", "pnl:add"), ("🔙 پنل ادمین", "adm")]
    return _mk(*rows)


def panel_detail(pid: int) -> InlineKeyboardMarkup:
    return _mk(
        ("🔌 تست اتصال", f"pnl:test:{pid}"),
        ("🔀 فعال/غیرفعال", f"pnl:tgl:{pid}"),
        ("🗑️ حذف", f"pnl:del:{pid}"),
        ("🔙 پنل‌ها", "adm:panels"),
        widths=(1, 2, 1),
    )


def staff_list(admins: list[int], owner_id: int) -> InlineKeyboardMarkup:
    rows = [(f"👑 مالک: {owner_id}", "adm:staff")]
    rows += [(f"🛡️ {a} (حذف)", f"staff:del:{a}") for a in admins]
    rows += [("➕ افزودن ادمین", "staff:add"), ("🔙 پنل ادمین", "adm")]
    return _mk(*rows)


def settings_menu(s: dict[str, str]) -> InlineKeyboardMarkup:
    on = lambda v: "✅ روشن" if v == "1" else "🚫 خاموش"
    return _mk(
        (f"🎁 تست: {on(s['trial_enabled'])}", "set:trial_tgl"),
        (f"⏱️ مدت تست: {s['trial_days']} روز", "set:trial_days"),
        (f"📊 حجم تست: {s['trial_volume_gb']} گیگ", "set:trial_vol"),
        (f"👥 دعوت: {on(s['referral_enabled'])}", "set:ref_tgl"),
        (f"🎁 هدیه دعوت: {s['referral_days']} روز", "set:ref_days"),
        (f"📢 جوین اجباری: {on(s['force_enabled'])}", "set:force_tgl"),
        (f"📢 کانال: {s['force_channel'] or '—'}", "set:force_ch"),
        (f"🔗 لینک جوین: {(s['force_url'] or 'خودکار')[:24]}", "set:force_url"),
        ("🔙 پنل ادمین", "adm"),
        widths=(2, 2, 2, 2, 1),
    )


def wallet_menu() -> InlineKeyboardMarkup:
    return _mk(
        (T("btn_topup"), "w:topup"),
        (T("btn_tx"), "w:tx"),
        (T("btn_back"), "back:main"),
    )


def admin_topups(topups: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"#{t['id']} {t['full_name'] or t['username']} — {t['amount']:,}", f"top:{t['id']}") for t in topups]
    rows.append(("🔙 پنل ادمین", "adm"))
    return _mk(*rows)


def topup_decide(topup_id: int) -> InlineKeyboardMarkup:
    return _mk(
        ("✅ تایید و شارژ", f"top:ok:{topup_id}"),
        ("🧾 مشاهده رسید", f"top:view:{topup_id}"),
        ("❌ رد", f"top:no:{topup_id}"),
        ("🔙 شارژها", "adm:topups"),
        widths=(1, 2, 1),
    )
