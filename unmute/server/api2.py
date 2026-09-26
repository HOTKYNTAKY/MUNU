"""Unmute — REST API part 2 (users, chats, media, admin...)."""
import json
import os
import re

import db
import util
from util import now_ms
from api import (row, rows, exec_sql, user_by_id, settings_of, is_contact, has_blocked,
                 priv_allow,
                 user_pub, att_json, msg_json, chat_members, chat_peer, notify, push_msg,
                 make_session, MEDIA_DIR, _dev_inbox, _lock, DEV)

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


# ---------------- me / settings ----------------
def me(handler, u):
    return handler.j({"ok": True, "user": user_pub(u, u["id"]), "settings": settings_of(u["id"]),
                      "email": u["email"], "verified": bool(u["verified"])})


def patch_me(handler, u, b):
    fields = {}
    if "display_name" in b:
        d = (b["display_name"] or "").strip()[:40]
        if not d:
            return handler.j({"ok": False, "error": "display"}, 400)
        fields["display_name"] = d
    if "bio" in b:
        fields["bio"] = (b["bio"] or "")[:300]
    if "avatar" in b and re.match(r"^.{1,8}#[0-9a-fA-F]{6}$", b["avatar"] or ""):
        fields["avatar"] = b["avatar"]
    if "cover" in b:
        fields["cover"] = (b["cover"] or "")[:40]
    if "avatar_img" in b:
        try:
            aid = int(b["avatar_img"] or 0)
        except (ValueError, TypeError):
            aid = 0
        if aid:
            a = row("SELECT * FROM attachments WHERE id=? AND owner_id=?", (aid, u["id"]))
            if not a or a["kind"] != "image":
                return handler.j({"ok": False, "error": "bad_avatar"}, 400)
            fields["avatar_img"] = aid
        else:
            fields["avatar_img"] = None
    if not fields:
        return handler.j({"ok": False, "error": "nothing"}, 400)
    old_av = u.get("avatar_img")
    sql = "UPDATE users SET " + ",".join("%s=?" % k for k in fields) + " WHERE id=?"
    exec_sql(sql, list(fields.values()) + [u["id"]])
    if "avatar_img" in fields and old_av and old_av != fields["avatar_img"]:
        _delete_attachment(old_av)  # replaced/removed photo: free disk immediately
    nu = user_by_id(u["id"])
    if HUB := handler.hub:
        HUB.send_many(handler.hub.online_ids(), {"t": "presence", "user": user_pub(nu, None)})
    return handler.j({"ok": True, "user": user_pub(nu, u["id"])})


def change_username(handler, u, b):
    uname = (b.get("username") or "").strip()
    if not util.USERNAME_RE.match(uname):
        return handler.j({"ok": False, "error": "username"}, 400)
    if row("SELECT 1 FROM users WHERE username=? AND id!=?", (uname, u["id"])):
        return handler.j({"ok": False, "error": "username_taken"}, 409)
    exec_sql("UPDATE users SET username=? WHERE id=?", (uname, u["id"]))
    return handler.j({"ok": True})


def change_password(handler, u, b):
    if not util.safe_eq(u["pass_hash"], util.pwhash(b.get("old") or "", u["salt"])):
        return handler.j({"ok": False, "error": "bad_old"}, 401)
    if len(b.get("new") or "") < 6:
        return handler.j({"ok": False, "error": "pass_short"}, 400)
    salt = util.new_token(8)
    exec_sql("UPDATE users SET salt=?, pass_hash=? WHERE id=?", (salt, util.pwhash(b["new"], salt), u["id"]))
    exec_sql("DELETE FROM sessions WHERE user_id=? AND token!=?", (u["id"], handler.token))
    return handler.j({"ok": True})


def change_email(handler, u, b):
    email = (b.get("email") or "").strip().lower()
    if not util.EMAIL_RE.match(email):
        return handler.j({"ok": False, "error": "email"}, 400)
    if row("SELECT 1 FROM users WHERE email=? AND id!=?", (email, u["id"])):
        return handler.j({"ok": False, "error": "email_taken"}, 409)
    exec_sql("UPDATE users SET email=?, verified=0 WHERE id=?", (email, u["id"]))
    if DEV:
        code = util.new_token(3)[:6].upper()
        exec_sql("INSERT INTO tokens(token,user_id,kind,expires_at) VALUES(?,?,?,?)", (code, u["id"], "verify", now_ms() + 3600_000))
        with _lock:
            _dev_inbox.append({"to": email, "kind": "verify", "code": code, "at": now_ms()})
    return handler.j({"ok": True})


