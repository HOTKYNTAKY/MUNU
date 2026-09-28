"""کیبوردهای اینلاین کاربر و ادمین."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _mk(*rows: tuple[str, str], widths: tuple[int, ...] = (1,)) -> InlineKeyboardMarkup:
    """ساخت سریع کیبورد از جفت‌های (متن، callback)."""
    b = InlineKeyboardBuilder()
    for text, cb in rows:
        b.button(text=text, callback_data=cb)
    b.adjust(*widths)
    return b.as_markup()


# ---------------------------------------------------------- منوی کاربر
def main_menu() -> InlineKeyboardMarkup:
    return _mk(
        ("🛒 خرید اشتراک", "plans"),
        ("📦 اشتراک‌های من", "mysub"),
        ("🆘 پشتیبانی", "support"),
        ("❓ راهنما", "help"),
    )


def back_main() -> InlineKeyboardMarkup:
    return _mk(("🔙 بازگشت", "back:main"))


def plans_list(plans: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"{p['title']} — {p['price']:,} تومان", f"buy:{p['id']}") for p in plans]
    rows.append(("🔙 بازگشت", "back:main"))
    return _mk(*rows)


def plan_detail(plan_id: int) -> InlineKeyboardMarkup:
    return _mk(
        ("✅ خرید همین پلن", f"pay:{plan_id}"),
        ("🔙 لیست پلن‌ها", "plans"),
    )


def my_subs(subs: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"📦 {(s['plan_title'] or 'اشتراک')} — {s['server_name']}", f"sub:{s['id']}") for s in subs]
    rows.append(("🔙 بازگشت", "back:main"))
    return _mk(*rows)


def sub_detail(sub_id: int) -> InlineKeyboardMarkup:
    return _mk(
        ("📋 دریافت کانفیگ", f"cfg:{sub_id}"),
        ("🔄 تمدید (انتخاب پلن)", "plans"),
        ("🔙 اشتراک‌های من", "mysub"),
    )


def support_menu() -> InlineKeyboardMarkup:
    return _mk(
        ("✍️ ثبت تیکت جدید", "tk:new"),
        ("📨 تیکت‌های من", "tk:my"),
        ("🔙 بازگشت", "back:main"),
    )


def my_tickets(tickets: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"#{t['id']} — {'🟢 باز' if t['status'] == 'open' else '✅ پاسخ داده شد'}", f"tk:{t['id']}") for t in tickets]
    rows.append(("🔙 پشتیبانی", "support"))
    return _mk(*rows)


# ---------------------------------------------------------- پنل ادمین
def admin_menu(n_orders: int = 0, n_tickets: int = 0) -> InlineKeyboardMarkup:
    return _mk(
        ("📊 آمار", "adm:stats"),
        (f"🧾 سفارش‌های در انتظار ({n_orders})", "adm:orders"),
        (f"🎫 تیکت‌های باز ({n_tickets})", "adm:tickets"),
        ("💎 مدیریت پلن‌ها", "adm:plans"),
        ("👥 مدیریت کاربران", "adm:users"),
        ("🖥️ سرورها و کانفیگ‌ها", "adm:srv"),
        ("💳 تنظیمات پرداخت", "adm:pay"),
        ("📣 پیام همگانی", "adm:bc"),
        ("💾 بکاپ فوری", "adm:backup"),
        ("♻️ ریستور از فایل", "adm:restore"),
        widths=(1, 1, 1, 2, 2, 2),
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
        ("🔀 فعال/غیرفعال", f"pl:tgl:{p['id']}"),
        ("🗑️ حذف", f"pl:del:{p['id']}"),
        ("🔙 پلن‌ها", "adm:plans"),
        widths=(2, 2),
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


def admin_users(users: list[dict]) -> InlineKeyboardMarkup:
    rows = [(f"{'🚫' if u['banned'] else '👤'} {u['full_name'] or u['username'] or u['id']}", f"usr:{u['id']}") for u in users]
    rows += [("🔎 جستجوی کاربر", "usr:find"), ("🔙 پنل ادمین", "adm")]
    return _mk(*rows)


def admin_user_detail(u: dict) -> InlineKeyboardMarkup:
    rows = [
        ("➕ افزایش روز اشتراک", f"usr:days:{u['id']}"),
        ("🚫 مسدود" if not u["banned"] else "✅ رفع مسدودیت", f"usr:ban:{u['id']}"),
        ("🔙 کاربران", "adm:users"),
    ]
    return _mk(*rows)


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
    return _mk(("❌ انصراف", "cancel"), widths=(1,))
