"""Unmute — REST API + business logic."""
import json
import os
import re
import threading

import db
import util
from util import now_ms

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")
MEDIA_DIR = os.path.join(db.DATA_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

DEV = os.environ.get("UM_DEV", "0") == "1"
HUB = None  # injected by run.py

_rl_auth = util.RateLimiter(40, 60)
_rl_api = util.RateLimiter(240, 60)
_rl_up = util.RateLimiter(30, 60)
_dev_inbox = []
_lock = threading.Lock()

PAGE = 40


# ---------------- helpers ----------------
def row(sql, args=()):
    c = db.conn()
    r = c.execute(sql, args).fetchone()
    return dict(r) if r else None


def rows(sql, args=()):
    return [dict(r) for r in db.conn().execute(sql, args).fetchall()]


def exec_sql(sql, args=()):
    c = db.conn()
    c.execute(sql, args)
    c.commit()
    return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def user_by_id(uid):
    return row("SELECT * FROM users WHERE id=?", (uid,))


def settings_of(uid):
    s = row("SELECT * FROM settings WHERE user_id=?", (uid,))
    if not s:
        exec_sql("INSERT OR IGNORE INTO settings(user_id) VALUES(?)", (uid,))
        s = row("SELECT * FROM settings WHERE user_id=?", (uid,))
    return s


def is_contact(owner, other):
    return bool(row("SELECT 1 FROM contacts WHERE owner_id=? AND user_id=?", (owner, other)))


def has_blocked(a, b):
    return bool(row("SELECT 1 FROM blocked WHERE user_id=? AND blocked_id=?", (a, b)))


def priv_allow(val, viewer, owner_id):
    if val == "everyone":
        return True
    if val == "nobody":
        return False
    return viewer == owner_id or is_contact(owner_id, viewer)


def avatar_of(u):
    em, col = (u.get("avatar") or "🧑|#1a212c").split("|", 1) if "|" in (u.get("avatar") or "") else ["🧑", "#1a212c"]
    return {"emoji": em, "color": col}


def user_pub(u, viewer=None):
    s = settings_of(u["id"])
    out = {
        "id": u["id"], "username": u["username"], "display_name": u["display_name"],
        "bio": u["bio"], "role": u["role"], "created_at": u["created_at"],
        "avatar": avatar_of(u),
    }
    if viewer and priv_allow(s["priv_photo"], viewer, u["id"]):
        out["cover"] = u.get("cover")
    if u.get("avatar_img") and (not viewer or priv_allow(s["priv_photo"], viewer, u["id"])):
        out["avatar"]["img"] = "/api/media/%d" % u["avatar_img"]
    online = HUB.online_count(u["id"]) > 0 if HUB else False
    if viewer and priv_allow(s["priv_online"], viewer, u["id"]):
        out["online"] = online
    else:
        out["online"] = False
    if viewer and priv_allow(s["priv_lastseen"], viewer, u["id"]):
        out["last_seen"] = u["last_seen"]
    if viewer:
        out["is_contact"] = is_contact(viewer, u["id"])
        out["blocked"] = has_blocked(viewer, u["id"])
    return out


def att_json(a):
    meta = {}
    try:
        meta = json.loads(a["meta"] or "{}")
    except Exception:
        pass
    return {"id": a["id"], "kind": a["kind"], "filename": a["filename"], "mime": a["mime"],
            "size": a["size"], "meta": meta, "url": "/api/media/%d" % a["id"]}


def msg_json(m, viewer, with_state=True):
    out = {
        "id": m["id"], "chat_id": m["chat_id"], "sender_id": m["sender_id"],
        "type": m["type"], "text": m["text"], "reply_to": m["reply_to"],
        "edited": bool(m["edited_at"]), "deleted": bool(m["deleted"]),
        "created_at": m["created_at"],
    }
    out["atts"] = [att_json(a) for a in rows("SELECT * FROM attachments WHERE message_id=?", (m["id"],))]
    rts = rows("SELECT emoji, user_id FROM reactions WHERE message_id=?", (m["id"],))
    rx = {}
    for r in rts:
        rx.setdefault(r["emoji"], []).append(r["user_id"])
    out["reactions"] = rx
    if with_state and m["sender_id"] == viewer:
        # group-aware ticks: delivered/read = ALL other members (same as before for DMs)
        tot = row("SELECT COUNT(*) n FROM chat_members WHERE chat_id=? AND user_id!=?", (m["chat_id"], viewer))
        n = tot["n"] if tot else 0
        if n <= 0:
            out["delivered"] = out["read"] = True
        else:
            st = row("SELECT COALESCE(SUM(delivered_at>0),0) d, COALESCE(SUM(read_at>0),0) r FROM message_state WHERE message_id=? AND user_id!=?", (m["id"], viewer))
            out["delivered"] = bool(st and st["d"] >= n)
            out["read"] = bool(st and st["r"] >= n)
    return out


def chat_members(chat_id):
    return [r["user_id"] for r in rows("SELECT user_id FROM chat_members WHERE chat_id=?", (chat_id,))]


def chat_peer(chat_id, me):
    for uid in chat_members(chat_id):
        if uid != me:
            return user_by_id(uid)
    return None


def notify(uid, kind, payload):
    exec_sql("INSERT INTO notifications(user_id,kind,payload,created_at) VALUES(?,?,?,?)",
             (uid, kind, json.dumps(payload, ensure_ascii=False), now_ms()))
    if HUB:
        HUB.send_user(uid, {"t": "notify", "kind": kind, "payload": payload})


def push_msg(chat_id, mjson, exclude=()):
    if not HUB:
        return
    for uid in chat_members(chat_id):
        if uid in exclude:
            continue
        HUB.send_user(uid, {"t": "msg", "msg": mjson})


# ---------------- auth ----------------
def make_session(uid, remember, ua, ip):
    tok = util.new_token(26)
    now = now_ms()
    exp = now + (30 * 86400_000 if remember else 86400_000)
    exec_sql("INSERT INTO sessions(token,user_id,created_at,last_active,expires_at,remember,ua,ip) VALUES(?,?,?,?,?,?,?,?)",
             (tok, uid, now, now, exp, 1 if remember else 0, (ua or "")[:120], ip))
    return tok


def auth_user(handler):
    h = handler.headers.get("Authorization") or ""
    tok = h[7:] if h.startswith("Bearer ") else ""
    if not tok:
        tok = getattr(handler, "token", "") or ""  # WS ?token= fallback
    s = row("SELECT * FROM sessions WHERE token=?", (tok,))
    if not s or s["expires_at"] < now_ms():
        return None
    u = user_by_id(s["user_id"])
    if not u or u["status"] != "active":
        return None
    if now_ms() - s["last_active"] > 60_000:
        exec_sql("UPDATE sessions SET last_active=? WHERE token=?", (now_ms(), tok))
    return u


def register(handler, b):
    if not _rl_auth.hit(handler.client_address[0]):
        return handler.j({"ok": False, "error": "rate"}, 429)
    uname = (b.get("username") or "").strip()
    dname = (b.get("display_name") or "").strip()[:40]
    pw = b.get("password") or ""
    email = (b.get("email") or "").strip().lower() or None
    if not util.USERNAME_RE.match(uname):
        return handler.j({"ok": False, "error": "username"}, 400)
    if len(pw) < 6:
        return handler.j({"ok": False, "error": "pass_short"}, 400)
    if not dname:
        return handler.j({"ok": False, "error": "display"}, 400)
    if email and not util.EMAIL_RE.match(email):
        return handler.j({"ok": False, "error": "email"}, 400)
    with _lock:
        if row("SELECT 1 FROM users WHERE username=?", (uname,)):
            return handler.j({"ok": False, "error": "username_taken"}, 409)
        if email and row("SELECT 1 FROM users WHERE email=?", (email,)):
            return handler.j({"ok": False, "error": "email_taken"}, 409)
        salt = util.new_token(8)
        first = not row("SELECT 1 FROM users")
        role = "admin" if (first or uname == os.environ.get("UM_ADMIN_USERNAME", "")) else "user"
        av = (b.get("avatar") or "")
        av = av if re.match(r"^.{1,8}#[0-9a-fA-F]{6}$", av) else "🧑|#6d5ef1"
        uid = exec_sql(
            "INSERT INTO users(username,display_name,email,pass_hash,salt,avatar,bio,role,created_at,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (uname, dname, email, util.pwhash(pw, salt), salt, av, (b.get("bio") or "")[:300], role, now_ms(), now_ms()))
        exec_sql("INSERT INTO settings(user_id, lang) VALUES(?, ?)", (uid, b.get("lang") or "fa"))
    if email and DEV:
        code = util.new_token(3)[:6].upper()
        exec_sql("INSERT INTO tokens(token,user_id,kind,expires_at) VALUES(?,?,?,?)", (code, uid, "verify", now_ms() + 3600_000))
        with _lock:
            _dev_inbox.append({"to": email, "kind": "verify", "code": code, "at": now_ms()})
    tok = make_session(uid, bool(b.get("remember")), handler.headers.get("User-Agent"), handler.client_address[0])
    u = user_by_id(uid)
    return handler.j({"ok": True, "token": tok, "user": user_pub(u, uid), "settings": settings_of(uid)})


def login(handler, b):
    ip = handler.client_address[0]
    if not _rl_auth.hit(ip):
        return handler.j({"ok": False, "error": "rate"}, 429)
    uname = (b.get("username") or "").strip()
    u = row("SELECT * FROM users WHERE username=?", (uname,))
    if not u or not util.safe_eq(u["pass_hash"], util.pwhash(b.get("password") or "", u["salt"])):
        return handler.j({"ok": False, "error": "bad_creds"}, 401)
    if u["status"] == "banned":
        return handler.j({"ok": False, "error": "banned"}, 403)
    if u["status"] == "suspended":
        return handler.j({"ok": False, "error": "suspended"}, 403)
    exec_sql("UPDATE users SET last_seen=? WHERE id=?", (now_ms(), u["id"]))
    tok = make_session(u["id"], bool(b.get("remember")), handler.headers.get("User-Agent"), ip)
    return handler.j({"ok": True, "token": tok, "user": user_pub(u, u["id"]), "settings": settings_of(u["id"])})


def forgot(handler, b):
    if not _rl_auth.hit(handler.client_address[0]):
        return handler.j({"ok": False, "error": "rate"}, 429)
    uname = (b.get("username") or "").strip()
    u = row("SELECT * FROM users WHERE username=? OR email=?", (uname, uname.lower()))
    if u and u["email"]:
        code = util.new_token(4)
        exec_sql("INSERT INTO tokens(token,user_id,kind,expires_at) VALUES(?,?,?,?)", (code, u["id"], "reset", now_ms() + 3600_000))
        if DEV:
            with _lock:
                _dev_inbox.append({"to": u["email"], "kind": "reset", "code": code, "at": now_ms()})
    return handler.j({"ok": True, "sent": bool(u and u["email"])})


# ---------------- messages ----------------
def send_message(handler, u, chat_id, b):
    me = u["id"]
    if not row("SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=?", (chat_id, me)):
        return handler.j({"ok": False, "error": "not_member"}, 403)
    ch = row("SELECT * FROM chats WHERE id=?", (chat_id,))
    if not ch:
        return handler.j({"ok": False, "error": "notfound"}, 404)
    if (ch["type"] or "dm") == "dm":
        peer = chat_peer(chat_id, me)
        if peer:
            if has_blocked(me, peer["id"]) or has_blocked(peer["id"], me):
                return handler.j({"ok": False, "error": "blocked"}, 403)
            ps = settings_of(peer["id"])
            if not priv_allow(ps["priv_msg"], me, peer["id"]):
                return handler.j({"ok": False, "error": "privacy"}, 403)
    text = (b.get("text") or "").strip()[:4000]
    att_ids = b.get("atts") or []
    if not text and not att_ids:
        return handler.j({"ok": False, "error": "empty"}, 400)
    kind = "text"
    if att_ids:
        a0 = row("SELECT * FROM attachments WHERE id=?", (att_ids[0],))
        if a0:
            kind = a0["kind"]
    reply = b.get("reply_to")
    mid = exec_sql(
        "INSERT INTO messages(chat_id,sender_id,type,text,reply_to,created_at) VALUES(?,?,?,?,?,?)",
        (chat_id, me, kind, text, reply if isinstance(reply, int) else None, now_ms()))
    for aid in att_ids[:6]:
        exec_sql("UPDATE attachments SET message_id=? WHERE id=? AND owner_id=?", (mid, aid, me))
    for uid in chat_members(chat_id):
        if uid != me:
            exec_sql("INSERT INTO message_state(message_id,user_id) VALUES(?,?)", (mid, uid))
            if not row("SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=? AND muted=1", (chat_id, uid)):
                notify(uid, "message", {"chat_id": chat_id, "from": user_pub(u, uid)["username"], "preview": (text or "📎")[:80]})
    gchat = row("SELECT type, title FROM chats WHERE id=?", (chat_id,))
    if gchat and (gchat["type"] or "dm") == "group" and text:
        for uname in set(re.findall(r"@([A-Za-z0-9_]{1,30})", text)):
            t = row("SELECT id FROM users WHERE username=? AND status='active'", (uname,))
            if t and t["id"] != me and row("SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=?", (chat_id, t["id"])):
                notify(t["id"], "mention", {"chat_id": chat_id, "title": gchat["title"] or "👥",
                                            "by": u["username"], "by_name": u["display_name"], "text": text[:120]})
    m = row("SELECT * FROM messages WHERE id=?", (mid,))
    mj = msg_json(m, me)
    # delivered to online peers
    for uid in chat_members(chat_id):
        if uid != me and HUB and HUB.online_count(uid) > 0:
            exec_sql("UPDATE message_state SET delivered_at=? WHERE message_id=? AND user_id=?", (now_ms(), mid, uid))
    mj["delivered"] = any(HUB.online_count(uid) > 0 for uid in chat_members(chat_id) if uid != me) if HUB else False
    push_msg(chat_id, msg_json(m, None), exclude=())
    return handler.j({"ok": True, "msg": mj})


def fetch_messages(handler, u, chat_id, q):
    me = u["id"]
    if not row("SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=?", (chat_id, me)):
        return handler.j({"ok": False, "error": "not_member"}, 403)
    before = int(q.get("before", ["0"])[0] or 0)
    around = int(q.get("around", ["0"])[0] or 0)
    lim = min(int(q.get("limit", [str(PAGE)])[0] or PAGE), 100)
    if around:
        msgs = rows("SELECT * FROM messages WHERE chat_id=? AND id>=(SELECT id FROM messages WHERE id=?) ORDER BY id ASC LIMIT ?",
                    (chat_id, around, lim))
        older = bool(row("SELECT 1 FROM messages WHERE chat_id=? AND id<?", (chat_id, msgs[0]["id"] if msgs else around)))
    elif before:
        msgs = rows("SELECT * FROM messages WHERE chat_id=? AND id<? ORDER BY id DESC LIMIT ?", (chat_id, before, lim))
        msgs.reverse()
        older = bool(row("SELECT 1 FROM messages WHERE chat_id=? AND id<?", (chat_id, msgs[0]["id"] if msgs else before)))
    else:
        msgs = rows("SELECT * FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?", (chat_id, lim))
        msgs.reverse()
        older = bool(row("SELECT 1 FROM messages WHERE chat_id=? AND id<?", (chat_id, msgs[0]["id"] if msgs else 0)))
    # visibility: deleted-for-me & deleted-for-everyone
    out = []
    for m in msgs:
        if m["deleted"]:
            out.append({"id": m["id"], "deleted_all": True, "created_at": m["created_at"],
                        "sender_id": m["sender_id"], "chat_id": chat_id})
            continue
        if str(me) in (m["deleted_me"] or "").split(","):
            continue
        out.append(msg_json(m, me))
    # mark delivered
    ids = [m["id"] for m in msgs if m["sender_id"] != me]
    if ids:
        c = db.conn()
        for i in ids:
            c.execute("UPDATE message_state SET delivered_at=? WHERE message_id=? AND user_id=? AND delivered_at=0", (now_ms(), i, me))
        c.commit()
    pins = rows("SELECT p.message_id, p.by_id, u.username FROM pins p JOIN users u ON u.id=p.by_id WHERE p.chat_id=? ORDER BY p.created_at", (chat_id,))
    return handler.j({"ok": True, "msgs": out, "older": older, "pins": pins})


def mark_read(handler, u, chat_id, b):
    me = u["id"]
    up_to = int(b.get("last_id") or 0)
    if not up_to:
        r = row("SELECT MAX(id) m FROM messages WHERE chat_id=? AND sender_id!=?", (chat_id, me))
        up_to = r["m"] or 0
    if not up_to:
        return handler.j({"ok": True})
    c = db.conn()
    c.execute("UPDATE message_state SET read_at=?, delivered_at=? WHERE user_id=? AND message_id IN (SELECT id FROM messages WHERE chat_id=? AND sender_id!=? AND id<=?) AND read_at=0",
              (now_ms(), now_ms(), me, chat_id, me, up_to))
    c.execute("UPDATE chat_members SET last_read=? WHERE chat_id=? AND user_id=?", (up_to, chat_id, me))
    c.commit()
    others = [uid for uid in chat_members(chat_id) if uid != me]
    if HUB:
        HUB.send_many(others, {"t": "read", "chat_id": chat_id, "reader": me, "up_to": up_to})
    return handler.j({"ok": True})
