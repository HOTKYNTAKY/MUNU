#!/usr/bin/env python3
"""Unmute — entry point: HTTP + WebSocket server (stdlib only)."""
import json
import os
import re
import socket
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import db
import api
import api2
import util
import wsproto
from util import now_ms

PORT = int(os.environ.get("UM_PORT", "8788"))
HUB = wsproto.Hub()
api.HUB = HUB
db.init()

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/logo.svg": ("logo.svg", "image/svg+xml"),
    "/views.js": ("views.js", "text/javascript; charset=utf-8"),
    "/chat.js": ("chat.js", "text/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "Unmute/1.0"
    protocol_version = "HTTP/1.1"
    hub = HUB
    token = None
    _fields = {}

    def log_message(self, *a):
        pass

    # ---------- utils ----------
    def j(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > util.MAX_UPLOAD + 2_000_000:
            return b""
        return self.rfile.read(n)

    def jbody(self):
        try:
            return json.loads((self._raw or b"").decode("utf-8", "ignore"))
        except Exception:
            return {}

    def authed(self):
        u = api.auth_user(self)
        self.token = (self.headers.get("Authorization") or "")[7:]
        return u

    # ---------- GET ----------
    def do_GET(self):
        try:
            self.route("GET")
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception as e:
            try:
                self.j({"ok": False, "error": str(e)[:160]}, 500)
            except Exception:
                pass

    def do_POST(self):
        try:
            self.route("POST")
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception as e:
            try:
                self.j({"ok": False, "error": str(e)[:160]}, 500)
            except Exception:
                pass

    def do_PATCH(self):
        try:
            self.route("PATCH")
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception as e:
            try:
                self.j({"ok": False, "error": str(e)[:160]}, 500)
            except Exception:
                pass

    def do_DELETE(self):
        try:
            self.route("DELETE")
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception as e:
            try:
                self.j({"ok": False, "error": str(e)[:160]}, 500)
            except Exception:
                pass

    def route(self, method):
        self._raw = self.body() if method != "GET" else b""
        pq = urlparse(self.path)
        p, q = pq.path.rstrip("/") or "/", parse_qs(pq.query)
        if p.startswith("/api/media/") and q.get("token") and not self.headers.get("Authorization"):
            try:
                self.headers["Authorization"] = "Bearer " + q["token"][0]
            except Exception:
                pass
        if p == "/ws":
            return self.ws_upgrade(q)
        # ---- public auth ----
        if method == "POST" and p == "/api/auth/register":
            return api.register(self, self.jbody())
        if method == "POST" and p == "/api/auth/login":
            return api.login(self, self.jbody())
        if method == "POST" and p == "/api/auth/forgot":
            return api.forgot(self, self.jbody())
        if method == "POST" and p == "/api/auth/reset":
            return api2.reset(self, self.jbody())
        if p == "/api/health":
            return self.j({"ok": True, "app": "unmute"})
        if p == "/api/dev/inbox":
            return api2.dev_inbox(self)
        # ---- static (public) ----
        if method == "GET" and p in STATIC:
            return self.serve_static(STATIC[p])
        # ---- authed ----
        if not _rl_ok(self):
            return self.j({"ok": False, "error": "rate"}, 429)
        u = self.authed()
        if not u:
            return self.j({"ok": False, "error": "unauthorized"}, 401)
        b = self.jbody() if method in ("POST", "PATCH", "DELETE") else {}

        if p == "/api/me" and method == "GET":
            return api2.me(self, u)
        if p == "/api/me" and method == "PATCH":
            return api2.patch_me(self, u, b)
        if p == "/api/me" and method == "DELETE":
            return api2.delete_account(self, u)
        if p == "/api/me/username":
            return api2.change_username(self, u, b)
        if p == "/api/me/password":
            return api2.change_password(self, u, b)
        if p == "/api/me/email":
            return api2.change_email(self, u, b)
        if p == "/api/me/verify":
            return api2.verify(self, u, b)
        if p == "/api/auth/logout":
            db.conn().execute("DELETE FROM sessions WHERE token=?", (self.token,))
            db.conn().commit()
            return self.j({"ok": True})
        if p == "/api/settings" and method == "GET":
            return api2.get_settings(self, u)
        if p == "/api/settings" and method == "PATCH":
            return api2.patch_settings(self, u, b)

        if p == "/api/users/search":
            return api2.search_users(self, u, q)
        if p == "/api/sessions" and method == "GET":
            return api2.sessions_list(self, u)
        if p == "/api/sessions" and method == "DELETE":
            return api2.sessions_revoke(self, u, b)
        m = re.match(r"^/api/users/([A-Za-z0-9_]{1,30})$", p)
        if m and method == "GET":
            return api2.profile(self, u, m.group(1))
        m = re.match(r"^/api/users/([A-Za-z0-9_]{1,30})/(contact|block|report)$", p)
        if m and method == "POST":
            if m.group(2) == "contact":
                return api2.contact_toggle(self, u, m.group(1), b)
            if m.group(2) == "block":
                return api2.block_toggle(self, u, m.group(1), b)
            return api2.report_user(self, u, m.group(1), b)
        if p == "/api/contacts":
            return api2.contacts_list(self, u)

        if p == "/api/chats" and method == "GET":
            return api.chat_list(self, u)
        if p == "/api/chats/dm" and method == "POST":
            return api2.dm_open(self, u, b)
        m = re.match(r"^/api/chats/(\d+)/messages$", p)
        if m and method == "GET":
            return api.fetch_messages(self, u, int(m.group(1)), q)
        if m and method == "POST":
            return api.send_message(self, u, int(m.group(1)), b)
        m = re.match(r"^/api/chats/(\d+)/read$", p)
        if m and method == "POST":
            return api.mark_read(self, u, int(m.group(1)), b)
        m = re.match(r"^/api/chats/(\d+)/meta$", p)
        if m and method in ("POST", "PATCH"):
            return api2.chat_meta(self, u, int(m.group(1)), b)

        m = re.match(r"^/api/messages/(\d+)$", p)
        if m and method == "PATCH":
            return api2.edit_message(self, u, int(m.group(1)), b)
        if m and method == "DELETE":
            return api2.delete_message(self, u, int(m.group(1)), q)
        m = re.match(r"^/api/messages/(\d+)/(react|forward|pin)$", p)
        if m and method == "POST":
            fn = {"react": api2.react_message, "forward": api2.forward_message, "pin": api2.pin_message}[m.group(2)]
            return fn(self, u, int(m.group(1)), b)

        if p == "/api/upload" and method == "POST":
            ctype = self.headers.get("Content-Type") or ""
            if "multipart/form-data" not in ctype:
                return self.j({"ok": False, "error": "multipart"}, 400)
            fields, files = util.parse_multipart(self._raw, ctype)
            self._fields = fields
            return api2.upload(self, u, files)
        m = re.match(r"^/api/media/(\d+)$", p)
        if m:
            return api2.media(self, u, int(m.group(1)))

        if p == "/api/notifications" and method == "GET":
            return api2.notifications(self, u)
        if p == "/api/notifications/read":
            return api2.notifications_read(self, u)
        if p == "/api/search":
            return api2.search_all(self, u, q)

        # ---- admin ----
        if p.startswith("/api/admin/"):
            if u["role"] != "admin":
                return self.j({"ok": False, "error": "forbidden"}, 403)
            if p == "/api/admin/stats":
                return api2.admin_stats(self, u)
            if p == "/api/admin/users":
                return api2.admin_users(self, u, q)
            m = re.match(r"^/api/admin/users/(\d+)/action$", p)
            if m:
                return api2.admin_user_action(self, u, m.group(1), b)
            if p == "/api/admin/reports":
                return api2.admin_reports(self, u)
            m = re.match(r"^/api/admin/reports/(\d+)/resolve$", p)
            if m:
                return api2.admin_report_resolve(self, u, m.group(1))
            if p == "/api/admin/broadcast":
                return api2.admin_broadcast(self, u, b)

        return self.j({"ok": False, "error": "notfound"}, 404)

    def serve_static(self, spec):
        name, ctype = spec
        path = os.path.join(api.WEB_DIR, name)
        try:
            data = open(path, "rb").read()
        except Exception:
            return self.j({"ok": False}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache" if name in ("index.html", "sw.js") else "public, max-age=300")
        self.end_headers()
        self.wfile.write(data)

    # ---------- WebSocket ----------
    def ws_upgrade(self, q):
        tok = (q.get("token") or [""])[0]
        self.token = tok
        u = api.auth_user(self)
        if not u:
            return self.j({"ok": False}, 401)
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            return self.j({"ok": False}, 400)
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", wsproto.accept_key(key))
        self.end_headers()
        sock = self.connection
        sock.settimeout(90)
        c = wsproto.WSConn(sock, u["id"])
        first = HUB.online_count(u["id"]) == 0
        HUB.add(c)
        db.conn().execute("UPDATE users SET last_seen=? WHERE id=?", (now_ms(), u["id"]))
        db.conn().commit()
        if first:
            HUB.send_many(HUB.online_ids(), {"t": "presence", "uid": u["id"], "online": True})
        try:
            while c.alive:
                txt = c.recv_text()
                try:
                    ev = json.loads(txt)
                except Exception:
                    continue
                t = ev.get("t")
                if t == "ping":
                    c.send_text({"t": "pong"})
                elif t == "typing":
                    cid = int(ev.get("chat_id") or 0)
                    others = [x for x in api.chat_members(cid) if x != u["id"]]
                    HUB.send_many(others, {"t": "typing", "chat_id": cid, "uid": u["id"],
                                           "name": u["display_name"]})
        except (ConnectionError, socket.timeout, OSError):
            pass
        finally:
            HUB.remove(c)
            c.close()
            if HUB.online_count(u["id"]) == 0:
                db.conn().execute("UPDATE users SET last_seen=? WHERE id=?", (now_ms(), u["id"]))
                db.conn().commit()
                HUB.send_many(HUB.online_ids(), {"t": "presence", "uid": u["id"], "online": False})
        try:
            self.close_connection = True
        except Exception:
            pass


_rl = util.RateLimiter(400, 60)


def _rl_ok(h):
    return _rl.hit(h.client_address[0])


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    print("UNMUTE listening on 0.0.0.0:%d (dev=%s)" % (PORT, os.environ.get("UM_DEV", "0")), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
