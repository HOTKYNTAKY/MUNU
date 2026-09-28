"""لایه دیتابیس SQLite — همه داده‌ها فقط روی همین سرور ذخیره می‌شود.

نکته طراحی: هر تابع برای خودش یک کانکشن کوتاه‌مدت باز می‌کند تا
جایگزینی فایل دیتابیس هنگام ریستور بدون ریستارت ربات ممکن باشد.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time

_lock = threading.Lock()
_db_path: str | None = None


def now() -> int:
    """زمان فعلی (epoch ثانیه)."""
    return int(time.time())


# ---------------------------------------------------------------- ساختار جداول
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id         INTEGER PRIMARY KEY,          -- آیدی تلگرام کاربر
  username   TEXT,
  full_name  TEXT,
  banned     INTEGER NOT NULL DEFAULT 0,   -- 1 = مسدود
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS plans(
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  title     TEXT NOT NULL,                 -- مثلا «ماهانه ۳۰ گیگ»
  days      INTEGER NOT NULL,              -- مدت به روز
  volume_gb REAL NOT NULL DEFAULT 0,       -- حجم به گیگ (۰ = نامحدود)
  price     INTEGER NOT NULL,              -- قیمت به تومان
  active    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS servers(
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  name     TEXT NOT NULL,                  -- مثلا «آلمان 🇩🇪»
  template TEXT NOT NULL DEFAULT '',       -- قالب کانفیگ با {UUID} و {EMAIL} (اختیاری)
  active   INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS vpn_configs(
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id   INTEGER NOT NULL REFERENCES servers(id),
  config_text TEXT NOT NULL,               -- کانفیگ آماده (vmess://... / vless://...)
  assigned_to INTEGER,                     -- آیدی کاربر (NULL = آزاد)
  assigned_at INTEGER
);
CREATE TABLE IF NOT EXISTS subscriptions(
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL,
  plan_id     INTEGER,
  server_name TEXT NOT NULL DEFAULT '',
  config_text TEXT NOT NULL DEFAULT '',
  starts_at   INTEGER NOT NULL,
  expires_at  INTEGER NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders(
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL,
  plan_id        INTEGER NOT NULL,
  amount         INTEGER NOT NULL,          -- مبلغ به تومان
  receipt_file_id TEXT,                    -- فایل رسید (عکس)
  receipt_text   TEXT,                     -- رسید متنی (شماره پیگیری...)
  status         TEXT NOT NULL DEFAULT 'pending',  -- pending/approved/rejected
  created_at     INTEGER NOT NULL,
  decided_at     INTEGER
);
CREATE TABLE IF NOT EXISTS tickets(
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL,
  text        TEXT NOT NULL,
  answer      TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'open',  -- open/answered/closed
  created_at  INTEGER NOT NULL,
  answered_at INTEGER
);
CREATE TABLE IF NOT EXISTS settings(
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS texts(
  key   TEXT PRIMARY KEY,   -- کلید متن (مثلا btn_buy)
  value TEXT NOT NULL       -- متن قابل ویرایش (پشتیبانی از {e:emoji})
);
CREATE TABLE IF NOT EXISTS menu_buttons(
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  text   TEXT NOT NULL,     -- متن دکمه شیشه‌ای
  url    TEXT NOT NULL,     -- لینک (https://... یا tg://...)
  pos    INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS premium_emoji(
  name     TEXT PRIMARY KEY,  -- نام کوتاه (مثلا fire)
  emoji_id TEXT NOT NULL      -- custom_emoji_id تلگرام
);
CREATE TABLE IF NOT EXISTS discount_codes(
  code       TEXT PRIMARY KEY,
  percent    INTEGER NOT NULL,          -- درصد تخفیف 1..100
  max_uses   INTEGER NOT NULL DEFAULT 0, -- سقف استفاده (۰ = نامحدود)
  used       INTEGER NOT NULL DEFAULT 0,
  active     INTEGER NOT NULL DEFAULT 1,
  expires_at INTEGER NOT NULL DEFAULT 0  -- ۰ = بدون انقضا
);
CREATE TABLE IF NOT EXISTS panels(
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  name     TEXT NOT NULL,     -- مثلا «پاسارگارد آلمان»
  base_url TEXT NOT NULL,     -- مثلا https://panel.example.com:8000
  api_key  TEXT NOT NULL DEFAULT '',  -- کلید pg_key_... (اولویت با این است)
  username TEXT NOT NULL DEFAULT '',
  password TEXT NOT NULL DEFAULT '',
  group_ids TEXT NOT NULL DEFAULT '', -- آیدی گروه‌ها با کاما (اختیاری)
  active   INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS admins(
  user_id INTEGER PRIMARY KEY  -- ادمین‌های کمکی (علاوه بر مالک)
);
CREATE TABLE IF NOT EXISTS topups(
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL,
  amount         INTEGER NOT NULL,          -- مبلغ به تومان
  receipt_file_id TEXT,                    -- فایل رسید (عکس)
  receipt_text   TEXT,                     -- رسید متنی
  status         TEXT NOT NULL DEFAULT 'pending',  -- pending/approved/rejected
  created_at     INTEGER NOT NULL,
  decided_at     INTEGER
);
CREATE TABLE IF NOT EXISTS wallet_tx(
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id       INTEGER NOT NULL,
  kind          TEXT NOT NULL,             -- topup/purchase/refund/adjust
  amount        INTEGER NOT NULL,          -- مثبت/منفی
  balance_after INTEGER NOT NULL,          -- موجودی بعد از تراکنش
  note          TEXT NOT NULL DEFAULT '',
  created_at    INTEGER NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "card_number": "",      # شماره کارت برای واریز دستی
    "card_holder": "",      # نام صاحب کارت
    "support_text": "برای پشتیبانی از دکمه «🆘 پشتیبانی» یک تیکت ثبت کن.",
    "trial_enabled": "1",   # پلن تست روشن/خاموش
    "trial_days": "1",      # مدت تست به روز
    "trial_volume_gb": "5", # حجم تست به گیگ
    "referral_enabled": "1",
    "referral_days": "3",   # هدیه دعوت‌کننده به روز
    "force_enabled": "0",   # جوین اجباری
    "force_channel": "",    # آیدی/یوزرنیم کانال برای چک عضویت
    "force_url": "",        # لینک عضویت
}


def init_db(path: str) -> None:
    """ساخت فایل دیتابیس و جداول (اگر نباشند) + تنظیمات پیش‌فرض."""
    global _db_path
    _db_path = path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with _lock, sqlite3.connect(path, timeout=30) as con:
        con.executescript(SCHEMA)
        _migrate(con)
        for k, v in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v))


def _migrate(con: sqlite3.Connection) -> None:
    """افزودن ستون‌های نسخه‌های جدید به دیتابیس‌های قدیمی."""
    def cols(table: str) -> set:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}

    def ensure(table: str, column: str, ddl: str) -> None:
        if column not in cols(table):
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    ensure("users", "trial_used", "INTEGER NOT NULL DEFAULT 0")
    ensure("users", "referred_by", "INTEGER NOT NULL DEFAULT 0")
    ensure("users", "bonus_days", "INTEGER NOT NULL DEFAULT 0")
    ensure("users", "balance", "INTEGER NOT NULL DEFAULT 0")
    ensure("plans", "panel_id", "INTEGER NOT NULL DEFAULT 0")
    ensure("subscriptions", "panel_id", "INTEGER NOT NULL DEFAULT 0")
    ensure("subscriptions", "panel_username", "TEXT NOT NULL DEFAULT ''")
    ensure("subscriptions", "sub_link", "TEXT NOT NULL DEFAULT ''")
    ensure("orders", "code", "TEXT NOT NULL DEFAULT ''")


def _connect() -> sqlite3.Connection:
    assert _db_path, "init_db() first"
    con = sqlite3.connect(_db_path, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _one(sql: str, args: tuple = ()) -> dict | None:
    with _lock, _connect() as con:
        r = con.execute(sql, args).fetchone()
        return dict(r) if r else None


def _all(sql: str, args: tuple = ()) -> list[dict]:
    with _lock, _connect() as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def _exec(sql: str, args: tuple = ()) -> int:
    """اجرا + برگرداندن lastrowid."""
    with _lock, _connect() as con:
        cur = con.execute(sql, args)
        con.commit()
        return cur.lastrowid or 0


# ---------------------------------------------------------------- کاربران
def add_or_update_user(user_id: int, username: str, full_name: str) -> None:
    _exec("""INSERT INTO users(id, username, full_name, created_at) VALUES(?, ?, ?, ?)
             ON CONFLICT(id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name""",
          (user_id, username or "", full_name or "", now()))


def get_user(user_id: int) -> dict | None:
    return _one("SELECT * FROM users WHERE id=?", (user_id,))


def find_user_by_name(username: str) -> dict | None:
    return _one("SELECT * FROM users WHERE username=?", (username.lstrip("@"),))


def list_users(limit: int = 15) -> list[dict]:
    return _all("SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (limit,))


def count_users() -> int:
    return _one("SELECT COUNT(*) n FROM users")["n"]


def set_banned(user_id: int, banned: bool) -> None:
    _exec("UPDATE users SET banned=? WHERE id=?", (1 if banned else 0, user_id))


def is_banned(user_id: int) -> bool:
    u = get_user(user_id)
    return bool(u and u["banned"])


def broadcast_targets() -> list[int]:
    """آیدی همه کاربران غیرمسدود (برای پیام همگانی)."""
    return [r["id"] for r in _all("SELECT id FROM users WHERE banned=0")]


# ---------------------------------------------------------------- پلن‌ها
def add_plan(title: str, days: int, volume_gb: float, price: int) -> int:
    return _exec("INSERT INTO plans(title, days, volume_gb, price) VALUES(?, ?, ?, ?)",
                 (title, days, volume_gb, price))


def list_plans(active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM plans" + (" WHERE active=1" if active_only else "") + " ORDER BY price"
    return _all(sql)


def get_plan(plan_id: int) -> dict | None:
    return _one("SELECT * FROM plans WHERE id=?", (plan_id,))


def update_plan(plan_id: int, **fields) -> None:
    allowed = {"title", "days", "volume_gb", "price", "active", "panel_id"}
    sets = ", ".join(f"{k}=?" for k in fields if k in allowed)
    if sets:
        _exec(f"UPDATE plans SET {sets} WHERE id=?",
              tuple(fields[k] for k in fields if k in allowed) + (plan_id,))


def delete_plan(plan_id: int) -> None:
    _exec("DELETE FROM plans WHERE id=?", (plan_id,))


# ---------------------------------------------------------------- سرورها و کانفیگ‌ها
def add_server(name: str, template: str = "") -> int:
    return _exec("INSERT INTO servers(name, template) VALUES(?, ?)", (name, template))


def list_servers() -> list[dict]:
    rows = _all("SELECT * FROM servers ORDER BY id")
    for r in rows:  # تعداد کانفیگ آزاد هر سرور
        r["free"] = _one("SELECT COUNT(*) n FROM vpn_configs WHERE server_id=? AND assigned_to IS NULL",
                         (r["id"],))["n"]
    return rows


def get_server(server_id: int) -> dict | None:
    return _one("SELECT * FROM servers WHERE id=?", (server_id,))


def update_server(server_id: int, **fields) -> None:
    allowed = {"name", "template", "active"}
    sets = ", ".join(f"{k}=?" for k in fields if k in allowed)
    if sets:
        _exec(f"UPDATE servers SET {sets} WHERE id=?",
              tuple(fields[k] for k in fields if k in allowed) + (server_id,))


def delete_server(server_id: int) -> None:
    _exec("DELETE FROM vpn_configs WHERE server_id=?", (server_id,))
    _exec("DELETE FROM servers WHERE id=?", (server_id,))


def add_config(server_id: int, config_text: str) -> int:
    return _exec("INSERT INTO vpn_configs(server_id, config_text) VALUES(?, ?)",
                 (server_id, config_text.strip()))


def get_free_config() -> dict | None:
    """قدیمی‌ترین کانفیگ آزاد از بین سرورهای فعال."""
    return _one("""SELECT v.*, s.name AS server_name FROM vpn_configs v
                   JOIN servers s ON s.id=v.server_id
                   WHERE v.assigned_to IS NULL AND s.active=1
                   ORDER BY v.id LIMIT 1""")


def assign_config(cfg_id: int, user_id: int) -> None:
    _exec("UPDATE vpn_configs SET assigned_to=?, assigned_at=? WHERE id=?",
          (user_id, now(), cfg_id))


def template_server() -> dict | None:
    """اولین سرور فعال که قالب ساخت کانفیگ دارد."""
    return _one("SELECT * FROM servers WHERE active=1 AND template<>'' ORDER BY id LIMIT 1")


# ---------------------------------------------------------------- اشتراک‌ها
def create_subscription(user_id: int, plan_id: int, server_name: str,
                        config_text: str, days: int, panel_id: int = 0,
                        panel_username: str = "", sub_link: str = "") -> int:
    t = now()
    return _exec("""INSERT INTO subscriptions(user_id, plan_id, server_name, config_text,
                    starts_at, expires_at, panel_id, panel_username, sub_link)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (user_id, plan_id, server_name, config_text, t, t + days * 86400,
                  panel_id, panel_username, sub_link))