def verify(handler, u, b):
    code = (b.get("code") or "").strip().upper()
    t = row("SELECT * FROM tokens WHERE token=? AND user_id=? AND kind='verify' AND expires_at>?", (code, u["id"], now_ms()))
    if not t:
        return handler.j({"ok": False, "error": "bad_code"}, 400)
    exec_sql("DELETE FROM tokens WHERE token=?", (code,))
    exec_sql("UPDATE users SET verified=1 WHERE id=?", (u["id"],))
    return handler.j({"ok": True})


def reset(handler, b):
    t = row("SELECT * FROM tokens WHERE token=? AND kind='reset' AND expires_at>?", ((b.get("token") or "").strip(), now_ms()))
    if not t:
        return handler.j({"ok": False, "error": "bad_token"}, 400)
    if len(b.get("password") or "") < 6:
        return handler.j({"ok": False, "error": "pass_short"}, 400)
    salt = util.new_token(8)
    exec_sql("UPDATE users SET salt=?, pass_hash=? WHERE id=?", (salt, util.pwhash(b["password"], salt), t["user_id"]))
    exec_sql("DELETE FROM tokens WHERE token=?", (t["token"],))
    exec_sql("DELETE FROM sessions WHERE user_id=?", (t["user_id"],))
    return handler.j({"ok": True})


def get_settings(handler, u):
    return handler.j({"ok": True, "settings": settings_of(u["id"])})


ALLOWED_SETTINGS = {
    "theme": ["dark", "light", "system"], "accent": None, "font_size": ["sm", "md", "lg"],
    "lang": ["fa", "en"], "notif_msg": bool, "notif_sound": bool, "notif_browser": bool,
    "priv_msg": ["everyone", "contacts", "nobody"], "priv_photo": ["everyone", "contacts", "nobody"],
    "priv_lastseen": ["everyone", "contacts", "nobody"], "priv_online": ["everyone", "contacts", "nobody"],
    "priv_profile": ["everyone", "contacts", "nobody"],
}


def patch_settings(handler, u, b):
    sets = {}
    for k, allow in ALLOWED_SETTINGS.items():
        if k not in b:
            continue
        v = b[k]
        if allow is bool:
            sets[k] = 1 if v in (1, True, "1", "true") else 0
        elif isinstance(allow, list):
            if v in allow:
                sets[k] = v
        else:
            sets[k] = str(v)[:20]
    if not sets:
        return handler.j({"ok": False, "error": "nothing"}, 400)
    sql = "UPDATE settings SET " + ",".join("%s=?" % k for k in sets) + " WHERE user_id=?"
    exec_sql(sql, list(sets.values()) + [u["id"]])
    return handler.j({"ok": True, "settings": settings_of(u["id"])})


def delete_account(handler, u):
    exec_sql("DELETE FROM users WHERE id=?", (u["id"],))
    return handler.j({"ok": True})


def dev_inbox(handler):
    if not DEV:
        return handler.j({"ok": False}, 404)
    with _lock:
        return handler.j({"ok": True, "inbox": _dev_inbox[-20:]})


# ---------------- users / social ----------------
def search_users(handler, u, q):
    term = "%" + (q.get("q", [""])[0] or "").strip() + "%"
    us = rows("SELECT * FROM users WHERE status='active' AND (username LIKE ? OR display_name LIKE ?) AND id!=? ORDER BY username LIMIT 30",
              (term, term, u["id"]))
    return handler.j({"ok": True, "users": [user_pub(x, u["id"]) for x in us]})


def profile(handler, u, username):
    t = row("SELECT * FROM users WHERE username=?", (username,))
    if not t:
        return handler.j({"ok": False, "error": "notfound"}, 404)
    s = settings_of(t["id"])
    if not priv_allow(s["priv_profile"], u["id"], t["id"]):
        return handler.j({"ok": False, "error": "privacy"}, 403)
    pub = user_pub(t, u["id"])
    pub["email"] = None
    chat = row("SELECT c.id FROM chats c JOIN chat_members m1 ON m1.chat_id=c.id JOIN chat_members m2 ON m2.chat_id=c.id WHERE m1.user_id=? AND m2.user_id=?", (u["id"], t["id"]))
    pub["chat_id"] = chat["id"] if chat else None
    return handler.j({"ok": True, "user": pub})


