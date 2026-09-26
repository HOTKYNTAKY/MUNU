"""Unmute — database layer (SQLite, stdlib only)."""
import os
import sqlite3
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("UM_DATA", os.path.join(BASE, "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "unmute.db")

_local = threading.local()


def conn():
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.c = c
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL COLLATE NOCASE,
  display_name TEXT NOT NULL,
  email TEXT UNIQUE COLLATE NOCASE,
  pass_hash TEXT NOT NULL, salt TEXT NOT NULL,
  avatar TEXT NOT NULL DEFAULT '🧑🚀|#1a212c',
  avatar_img INTEGER,
  cover TEXT,
  bio TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'user',
  status TEXT NOT NULL DEFAULT 'active',   -- active|banned|suspended
  verified INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  last_seen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL, last_active INTEGER NOT NULL, expires_at INTEGER NOT NULL,
  remember INTEGER NOT NULL DEFAULT 0, ua TEXT, ip TEXT
);
CREATE TABLE IF NOT EXISTS chats(
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL DEFAULT 'dm',
  title TEXT, avatar TEXT NOT NULL DEFAULT '👥|#0ea5e9', owner_id INTEGER,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_members(
  chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member',
  pinned INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
  muted INTEGER NOT NULL DEFAULT 0, deleted_at INTEGER NOT NULL DEFAULT 0,
  last_read INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL DEFAULT 'text',       -- text|image|video|file|audio|voice|system
  text TEXT NOT NULL DEFAULT '',
  reply_to INTEGER, edited_at INTEGER NOT NULL DEFAULT 0,
  deleted INTEGER NOT NULL DEFAULT 0, deleted_me TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS message_state(
  message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL,
  delivered_at INTEGER NOT NULL DEFAULT 0, read_at INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(message_id, user_id)
);
CREATE TABLE IF NOT EXISTS reactions(
  message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL, emoji TEXT NOT NULL,
  PRIMARY KEY(message_id, user_id, emoji)
);
CREATE TABLE IF NOT EXISTS attachments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER NOT NULL, message_id INTEGER,
  kind TEXT NOT NULL, filename TEXT NOT NULL, mime TEXT NOT NULL,
  size INTEGER NOT NULL, path TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pins(
  chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, by_id INTEGER NOT NULL,
  created_at INTEGER NOT NULL, PRIMARY KEY(chat_id, message_id)
);
CREATE TABLE IF NOT EXISTS contacts(
  owner_id INTEGER NOT NULL, user_id INTEGER NOT NULL, created_at INTEGER NOT NULL,
  PRIMARY KEY(owner_id, user_id)
);
CREATE TABLE IF NOT EXISTS blocked(
  user_id INTEGER NOT NULL, blocked_id INTEGER NOT NULL, created_at INTEGER NOT NULL,
  PRIMARY KEY(user_id, blocked_id)
);
CREATE TABLE IF NOT EXISTS reports(
  id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER NOT NULL, target_id INTEGER NOT NULL,
  reason TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
  kind TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
  read INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings(
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  theme TEXT NOT NULL DEFAULT 'system', accent TEXT NOT NULL DEFAULT 'violet',
  font_size TEXT NOT NULL DEFAULT 'md', lang TEXT NOT NULL DEFAULT 'fa',
  notif_msg INTEGER NOT NULL DEFAULT 1, notif_sound INTEGER NOT NULL DEFAULT 1,
  notif_browser INTEGER NOT NULL DEFAULT 0,
  priv_msg TEXT NOT NULL DEFAULT 'everyone', priv_photo TEXT NOT NULL DEFAULT 'everyone',
  priv_lastseen TEXT NOT NULL DEFAULT 'everyone', priv_online TEXT NOT NULL DEFAULT 'everyone',
  priv_profile TEXT NOT NULL DEFAULT 'everyone'
);
CREATE TABLE IF NOT EXISTS tokens(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL, expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages(chat_id, id);
CREATE INDEX IF NOT EXISTS idx_msg_sender ON messages(sender_id);
CREATE INDEX IF NOT EXISTS idx_sess_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, read);
CREATE INDEX IF NOT EXISTS idx_att_msg ON attachments(message_id);
"""


def init():
    c = conn()
    c.executescript(SCHEMA)
    # ---- migrations for existing DBs ----
    acols = [r[1] for r in c.execute("PRAGMA table_info(attachments)").fetchall()]
    if "created_at" not in acols:
        c.execute("ALTER TABLE attachments ADD COLUMN created_at INTEGER NOT NULL DEFAULT 0")
    ucols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    if "avatar_img" not in ucols:
        c.execute("ALTER TABLE users ADD COLUMN avatar_img INTEGER")
    ccols = [r[1] for r in c.execute("PRAGMA table_info(chats)").fetchall()]
    if "title" not in ccols:
        c.execute("ALTER TABLE chats ADD COLUMN title TEXT")
    if "avatar" not in ccols:
        c.execute("ALTER TABLE chats ADD COLUMN avatar TEXT NOT NULL DEFAULT '👥|#0ea5e9'")
    if "owner_id" not in ccols:
        c.execute("ALTER TABLE chats ADD COLUMN owner_id INTEGER")
    mcols = [r[1] for r in c.execute("PRAGMA table_info(chat_members)").fetchall()]
    if "role" not in mcols:
        c.execute("ALTER TABLE chat_members ADD COLUMN role TEXT NOT NULL DEFAULT 'member'")
    import time as _t
    # existing media counts from now (expires TTL after update)
    c.execute("UPDATE attachments SET created_at=? WHERE created_at=0", (int(_t.time() * 1000),))
    c.commit()