def active_subscriptions(user_id: int) -> list[dict]:
    return _all("""SELECT s.*, p.title AS plan_title FROM subscriptions s
                   LEFT JOIN plans p ON p.id=s.plan_id
                   WHERE s.user_id=? AND s.active=1 AND s.expires_at>? ORDER BY s.expires_at""",
                (user_id, now()))


def get_subscription(sub_id: int) -> dict | None:
    return _one("""SELECT s.*, p.title AS plan_title FROM subscriptions s
                   LEFT JOIN plans p ON p.id=s.plan_id WHERE s.id=?""", (sub_id,))


def extend_subscription(sub_id: int, days: int) -> None:
    _exec("UPDATE subscriptions SET expires_at=expires_at+?, active=1 WHERE id=?",
          (days * 86400, sub_id))


def count_active_subs() -> int:
    return _one("SELECT COUNT(*) n FROM subscriptions WHERE active=1 AND expires_at>?", (now(),))["n"]


def expiring_soon(hours: int = 24) -> list[dict]:
    """اشتراک‌های فعالی که تا N ساعت آینده منقضی می‌شوند (برای یادآوری)."""
    t = now()
    return _all("SELECT * FROM subscriptions WHERE active=1 AND expires_at>? AND expires_at<=?",
                (t, t + hours * 3600))