def contact_toggle(handler, u, username, b):
    t = row("SELECT id FROM users WHERE username=?", (username,))
    if not t:
        return handler.j({"ok": False, "error": "notfound"}, 404)
    if b.get("add"):
        exec_sql("INSERT OR IGNORE INTO contacts(owner_id,user_id,created_at) VALUES(?,?,?)", (u["id"], t["id"], now_ms()))
    else:
        exec_sql("DELETE FROM contacts WHERE owner_id=? AND user_id=?", (u["id"], t["id"]))
    return handler.j({"ok": True})


def block_toggle(handler, u, username, b):
    t = row("SELECT id FROM users WHERE username=?", (username,))
    if not t:
        return handler.j({"ok": False, "error": "notfound"}, 404)
    if b.get("block"):
        exec_sql("INSERT OR IGNORE INTO blocked(user_id,blocked_id,created_at) VALUES(?,?,?)", (u["id"], t["id"], now_ms()))
    else:
        exec_sql("DELETE FROM blocked WHERE user_id=? AND blocked_id=?", (u["id"], t["id"]))
    return handler.j({"ok": True})


def report_user(handler, u, username, b):
    t = row("SELECT id FROM users WHERE username=?", (username,))
    if not t:
        return handler.j({"ok": False, "error": "notfound"}, 404)
    reason = (b.get("reason") or "other")
    if reason not in ("spam", "harassment", "fake", "inappropriate", "other"):
        reason = "other"
    exec_sql("INSERT INTO reports(reporter_id,target_id,reason,details,created_at) VALUES(?,?,?,?,?)",
             (u["id"], t["id"], reason, (b.get("details") or "")[:500], now_ms()))
    return handler.j({"ok": True})


def contacts_list(handler, u):
    us = rows("SELECT u.* FROM contacts c JOIN users u ON u.id=c.user_id WHERE c.owner_id=? ORDER BY u.display_name", (u["id"],))
    return handler.j({"ok": True, "users": [user_pub(x, u["id"]) for x in us]})


# ---------------- chats ----------------
def chat_list(handler, u):
    me = u["id"]
    cms = rows("""SELECT cm.*, c.created_at c_created FROM chat_members cm JOIN chats c ON c.id=cm.chat_id
                  WHERE cm.user_id=?""", (me,))
    out = []
    for cm in cms:
        peer = chat_peer(cm["chat_id"], me)
        if not peer:
            continue
        last = row("""SELECT * FROM messages WHERE chat_id=? AND NOT(deleted=1) AND NOT(','||deleted_me||',' LIKE ?)
                      ORDER BY id DESC LIMIT 1""", (cm["chat_id"], "%%,%d,%%" % me))
        unread = row("SELECT COUNT(*) n FROM messages m WHERE m.chat_id=? AND m.sender_id!=? AND m.id>? AND NOT(m.deleted=1)",
                     (cm["chat_id"], me, cm["last_read"]))["n"]
        out.append({
            "id": cm["chat_id"], "peer": user_pub(peer, me),
            "last": msg_json(last, me) if last else None,
            "unread": unread if not cm["muted"] else unread,
            "pinned": bool(cm["pinned"]), "archived": bool(cm["archived"]), "muted": bool(cm["muted"]),
            "updated": last["id"] if last else cm["chat_id"],
        })
    out.sort(key=lambda x: (x["pinned"], x["updated"]), reverse=True)
    return handler.j({"ok": True, "chats": out})


def dm_open(handler, u, b):
    t = row("SELECT * FROM users WHERE username=?", ((b.get("username") or "").strip(),))
    if not t:
        return handler.j({"ok": False, "error": "notfound"}, 404)
    if t["id"] == u["id"]:
        return handler.j({"ok": False, "error": "self"}, 400)
    chat = row("SELECT c.id FROM chats c JOIN chat_members m1 ON m1.chat_id=c.id JOIN chat_members m2 ON m2.chat_id=c.id WHERE m1.user_id=? AND m2.user_id=?", (u["id"], t["id"]))
    if chat:
        exec_sql("UPDATE chat_members SET deleted_at=0, archived=0 WHERE chat_id=? AND user_id=?", (chat["id"], u["id"]))
        return handler.j({"ok": True, "chat_id": chat["id"]})
    cid = exec_sql("INSERT INTO chats(type,created_at) VALUES('dm',?)", (now_ms(),))
    exec_sql("INSERT INTO chat_members(chat_id,user_id) VALUES(?,?)", (cid, u["id"]))
    exec_sql("INSERT INTO chat_members(chat_id,user_id) VALUES(?,?)", (cid, t["id"]))
    return handler.j({"ok": True, "chat_id": cid})


