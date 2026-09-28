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
"""

DEFAULT_SETTINGS = {
    "card_number": "",      # شماره کارت برای واریز دستی
    "card_holder": "",      # نام صاحب کارت
    "support_text": "برای پشتیبانی از دکمه «🆘 پشتیبانی» یک تیکت ثبت کن.",
}


def init_db(path: str) -> None:
    """ساخت فایل دیتابیس و جداول (اگر نباشند) + تنظیمات پیش‌فرض."""
    global _db_path
    _db_path = path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with _lock, sqlite3.connect(path, timeout=30) as con:
        con.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v))


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
    allowed = {"title", "days", "volume_gb", "price", "active"}
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
                        config_text: str, days: int) -> int:
    t = now()
    return _exec("""INSERT INTO subscriptions(user_id, plan_id, server_name, config_text,
                    starts_at, expires_at) VALUES(?, ?, ?, ?, ?, ?)""",
                 (user_id, plan_id, server_name, config_text, t, t + days * 86400))


def active_subscriptions(user_id: int) -> list[dict]:
    return _all("""SELECT s.*, p.title AS plan_title FROM subscriptions s
                   LEFT JOIN plans p ON p.id=s.plan_id
                   WHERE s.user_id=? AND s.active=1 AND s.expires_at>? ORDER BY s.expires_at""",
                (user_id, now()))


def get_subscription(sub_id: int) -> dict | None:
    return _all("""SELECT s.*, p.title AS plan_title FROM subscriptions s
                   LEFT JOIN plans p ON p.id=s.plan_id WHERE s.id=?""", (sub_id,))[:1] or [None][0]


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
                 receipt_file_id: str = "", receipt_text: str = "") -> int:
    return _exec("""INSERT INTO orders(user_id, plan_id, amount, receipt_file_id, receipt_text, created_at)
                    VALUES(?, ?, ?, ?, ?, ?)""",
                 (user_id, plan_id, amount, receipt_file_id, receipt_text, now()))


def get_order(order_id: int) -> dict | None:
    return _all("""SELECT o.*, p.title AS plan_title, p.days AS plan_days,
                          u.username, u.full_name
                   FROM orders o JOIN plans p ON p.id=o.plan_id
                   LEFT JOIN users u ON u.id=o.user_id WHERE o.id=?""", (order_id,))[:1] or [None][0]


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
    return _all("""SELECT t.*, u.username, u.full_name FROM tickets t
                   LEFT JOIN users u ON u.id=t.user_id WHERE t.id=?""", (ticket_id,))[:1] or [None][0]


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