def deactivate_expired() -> list[dict]:
    """غیرفعال کردن اشتراک‌های منقضی‌شده + برگرداندن لیستشان (برای اطلاع‌رسانی)."""
    rows = _all("SELECT * FROM subscriptions WHERE active=1 AND expires_at<=?", (now(),))
    if rows:
        _exec("UPDATE subscriptions SET active=0 WHERE active=1 AND expires_at<=?", (now(),))
    return rows


# ---------------------------------------------------------------- سفارش‌ها
def create_order(user_id: int, plan_id: int, amount: int,
                 receipt_file_id: str = "", receipt_text: str = "", code: str = "") -> int:
    return _exec("""INSERT INTO orders(user_id, plan_id, amount, receipt_file_id, receipt_text, code, created_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?)""",
                 (user_id, plan_id, amount, receipt_file_id, receipt_text, code, now()))


def get_order(order_id: int) -> dict | None:
    return _one("""SELECT o.*, p.title AS plan_title, p.days AS plan_days,
                          u.username, u.full_name
                   FROM orders o JOIN plans p ON p.id=o.plan_id
                   LEFT JOIN users u ON u.id=o.user_id WHERE o.id=?""", (order_id,))


def list_pending_orders() -> list[dict]:
    return _all("""SELECT o.*, p.title AS plan_title, u.username, u.full_name
                   FROM orders o JOIN plans p ON p.id=o.plan_id
                   LEFT JOIN users u ON u.id=o.user_id
                   WHERE o.status='pending' ORDER BY o.id""")