def chat_meta(handler, u, chat_id, b):
    me = u["id"]
    if not row("SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=?", (chat_id, me)):
        return handler.j({"ok": False, "error": "not_member"}, 403)
    sets, vals = [], []
    for k in ("pinned", "archived", "muted"):
        if k in b:
            sets.append("%s=?" % k)
            vals.append(1 if b[k] else 0)
    if "deleted" in b and b["deleted"]:
        sets.append("deleted_at=?")
        vals.append(now_ms())
        sets.append("last_read=(SELECT COALESCE(MAX(id),0) FROM messages WHERE chat_id=?)")
        vals.append(chat_id)
    if sets:
        exec_sql("UPDATE chat_members SET %s WHERE chat_id=? AND user_id=?" % ",".join(sets), vals + [chat_id, me])
    return handler.j({"ok": True})


def sessions_list(handler, u):
    ss = rows("SELECT token, created_at, last_active, expires_at, remember, ua, ip FROM sessions WHERE user_id=? ORDER BY last_active DESC", (u["id"],))
    for s in ss:
        s["current"] = (s["token"] == handler.token)
        s["token"] = s["token"][:10] + "…"
    return handler.j({"ok": True, "sessions": ss})


def sessions_revoke(handler, u, b):
    if b.get("all"):
        exec_sql("DELETE FROM sessions WHERE user_id=? AND token!=?", (u["id"], handler.token))
    elif b.get("prefix"):
        for s in rows("SELECT token FROM sessions WHERE user_id=?", (u["id"],)):
            if s["token"].startswith(b["prefix"][:10]):
                exec_sql("DELETE FROM sessions WHERE token=?", (s["token"],))
    return handler.j({"ok": True})


# ---------------- message ops ----------------
def edit_message(handler, u, mid, b):
    m = row("SELECT * FROM messages WHERE id=?", (mid,))
    if not m or m["sender_id"] != u["id"] or m["deleted"]:
        return handler.j({"ok": False, "error": "not_allowed"}, 403)
    text = (b.get("text") or "").strip()[:4000]
    if not text:
        return handler.j({"ok": False, "error": "empty"}, 400)
    exec_sql("UPDATE messages SET text=?, edited_at=? WHERE id=?", (text, now_ms(), mid))
    m2 = row("SELECT * FROM messages WHERE id=?", (mid,))
    push_msg(m["chat_id"], msg_json(m2, None))
    return handler.j({"ok": True, "msg": msg_json(m2, u["id"])})


def delete_message(handler, u, mid, q):
    scope = (q.get("scope", ["me"])[0])
    m = row("SELECT * FROM messages WHERE id=?", (mid,))
    if not m:
        return handler.j({"ok": False}, 404)
    me = u["id"]
    if scope == "all":
        if m["sender_id"] != me:
            return handler.j({"ok": False, "error": "not_allowed"}, 403)
        exec_sql("UPDATE messages SET deleted=1, text='' WHERE id=?", (mid,))
        push_msg(m["chat_id"], {"t": "deleted_all", "id": mid, "chat_id": m["chat_id"]})
    else:
        dm = (m["deleted_me"] or "").split(",")
        if str(me) not in dm:
            dm.append(str(me))
        exec_sql("UPDATE messages SET deleted_me=? WHERE id=?", (",".join(x for x in dm if x), mid))
        if HUB := handler.hub:
            HUB.send_user(me, {"t": "deleted_me", "id": mid, "chat_id": m["chat_id"]})
    return handler.j({"ok": True})


