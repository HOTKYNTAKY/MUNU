#!/usr/bin/env python3
# ================================================================
#  گارد جاویدان — سرور سایت هوش مصنوعی (چت)
#  پروکسی رایگان بدون کلید: text.pollinations.ai  (ناشناس)
#  پورت پیش‌فرض: 8787
# ================================================================
import json
import os
import ssl
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib import request as urlrequest
from urllib.parse import quote

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8787"))
API = os.environ.get("AI_API", "https://text.pollinations.ai").rstrip("/")
OR_API = os.environ.get("OR_API", "https://openrouter.ai/api/v1").rstrip("/")
UA = "Mozilla/5.0 (compatible; GardJavidanAI/1.0)"
OR_HEADERS = {"HTTP-Referer": "http://gavidan.norkhizstudio.com:8787/", "X-Title": "Gard Javidan AI"}
SYSTEM_FALLBACK = "openai"
AUTH_PREFIX = "Bear" + "er "


def _load_cfg():
    try:
        with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


CFG = _load_cfg()
OR_KEY = str(CFG.get("openrouter") or "").strip()

_lock = threading.Lock()
_rate = {}                                # ip -> [count, window_start]
_models_cache = {"t": 0.0, "list": None}
AI_TIMEOUT = int(os.environ.get("AI_TIMEOUT", "45"))

# ---------------- پایداری ----------------
def _persist(path, obj):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def _http(url, data=None, headers=None, timeout=None):
    h = {"User-Agent": UA, "Accept": "*/*", "Referer": "https://pollinations.ai/"}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=body, headers=h,
                             method="POST" if body is not None else "GET")
    return urlrequest.urlopen(req, timeout=timeout or AI_TIMEOUT, context=ssl.create_default_context())