def set_order_status(order_id: int, status: str) -> None:
    _exec("UPDATE orders SET status=?, decided_at=? WHERE id=?", (status, now(), order_id))


def revenue_total(since: int = 0) -> int:
    r = _one("SELECT COALESCE(SUM(amount),0) s FROM orders WHERE status='approved' AND created_at>?", (since,))
    return r["s"]


# ---------------------------------------------------------------- تیکت‌ها
def create_ticket(user_id: int, text: str) -> int:
    return _exec("INSERT INTO tickets(user_id, text, created_at) VALUES(?, ?, ?)",
                 (user_id, text, now()))


def get_ticket(ticket_id: int) -> dict | None:
    return _one("""SELECT t.*, u.username, u.full_name FROM tickets t
                   LEFT JOIN users u ON u.id=t.user_id WHERE t.id=?""", (ticket_id,))


def list_open_tickets() -> list[dict]:
    return _all("""SELECT t.*, u.username, u.full_name FROM tickets t
                   LEFT JOIN users u ON u.id=t.user_id
                   WHERE t.status='open' ORDER BY t.id""")


def list_user_tickets(user_id: int) -> list[dict]:
    return _all("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,))


def answer_ticket(ticket_id: int, answer: str) -> None:
    _exec("UPDATE tickets SET answer=?, status='answered', answered_at=? WHERE id=?",
          (answer, now(), ticket_id))


def close_ticket(ticket_id: int) -> None:
    _exec("UPDATE tickets SET status='closed' WHERE id=?", (ticket_id,))


def count_open_tickets() -> int:
    return _one("SELECT COUNT(*) n FROM tickets WHERE status='open'")["n"]


# ---------------------------------------------------------------- تنظیمات
def get_setting(key: str) -> str:
    r = _one("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else ""


def set_setting(key: str, value: str) -> None:
    _exec("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
          (key, value))


# ---------------------------------------------------------------- متن‌های قابل ویرایش
def get_text(key: str) -> str | None:
    r = _one("SELECT value FROM texts WHERE key=?", (key,))
    return r["value"] if r else None


def set_text(key: str, value: str) -> None:
    _exec("INSERT INTO texts(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
          (key, value))


def all_texts() -> dict:
    return {r["key"]: r["value"] for r in _all("SELECT key, value FROM texts")}


# ---------------------------------------------------------------- دکمه‌های شیشه‌ای منو
def add_menu_button(text: str, url: str) -> int:
    mx = _one("SELECT COALESCE(MAX(pos),0) m FROM menu_buttons")["m"]
    return _exec("INSERT INTO menu_buttons(text, url, pos) VALUES(?, ?, ?)", (text, url, mx + 1))


def list_menu_buttons(active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM menu_buttons" + (" WHERE active=1" if active_only else "") + " ORDER BY pos, id"
    return _all(sql)


def get_menu_button(bid: int) -> dict | None:
    return _one("SELECT * FROM menu_buttons WHERE id=?", (bid,))


def toggle_menu_button(bid: int) -> None:
    _exec("UPDATE menu_buttons SET active=1-active WHERE id=?", (bid,))


def delete_menu_button(bid: int) -> None:
    _exec("DELETE FROM menu_buttons WHERE id=?", (bid,))


# ---------------------------------------------------------------- ایموجی پریمیوم
def add_emoji(name: str, emoji_id: str) -> None:
    _exec("INSERT INTO premium_emoji(name, emoji_id) VALUES(?, ?) ON CONFLICT(name) DO UPDATE SET emoji_id=excluded.emoji_id",
          (name.strip().lower(), emoji_id))


def list_emoji() -> list[dict]:
    return _all("SELECT * FROM premium_emoji ORDER BY name")


def get_emoji(name: str) -> str | None:
    r = _one("SELECT emoji_id FROM premium_emoji WHERE name=?", (name.strip().lower(),))
    return r["emoji_id"] if r else None


def delete_emoji(name: str) -> None:
    _exec("DELETE FROM premium_emoji WHERE name=?", (name,))


# ---------------------------------------------------------------- کد تخفیف
def add_discount(code: str, percent: int, max_uses: int = 0, expires_at: int = 0) -> None:
    _exec("INSERT INTO discount_codes(code, percent, max_uses, expires_at) VALUES(?, ?, ?, ?) "
          "ON CONFLICT(code) DO UPDATE SET percent=excluded.percent, max_uses=excluded.max_uses, "
          "expires_at=excluded.expires_at, active=1",
          (code.strip().upper(), percent, max_uses, expires_at))


def list_discounts() -> list[dict]:
    return _all("SELECT * FROM discount_codes ORDER BY code")


def get_discount(code: str) -> dict | None:
    return _one("SELECT * FROM discount_codes WHERE code=?", (code.strip().upper(),))


def delete_discount(code: str) -> None:
    _exec("DELETE FROM discount_codes WHERE code=?", (code,))


def toggle_discount(code: str) -> None:
    _exec("UPDATE discount_codes SET active=1-active WHERE code=?", (code,))


def use_discount(code: str) -> None:
    _exec("UPDATE discount_codes SET used=used+1 WHERE code=?", (code,))


def valid_discount(code: str) -> dict | None:
    """کد معتبر و قابل استفاده؟ (فعال + منقضی‌نشده + ظرفیت باقی‌مانده)"""
    d = get_discount(code)
    if not d or not d["active"]:
        return None
    if d["expires_at"] and d["expires_at"] <= now():
        return None
    if d["max_uses"] and d["used"] >= d["max_uses"]:
        return None
    return d


# ---------------------------------------------------------------- پنل‌های پاسارگارد
def add_panel(name: str, base_url: str, api_key: str = "", username: str = "",
              password: str = "", group_ids: str = "") -> int:
    return _exec("INSERT INTO panels(name, base_url, api_key, username, password, group_ids) "
                 "VALUES(?, ?, ?, ?, ?, ?)",
                 (name, base_url.rstrip("/"), api_key, username, password, group_ids))


def list_panels() -> list[dict]:
    return _all("SELECT * FROM panels ORDER BY id")


def get_panel(panel_id: int) -> dict | None:
    return _one("SELECT * FROM panels WHERE id=?", (panel_id,))


def update_panel(panel_id: int, **fields) -> None:
    allowed = {"name", "base_url", "api_key", "username", "password", "group_ids", "active"}
    sets = ", ".join(f"{k}=?" for k in fields if k in allowed)
    if sets:
        _exec(f"UPDATE panels SET {sets} WHERE id=?",
              tuple(fields[k] for k in fields if k in allowed) + (panel_id,))


def delete_panel(panel_id: int) -> None:
    _exec("DELETE FROM panels WHERE id=?", (panel_id,))


# ---------------------------------------------------------------- ادمین‌های کمکی
def add_admin(user_id: int) -> None:
    _exec("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (user_id,))


def remove_admin(user_id: int) -> None:
    _exec("DELETE FROM admins WHERE user_id=?", (user_id,))


def list_admins() -> list[int]:
    return [r["user_id"] for r in _all("SELECT user_id FROM admins ORDER BY user_id")]


def is_extra_admin(user_id: int) -> bool:
    return _one("SELECT 1 FROM admins WHERE user_id=?", (user_id,)) is not None


# ---------------------------------------------------------------- تست و دعوت
def set_trial_used(user_id: int) -> None:
    _exec("UPDATE users SET trial_used=1 WHERE id=?", (user_id,))


def set_referred(user_id: int, by_id: int) -> None:
    _exec("UPDATE users SET referred_by=? WHERE id=? AND referred_by=0", (by_id, user_id))


def count_referrals(user_id: int) -> int:
    return _one("SELECT COUNT(*) n FROM users WHERE referred_by=?", (user_id,))["n"]


def has_approved_order(user_id: int) -> bool:
    return _one("SELECT 1 FROM orders WHERE user_id=? AND status='approved'", (user_id,)) is not None


def add_bonus_days(user_id: int, days: int) -> None:
    _exec("UPDATE users SET bonus_days=bonus_days+? WHERE id=?", (days, user_id))


def take_bonus_days(user_id: int) -> int:
    u = get_user(user_id)
    b = (u or {}).get("bonus_days", 0) or 0
    if b:
        _exec("UPDATE users SET bonus_days=0 WHERE id=?", (user_id,))
    return b


def first_active_panel() -> dict | None:
    ps = [p for p in list_panels() if p["active"]]
    return ps[0] if ps else None


def get_balance(user_id: int) -> int:
    u = get_user(user_id)
    return (u or {}).get("balance", 0) or 0


def add_balance(user_id: int, delta: int, kind: str, note: str = "") -> int:
    """تغییر موجودی + ثبت در دفتر. برمی‌گرداند: موجودی جدید."""
    bal = get_balance(user_id) + delta
    _exec("UPDATE users SET balance=? WHERE id=?", (bal, user_id))
    _exec("INSERT INTO wallet_tx(user_id, kind, amount, balance_after, note, created_at)"
          " VALUES(?, ?, ?, ?, ?, ?)",
          (user_id, kind, delta, bal, note[:200], now()))
    return bal


def list_wallet_tx(user_id: int, limit: int = 10) -> list[dict]:
    return _all("SELECT * FROM wallet_tx WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit))


def wallet_income() -> int:
    r = _one("SELECT COALESCE(SUM(amount),0) s FROM wallet_tx WHERE kind='topup'")
    return r["s"] if r else 0


def create_topup(user_id: int, amount: int, receipt_file_id: str = "",
                 receipt_text: str = "") -> int:
    return _exec("INSERT INTO topups(user_id, amount, receipt_file_id, receipt_text, created_at)"
                 " VALUES(?, ?, ?, ?, ?)",
                 (user_id, amount, receipt_file_id, receipt_text, now()))


def get_topup(topup_id: int) -> dict | None:
    return _one("""SELECT t.*, u.username, u.full_name FROM topups t
                   LEFT JOIN users u ON u.id=t.user_id WHERE t.id=?""",
                (topup_id,))


def list_pending_topups() -> list[dict]:
    return _all("""SELECT t.*, u.username, u.full_name FROM topups t
                   LEFT JOIN users u ON u.id=t.user_id
                   WHERE t.status='pending' ORDER BY t.id""")


def count_pending_topups() -> int:
    r = _one("SELECT COUNT(*) n FROM topups WHERE status='pending'")
    return r["n"] if r else 0


def set_topup_status(topup_id: int, status: str) -> None:
    _exec("UPDATE topups SET status=?, decided_at=? WHERE id=?",
          (status, now(), topup_id))