def react_message(handler, u, mid, b):
    emoji = (b.get("emoji") or "").strip()[:8]
    m = row("SELECT * FROM messages WHERE id=?", (mid,))
    if not m or not emoji:
        return handler.j({"ok": False, "error": "bad"}, 400)
    if not row("SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=?", (m["chat_id"], u["id"])):
        return handler.j({"ok": False, "error": "not_member"}, 403)
    existed = row("SELECT 1 FROM reactions WHERE message_id=? AND user_id=? AND emoji=?", (mid, u["id"], emoji))
    if existed:
        exec_sql("DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?", (mid, u["id"], emoji))
    else:
        exec_sql("INSERT INTO reactions(message_id,user_id,emoji) VALUES(?,?,?)", (mid, u["id"], emoji))
    rts = rows("SELECT emoji, user_id FROM reactions WHERE message_id=?", (mid,))
    rx = {}
    for r in rts:
        rx.setdefault(r["emoji"], []).append(r["user_id"])
    push_msg(m["chat_id"], {"t": "react", "id": mid, "chat_id": m["chat_id"], "reactions": rx})
    return handler.j({"ok": True, "reactions": rx})


def forward_message(handler, u, mid, b):
    m = row("SELECT * FROM messages WHERE id=?", (mid,))
    to = int(b.get("chat_id") or 0)
    if not m or m["deleted"] or not to:
        return handler.j({"ok": False, "error": "bad"}, 400)
    if not row("SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=?", (to, u["id"])):
        return handler.j({"ok": False, "error": "not_member"}, 403)
    new_mid = exec_sql("INSERT INTO messages(chat_id,sender_id,type,text,created_at) VALUES(?,?,?,?,?)",
                       (to, u["id"], m["type"], m["text"] + ("\n↪ fwd" if m["text"] else ""), now_ms()))
    for a in rows("SELECT * FROM attachments WHERE message_id=?", (mid,)):
        # own file copy: independent 24h TTL, original expiry never breaks the forward
        try:
            blob = open(a["path"], "rb").read()
        except Exception:
            continue  # expired/missing media: forward text only
        nid = exec_sql("INSERT INTO attachments(owner_id,message_id,kind,filename,mime,size,path,meta,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (u["id"], new_mid, a["kind"], a["filename"], a["mime"], a["size"], "", a["meta"], now_ms()))
        npath = os.path.join(MEDIA_DIR, "%d_%s" % (nid, a["filename"]))
        try:
            with open(npath, "wb") as fh:
                fh.write(blob)
        except Exception:
            exec_sql("DELETE FROM attachments WHERE id=?", (nid,))
            continue
        exec_sql("UPDATE attachments SET path=?, size=? WHERE id=?", (npath, len(blob), nid))
    for uid in chat_members(to):
        if uid != u["id"]:
            exec_sql("INSERT INTO message_state(message_id,user_id) VALUES(?,?)", (new_mid, uid))
    nm = row("SELECT * FROM messages WHERE id=?", (new_mid,))
    push_msg(to, msg_json(nm, None))
    return handler.j({"ok": True, "id": new_mid})


def pin_message(handler, u, mid, b):
    m = row("SELECT * FROM messages WHERE id=?", (mid,))
    if not m:
        return handler.j({"ok": False}, 404)
    if not row("SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=?", (m["chat_id"], u["id"])):
        return handler.j({"ok": False, "error": "not_member"}, 403)
    if b.get("pin"):
        exec_sql("INSERT OR IGNORE INTO pins(chat_id,message_id,by_id,created_at) VALUES(?,?,?,?)", (m["chat_id"], mid, u["id"], now_ms()))
    else:
        exec_sql("DELETE FROM pins WHERE chat_id=? AND message_id=?", (m["chat_id"], mid))
    pins = rows("SELECT message_id FROM pins WHERE chat_id=?", (m["chat_id"],))
    push_msg(m["chat_id"], {"t": "pin", "chat_id": m["chat_id"], "pins": [p["message_id"] for p in pins]})
    return handler.j({"ok": True})


# ---------------- upload / media ----------------
def _delete_attachment(aid):
    a = row("SELECT * FROM attachments WHERE id=?", (aid,))
    if not a:
        return
    refs = row("SELECT COUNT(*) n FROM attachments WHERE path=? AND id!=?", (a["path"], aid))
    if not refs or not refs["n"]:
        try:
            os.remove(a["path"])
        except Exception:
            pass
    exec_sql("DELETE FROM attachments WHERE id=?", (aid,))


def expire_media():
    """Delete chat media older than UM_MEDIA_TTL hours (default 24).
    Profile photos (referenced by users.avatar_img) are NEVER expired."""
    try:
        ttl_h = int(os.environ.get("UM_MEDIA_TTL", "24"))
    except ValueError:
        ttl_h = 24
    if ttl_h <= 0:
        return 0
    cutoff = now_ms() - ttl_h * 3600_000
    olds = rows("SELECT id FROM attachments WHERE created_at>0 AND created_at<?", (cutoff,))
    n = 0
    for o in olds:
        if row("SELECT 1 FROM users WHERE avatar_img=?", (o["id"],)):
            continue  # a profile photo: keep forever
        _delete_attachment(o["id"])
        n += 1
    return n


def upload(handler, u, files):
    if not files:
        return handler.j({"ok": False, "error": "nofile"}, 400)
    f = files[0]
    name = SAFE_NAME.sub("_", f["filename"] or "file.bin")[:60] or "file.bin"
    if len(f["data"]) > util.MAX_UPLOAD:
        return handler.j({"ok": False, "error": "too_big"}, 413)
    ext = os.path.splitext(name)[1].lower()
    if ext not in util.ALLOWED_EXT and not f["mime"].startswith(("image/", "video/", "audio/")):
        return handler.j({"ok": False, "error": "type"}, 415)
    kind = util.kind_of(name, f["mime"])
    meta = {}
    try:
        extra = json.loads((handler._fields or {}).get("meta", "{}"))
        meta = extra if isinstance(extra, dict) else {}
    except Exception:
        pass
    if meta.get("voice"):
        kind = "voice"
    if meta.get("avatar"):
        if kind != "image":
            return handler.j({"ok": False, "error": "type"}, 415)
        if len(f["data"]) > util.MAX_AVATAR:
            return handler.j({"ok": False, "error": "too_big"}, 413)
    aid = exec_sql("INSERT INTO attachments(owner_id,message_id,kind,filename,mime,size,path,meta,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (u["id"], None, kind, name, f["mime"], len(f["data"]), "", json.dumps(meta, ensure_ascii=False), now_ms()))
    path = os.path.join(MEDIA_DIR, "%d_%s" % (aid, name))
    with open(path, "wb") as fh:
        fh.write(f["data"])
    exec_sql("UPDATE attachments SET path=? WHERE id=?", (path, aid))
    a = row("SELECT * FROM attachments WHERE id=?", (aid,))
    return handler.j({"ok": True, "att": att_json(a)})


def media(handler, u, att_id):
    a = row("SELECT * FROM attachments WHERE id=?", (att_id,))
    if not a:
        return handler.j({"ok": False}, 404)
    ok = a["owner_id"] == u["id"]
    if not ok and a["message_id"]:
        m = row("SELECT chat_id FROM messages WHERE id=?", (a["message_id"],))
        if m and row("SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=?", (m["chat_id"], u["id"])):
            ok = True
    if not ok:
        # profile photo: visible to anyone passing the owner's priv_photo
        trow = row("SELECT id FROM users WHERE avatar_img=?", (att_id,))
        if trow:
            t = user_by_id(trow["id"])
            if t and priv_allow(settings_of(t["id"])["priv_photo"], u["id"], t["id"]):
                ok = True
    if not ok:
        return handler.j({"ok": False}, 403)
    try:
        data = open(a["path"], "rb").read()
    except Exception:
        return handler.j({"ok": False}, 404)
    handler.send_response(200)
    handler.send_header("Content-Type", a["mime"] or "application/octet-stream")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "private, max-age=3600")
    handler.end_headers()
    handler.wfile.write(data)


# ---------------- notifications / search ----------------
def notifications(handler, u):
    ns = rows("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 60", (u["id"],))
    for n in ns:
        n["payload"] = json.loads(n["payload"] or "{}")
    return handler.j({"ok": True, "notifications": ns})


def notifications_read(handler, u):
    exec_sql("UPDATE notifications SET read=1 WHERE user_id=?", (u["id"],))
    return handler.j({"ok": True})


def search_all(handler, u, q):
    term = (q.get("q", [""])[0] or "").strip()
    if not term:
        return handler.j({"ok": True, "users": [], "messages": []})
    like = "%" + term + "%"
    us = rows("SELECT * FROM users WHERE status='active' AND (username LIKE ? OR display_name LIKE ?) AND id!=? LIMIT 15", (like, like, u["id"]))
    ms = rows("""SELECT m.* FROM messages m
                 JOIN chat_members cm ON cm.chat_id=m.chat_id
                 WHERE cm.user_id=? AND m.deleted=0 AND m.text LIKE ?
                   AND NOT(','||m.deleted_me||',' LIKE ?)
                 ORDER BY m.id DESC LIMIT 30""", (u["id"], like, "%%,%d,%%" % u["id"]))
    out_msgs = []
    for m in ms:
        peer = chat_peer(m["chat_id"], u["id"])
        out_msgs.append({"id": m["id"], "chat_id": m["chat_id"], "text": m["text"][:160],
                         "sender": user_pub(user_by_id(m["sender_id"]), u["id"]) if user_by_id(m["sender_id"]) else None,
                         "peer": user_pub(peer, u["id"]) if peer else None, "created_at": m["created_at"]})
    return handler.j({"ok": True, "users": [user_pub(x, u["id"]) for x in us], "messages": out_msgs})


# ---------------- admin ----------------
def admin_guard(u):
    return u["role"] == "admin"


def admin_stats(handler, u):
    users_n = row("SELECT COUNT(*) n FROM users")["n"]
    msgs_n = row("SELECT COUNT(*) n FROM messages")["n"]
    online = len(handler.hub.online_ids()) if handler.hub else 0
    regs_day = row("SELECT COUNT(*) n FROM users WHERE created_at>?", (now_ms() - 86400_000,))["n"]
    series = []
    for d in range(13, -1, -1):
        t0 = now_ms() - (d + 1) * 86400_000
        t1 = now_ms() - d * 86400_000
        r = row("SELECT COUNT(*) n FROM users WHERE created_at>=? AND created_at<?", (t0, t1))
        m = row("SELECT COUNT(*) n FROM messages WHERE created_at>=? AND created_at<?", (t0, t1))
        series.append({"day": d, "regs": r["n"], "msgs": m["n"]})
    return handler.j({"ok": True, "stats": {"users": users_n, "messages": msgs_n, "online": online,
                                            "regs_day": regs_day, "series": series}})


def admin_users(handler, u, q):
    term = "%" + (q.get("q", [""])[0] or "") + "%"
    us = rows("SELECT * FROM users WHERE username LIKE ? OR display_name LIKE ? ORDER BY id DESC LIMIT 60", (term, term))
    return handler.j({"ok": True, "users": [{**user_pub(x, u["id"]), "status": x["status"], "email": x["email"]} for x in us]})


def admin_user_action(handler, u, uid, b):
    act = b.get("act")
    t = user_by_id(int(uid))
    if not t:
        return handler.j({"ok": False}, 404)
    if t["role"] == "admin" and t["id"] != u["id"]:
        return handler.j({"ok": False, "error": "admin"}, 403)
    if act in ("ban", "unban", "suspend"):
        st = {"ban": "banned", "unban": "active", "suspend": "suspended"}[act]
        exec_sql("UPDATE users SET status=? WHERE id=?", (st, t["id"]))
        if st != "active":
            exec_sql("DELETE FROM sessions WHERE user_id=?", (t["id"],))
    elif act == "delete":
        exec_sql("DELETE FROM users WHERE id=?", (t["id"],))
    else:
        return handler.j({"ok": False, "error": "act"}, 400)
    return handler.j({"ok": True})


def admin_reports(handler, u):
    rs = rows("""SELECT r.*, a.username reporter, b.username target FROM reports r
                 JOIN users a ON a.id=r.reporter_id LEFT JOIN users b ON b.id=r.target_id
                 ORDER BY r.id DESC LIMIT 60""")
    return handler.j({"ok": True, "reports": rs})


def admin_report_resolve(handler, u, rid):
    exec_sql("UPDATE reports SET status='resolved' WHERE id=?", (int(rid),))
    return handler.j({"ok": True})


def admin_broadcast(handler, u, b):
    text = (b.get("text") or "").strip()[:500]
    if not text:
        return handler.j({"ok": False, "error": "empty"}, 400)
    ids = [r["id"] for r in rows("SELECT id FROM users")]
    for i in ids:
        notify(i, "system", {"text": text})
    return handler.j({"ok": True, "count": len(ids)})