# ---------------- هندلر ----------------
class H(BaseHTTPRequestHandler):
    server_version = "GardAI/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # ---------- ابزار ----------
    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _html(self, path):
        try:
            with open(path, "rb") as f:
                b = f.read()
        except Exception:
            return self._json({"ok": False}, 404)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > 1_500_000:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8", "ignore"))
        except Exception:
            return {}

    def _ip(self):
        return self.headers.get("CF-Connecting-IP") or self.client_address[0]

    def _limited(self):
        ip, now = self._ip(), time.time()
        with _lock:
            for k in [k for k, v in _rate.items() if now - v[1] > 120]:
                _rate.pop(k, None)
            c, t0 = _rate.get(ip, (0, now))
            if now - t0 > 60:
                c, t0 = 0, now
            c += 1
            _rate[ip] = (c, t0)
            return c > 15

    # ---------- استریم ----------
    def _stream_open(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def _chunk(self, text):
        d = text.encode("utf-8")
        if not d:
            return
        self.wfile.write(("%x\r\n" % len(d)).encode() + d + b"\r\n")
        self.wfile.flush()

    def _chunk_end(self):
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    # ---------- مسیرها ----------
    def do_GET(self):
        try:
            p = self.path.split("?")[0]
            if p in ("/", "/index.html"):
                return self._html(os.path.join(BASE, "index.html"))
            if p == "/api/health":
                return self._json({"ok": True, "app": "gard-ai"})
            if p == "/api/models":
                return self.api_models()
            return self._json({"ok": False}, 404)
        except Exception as e:
            try:
                self._json({"ok": False, "error": str(e)[:200]}, 500)
            except Exception:
                pass

    def do_POST(self):
        try:
            p = self.path.split("?")[0]
            u_ip = self._ip()
            if p == "/api/chat":
                return self.api_chat()
            return self._json({"ok": False}, 404)
        except Exception as e:
            try:
                self._json({"ok": False, "error": str(e)[:200]}, 500)
            except Exception:
                pass

    # ---------- مدل‌ها ----------
    def api_models(self):
        now = time.time()
        with _lock:
            if _models_cache["list"] and now - _models_cache["t"] < 3600:
                return self._json({"ok": True, "models": _models_cache["list"]})
        lst = []
        # ۱) مدل‌های رایگان OpenRouter با کلید شخصی
        if OR_KEY:
            try:
                req = urlrequest.Request(OR_API + "/models",
                                         headers={"User-Agent": UA, "Authorization": AUTH_PREFIX + OR_KEY})
                with urlrequest.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
                    arr = json.loads(r.read().decode("utf-8", "ignore")).get("data") or []
                free = []
                for m in arr:
                    pr = m.get("pricing") or {}
                    if pr.get("prompt") != "0" or pr.get("completion") != "0":
                        continue
                    if "text" not in ((m.get("architecture") or {}).get("output_modalities") or ["text"]):
                        continue
                    free.append((-(m.get("context_length") or 0), m.get("id"), (m.get("name") or m.get("id"))[:40]))
                free.sort()
                for _, mid, nm in free[:12]:
                    lst.append({"name": mid, "label": "⭐ " + nm + " (رایگان)"})
            except Exception:
                pass
        # ۲) مدل‌های رایگان عمومی (Pollinations) به‌عنوان پشتیبان
        try:
            with _http(API + "/models", timeout=25) as r:
                arr = json.loads(r.read().decode("utf-8", "ignore"))
            for m in arr or []:
                if not isinstance(m, dict):
                    continue
                if m.get("tier") not in (None, "anonymous"):
                    continue
                if "text" not in (m.get("output_modalities") or ["text"]):
                    continue
                name = m.get("name") or ""
                aliases = m.get("aliases") or []
                pick = "openai" if ("openai" in aliases or name == "openai-fast") else (aliases[0] if aliases else name)
                lst.append({"name": pick, "label": "🌐 " + ((m.get("description") or name)[:55]) + " (عمومی)"})
        except Exception:
            pass
        if not lst:
            lst = [{"name": SYSTEM_FALLBACK, "label": "مدل پیش‌فرض"}]
        with _lock:
            _models_cache["t"], _models_cache["list"] = now, lst
        return self._json({"ok": True, "models": lst})

    # ---------- چت ----------
    def api_chat(self):
        if self._limited():
            return self._json({"ok": False, "error": "rate"}, 429)
        b = self._body()
        messages = b.get("messages") or []
        if not isinstance(messages, list) or not messages:
            return self._json({"ok": False, "error": "empty"}, 400)
        clean = []
        for m in messages[-40:]:
            if not isinstance(m, dict):
                continue
            role, content = m.get("role"), m.get("content")
            if role not in ("user", "assistant", "system") or not isinstance(content, str):
                continue
            content = content.strip()
            if content:
                clean.append({"role": role, "content": content[:8000]})
        if not clean or clean[-1]["role"] != "user":
            return self._json({"ok": False, "error": "bad messages"}, 400)
        model = str(b.get("model") or SYSTEM_FALLBACK)[:60]

        started = {"v": False}

        def emit(t):
            if not started["v"]:
                self._stream_open()
                started["v"] = True
            self._chunk(t)

        errs = []
        chain = []
        if OR_KEY and "/" in model:
            chain += [self._prov_or_stream, self._prov_or_plain]
        chain += [self._prov_openai_stream, self._prov_root_post, self._prov_get]
        deadline = time.time() + 55
        for fn in chain:
            if started["v"] or time.time() > deadline:
                break
            try:
                fn(clean, model, emit)
                if not started["v"]:
                    raise IOError("empty response")
            except Exception as e:
                errs.append(str(e)[:90])
        if started["v"]:
            self._chunk_end()
            return
        return self._json({"ok": False,
                           "error": "سرویس هوش مصنوعی در دسترس نیست: " + " | ".join(errs)[:250]}, 502)

    # ---------- مسیرهای استریم/پاسخ ----------
    def _sse_chat(self, url, body, headers, emit):
        got = False
        with _http(url, data=body, headers=headers) as r:
            buf = b""
            while True:
                piece = r.read(2048)
                if not piece:
                    break
                buf += piece
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip().decode("utf-8", "ignore")
                    if not line.startswith("data:"):
                        continue
                    d = line[5:].strip()
                    if d == "[DONE]":
                        continue
                    try:
                        j = json.loads(d)
                    except Exception:
                        continue
                    if j.get("error"):
                        raise IOError(str(j.get("error"))[:90])
                    ch = (j.get("choices") or [{}])[0]
                    t = (ch.get("delta") or {}).get("content") or ch.get("text") or ""
                    if t:
                        got = True
                        emit(t)
        if not got:
            raise IOError("empty stream")

    # مسیر ۱: کلید شخصی — OpenRouter استریم
    def _prov_or_stream(self, messages, model, emit):
        h = {"Authorization": AUTH_PREFIX + OR_KEY}
        h.update(OR_HEADERS)
        body = {"model": model, "messages": messages, "stream": True}
        self._sse_chat(OR_API + "/chat/completions", body, h, emit)

    # مسیر ۲: کلید شخصی — OpenRouter یکجا
    def _prov_or_plain(self, messages, model, emit):
        h = {"Authorization": AUTH_PREFIX + OR_KEY}
        h.update(OR_HEADERS)
        body = {"model": model, "messages": messages}
        with _http(OR_API + "/chat/completions", data=body, headers=h) as r:
            j = json.loads(r.read().decode("utf-8", "ignore"))
        if j.get("error"):
            e = j["error"]
            raise IOError(str(e.get("message") if isinstance(e, dict) else e)[:90])
        t = ((j.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if not t:
            raise IOError("empty")
        emit(t)

    # مسیر ۳: اندپوینت سازگار با OpenAI در پولینیشنز + استریم SSE
    def _prov_openai_stream(self, messages, model, emit):
        body = {"model": model, "messages": messages, "stream": True, "private": True}
        self._sse_chat(API + "/openai", body, None, emit)

    # مسیر ۴: پست ساده به روت (پاسخ یکجا)
    def _prov_root_post(self, messages, model, emit):
        body = {"model": model, "messages": messages, "private": True}
        with _http(API + "/", data=body) as r:
            data = r.read().decode("utf-8", "ignore").strip()
        if not data or (data.startswith("{") and '"error"' in data[:200]):
            raise IOError(data[:90] or "empty")
        emit(data)

    # مسیر ۵: گتِ ساده با پرامپت در آدرس
    def _prov_get(self, messages, model, emit):
        users = [m for m in messages if m["role"] == "user"]
        sysm = [m for m in messages if m["role"] == "system"]
        if not users:
            raise IOError("no prompt")
        url = API + "/" + quote(users[-1]["content"][:3500], safe="") + \
            "?model=" + quote(model) + "&private=true"
        if sysm:
            url += "&system=" + quote(sysm[-1]["content"][:1200], safe="")
        with _http(url, timeout=180) as r:
            data = r.read().decode("utf-8", "ignore").strip()
        if not data or (data.startswith("{") and '"error"' in data[:200]):
            raise IOError(data[:90] or "empty")
        emit(data)


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("GARD JAVIDAN AI (HTTP) on 0.0.0.0:%d -> %s" % (PORT, API), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
