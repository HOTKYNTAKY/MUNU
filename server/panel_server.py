#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
پنل گارد جاویدان — سرور سبک (فقط کتابخانه استاندارد پایتون)
- احراز هویت چندکاربره (هش pbkdf2 + توکن سشن)
- پروکسی ارسال به تلگرام (توکن فقط سمت سرور)
- سرو استاتیک پنل (index.html / assets / menu.html)
پورت: متغیر محیطی PORT یا آرگومان اول، پیش‌فرض 8787
"""
import json, os, re, sys, secrets, hashlib, base64, threading, urllib.request, uuid, time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else "8787"))

CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
TG  = "https://api.telegram.org/bot" + CFG["token"]
CHAT = str(CFG["chat"])

USERS_F  = os.path.join(BASE, "users.json")
SESS_F   = os.path.join(BASE, "sessions.json")
LOGS_F   = os.path.join(BASE, "logs.json")
MSGS_F   = os.path.join(BASE, "msgs.json")

_lock = threading.Lock()
USERS  = {}
SESS   = {}
LOGS   = {}
MSGS   = []
FAIL   = {}

def _load():
    global USERS, SESS, LOGS, MSGS
    def rd(p, d):
        try:
            with open(p, encoding="utf-8") as f: return json.load(f)
        except Exception:
            return d
    USERS = rd(USERS_F, {}); SESS = rd(SESS_F, {}); LOGS = rd(LOGS_F, {}); MSGS = rd(MSGS_F, [])

def _save_users():
    with open(USERS_F, "w", encoding="utf-8") as f: json.dump(USERS, f, ensure_ascii=False)
def _save_sess():
    with open(SESS_F, "w", encoding="utf-8") as f: json.dump(SESS, f)
def _save_logs():
    with open(LOGS_F, "w", encoding="utf-8") as f: json.dump(LOGS, f, ensure_ascii=False)
def _save_msgs():
    with open(MSGS_F, "w", encoding="utf-8") as f: json.dump(MSGS, f, ensure_ascii=False)

def admin_name():
    a = CFG.get("admin")
    if a and a in USERS: return a
    for n, u in USERS.items():
        if u.get("role") == "admin": return n
    return None

def is_admin(u):
    return u == admin_name()

def pwhash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120000).hex()

NAME_RE = re.compile(r"^[\w\u0600-\u06FF][\w\u0600-\u06FF .\-]{2,19}$")

def tg(method, fields, file_bytes=None, file_field=None, filename="upload.bin"):
    boundary = "----gard" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode())
    if file_bytes is not None:
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: application/octet-stream\r\n\r\n" % (boundary, file_field, filename)).encode() + file_bytes + b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode())
    req = urllib.request.Request(TG + "/" + method, data=b"".join(parts),
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)

ALLOWED_STATIC = {"/", "/index.html", "/menu.html"}

class H(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    def log_message(self, fmt, *args):
        pass

    # ---------- کمکی ----------
    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 40 * 1024 * 1024:
            raise ValueError("payload too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw)

    def _user(self):
        auth = self.headers.get("Authorization", "")
        tok = auth[7:] if auth.startswith("Bearer ") else ""
        with _lock:
            s = SESS.get(tok)
            if not s: return None
            u = USERS.get(s["user"])
            if u:
                u["last"] = int(time.time() * 1000)
                _save_users()
            return s["user"]

    # ---------- استاتیک (فقط سفیدلیست) ----------
    def do_GET(self):
        p = self.path.split("?")[0]
        if p.startswith("/api/"):
            if p == "/api/health":
                return self._json({"ok": True})
            if p == "/api/me":
                u = self._user()
                if not u: return self._json({"ok": False})
                with _lock:
                    role = "admin" if is_admin(u) else "user"
                return self._json({"ok": True, "user": u, "role": role, "admin": admin_name()})
            if p == "/api/msgs":
                u = self._user()
                if not u: return self._json({"ok": False}, 401)
                adm = is_admin(u)
                with _lock:
                    out = []
                    for m in MSGS:
                        if adm or m["frm"] == u or m["to"] == u or m["to"] == "*":
                            out.append(dict(m))
                return self._json({"ok": True, "msgs": out})
            if p == "/api/users":
                u = self._user()
                if not u or not is_admin(u): return self._json({"ok": False}, 403)
                with _lock:
                    lst = [{"name": n, "role": ("admin" if is_admin(n) else "user"), "last": x.get("last", 0), "c": x.get("c", 0)} for n, x in USERS.items()]
                return self._json({"ok": True, "users": lst})
            if p == "/api/bot":
                u = self._user()
                if not u: return self._json({"ok": False}, 401)
                try:
                    j = tg("getMe", {})
                    return self._json({"ok": bool(j.get("ok")), "username": (j.get("result") or {}).get("username", "")})
                except Exception as e:
                    return self._json({"ok": False, "desc": str(e)[:100]})
            if p == "/api/log":
                u = self._user()
                if not u: return self._json({"ok": False}, 401)
                with _lock:
                    return self._json({"ok": True, "log": LOGS.get(u, [])})
            return self._json({"ok": False}, 404)
        if p in ALLOWED_STATIC or (p.startswith("/assets/") and ".." not in p and p.lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".css", ".js", ".webp"))):
            return super().do_GET()
        return self._json({"ok": False}, 404)

    # ---------- API ----------
    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            if p == "/api/register":  return self.api_register()
            if p == "/api/login":     return self.api_login()
            u = self._user()
            if not u:                 return self._json({"ok": False, "error": "unauthorized"}, 401)
            if p == "/api/logout":    return self.api_logout()
            if p == "/api/changepass":return api_changepass_proxy(self, u)
            if p == "/api/msgs":      return self.api_msgs(u)
            if p == "/api/markread":  return self.api_markread(u)
            if p == "/api/send":      return self.api_send(u)
            if p == "/api/sendfile":  return self.api_sendfile(u)
            if p == "/api/log":       return self.api_log(u)
            if p == "/api/logclear":  return self.api_logclear(u)
            return self._json({"ok": False}, 404)
        except ValueError:
            return self._json({"ok": False, "error": "bad request"}, 400)
        except Exception as e:
            return self._json({"ok": False, "error": str(e)[:200]}, 500)

    # ---------- احراز هویت ----------
    def _rate(self, name):
        import time
        c, until = FAIL.get(name, (0, 0))
        if time.time() < until:
            return False
        return True

    def _fail(self, name):
        import time
        c, _ = FAIL.get(name, (0, 0))
        c += 1
        FAIL[name] = (c, time.time() + 300) if c >= 6 else (c, 0)

    def api_register(self):
        b = self._body()
        name = (b.get("user") or "").strip()
        pw = b.get("pass") or ""
        if not NAME_RE.match(name):      return self._json({"ok": False, "error": "نام کاربری معتبر نیست"}, 400)
        if len(pw) < 4:                  return self._json({"ok": False, "error": "گذرواژه حداقل ۴ کاراکتر"}, 400)
        with _lock:
            if name in USERS:            return self._json({"ok": False, "error": "این نام کاربری قبلاً ساخته شده"}, 400)
            salt = secrets.token_hex(8)
            role = "admin" if (CFG.get("admin") == name or not any(x.get("role") == "admin" for x in USERS.values())) else "user"
            USERS[name] = {"s": salt, "h": pwhash(pw, salt), "c": int(time.time() * 1000), "role": role, "last": int(time.time() * 1000)}
            _save_users()
            tok = self._make_session(name)
        return self._json({"ok": True, "token": tok, "user": name, "role": role})

    def api_login(self):
        b = self._body()
        name = (b.get("user") or "").strip()
        pw = b.get("pass") or ""
        if not self._rate(name):         return self._json({"ok": False, "error": "تلاش بیش از حد؛ ۵ دقیقه صبر کنید"}, 429)
        with _lock:
            u = USERS.get(name)
            if not u or u["h"] != pwhash(pw, u["s"]):
                self._fail(name)
                return self._json({"ok": False, "error": "نام کاربری یا گذرواژه اشتباه است"}, 401)
            tok = self._make_session(name)
        return self._json({"ok": True, "token": tok, "user": name})

    def _make_session(self, name):
        tok = secrets.token_hex(24)
        SESS[tok] = {"user": name, "c": int(__import__("time").time() * 1000)}
        _save_sess()
        return tok

    def api_logout(self):
        auth = self.headers.get("Authorization", "")
        tok = auth[7:] if auth.startswith("Bearer ") else ""
        with _lock:
            SESS.pop(tok, None)
            _save_sess()
        return self._json({"ok": True})

    # ---------- پیام‌رسان دوطرفه ----------
    def api_msgs(self, u):
        b = self._body()
        to = (b.get("to") or "").strip()
        text = (b.get("text") or "").strip()
        if not text:                 return self._json({"ok": False, "error": "empty"}, 400)
        if len(text) > 4000:         return self._json({"ok": False, "error": "too long"}, 400)
        adm = is_admin(u)
        with _lock:
            if to == "*":
                if not adm:          return self._json({"ok": False}, 403)
            elif to not in USERS:    return self._json({"ok": False, "error": "no user"}, 400)
            elif not adm and to != admin_name():
                                     return self._json({"ok": False}, 403)
            mid = (max([m["id"] for m in MSGS], default=0) + 1)
            m = {"id": mid, "frm": u, "to": to, "text": text, "t": int(time.time() * 1000), "read": False}
            MSGS.append(m)
            _save_msgs()
        return self._json({"ok": True, "id": mid})

    def api_markread(self, u):
        with _lock:
            for m in MSGS:
                if m["to"] == u and not m["read"]:
                    m["read"] = True
            _save_msgs()
        return self._json({"ok": True})

    # ---------- ارسال ----------
    def api_send(self, u):
        b = self._body()
        method = b.get("method")
        fields = dict(b.get("fields") or {})
        if method == "sendMessage":
            fields["text"] = (fields.get("text") or "") + "\n\n👤 کاربر: " + u
        elif method in ("sendLocation", "sendContact"):
            pass
        else:
            return self._json({"ok": False, "error": "method"}, 400)
        j = tg(method, {**fields, "chat_id": CHAT})
        if j.get("ok") and method in ("sendLocation", "sendContact"):
            tg("sendMessage", {"chat_id": CHAT, "text": "👤 کاربر: " + u})
        return self._json({"ok": bool(j.get("ok")), "desc": j.get("description", "")})

    def api_sendfile(self, u):
        b = self._body()
        method = b.get("method")
        if method not in ("sendPhoto", "sendVideo", "sendDocument"):
            return self._json({"ok": False, "error": "method"}, 400)
        data = base64.b64decode(b.get("data") or "")
        if not data:                     return self._json({"ok": False, "error": "empty file"}, 400)
        name = (b.get("name") or "upload.bin").replace("\"", "").replace("\r", "").replace("\n", "")[:80]
        field = {"sendPhoto": "photo", "sendVideo": "video", "sendDocument": "document"}[method]
        j = tg(method, {"chat_id": CHAT, "caption": "👤 کاربر: " + u}, data, field, name)
        return self._json({"ok": bool(j.get("ok")), "desc": j.get("description", "")})

    # ---------- تاریخچه ----------
    def api_log(self, u):
        b = self._body()
        with _lock:
            arr = LOGS.setdefault(u, [])
            arr.insert(0, b)
            LOGS[u] = arr[:50]
            _save_logs()
        return self._json({"ok": True})

    def api_logclear(self, u):
        with _lock:
            LOGS[u] = []
            _save_logs()
        return self._json({"ok": True})

def api_changepass_proxy(h, u):
    b = h._body()
    old, new = b.get("old") or "", b.get("new") or ""
    if len(new) < 4:                     return h._json({"ok": False, "error": "گذرواژه جدید حداقل ۴ کاراکتر"}, 400)
    with _lock:
        rec = USERS.get(u)
        if not rec or rec["h"] != pwhash(old, rec["s"]):
            return h._json({"ok": False, "error": "گذرواژه فعلی اشتباه است"}, 401)
        salt = secrets.token_hex(8)
        USERS[u] = {"s": salt, "h": pwhash(new, salt), "c": rec["c"]}
        _save_users()
    return h._json({"ok": True})

def main():
    _load()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    domain = os.environ.get("CERT_DOMAIN", "gavidan.norkhizstudio.com")
    cert = "/etc/letsencrypt/live/%s/fullchain.pem" % domain
    key  = "/etc/letsencrypt/live/%s/privkey.pem" % domain
    if not (os.path.exists(cert) and os.path.exists(key)):
        cert = os.path.join(BASE, "cert.pem")
        key  = os.path.join(BASE, "key.pem")
    if os.path.exists(cert) and os.path.exists(key):
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        print("GARD JAVIDAN PANEL (HTTPS) on 0.0.0.0:%d" % PORT, flush=True)
    else:
        print("GARD JAVIDAN PANEL (HTTP) on 0.0.0.0:%d" % PORT, flush=True)
    srv.serve_forever()

if __name__ == "__main__":
    main()
