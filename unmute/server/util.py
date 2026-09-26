"""Unmute — security & parsing utilities."""
import hashlib
import hmac
import os
import re
import secrets
import time
import threading

now_ms = lambda: int(time.time() * 1000)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PBKDF2_ITER = 200_000

AVATAR_EMOJI = ["\U0001F9D1\u200D\U0001F680","\U0001F98A","\U0001F43B","\U0001F43C","\U0001F42F","\U0001F438","\U0001F981","\U0001F428","\U0001F984","\U0001F433","\U0001F338","\U0001F319","\u2B50","\U0001F525","\U0001F340","\U0001F388","\U0001F3A7","\U0001F3AF","\U0001F9E0","\U0001F916"]
AVATAR_COLORS = ["#6d5ef1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#8b5cf6", "#14b8a6"]


def pwhash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITER).hex()


def new_token(n=24) -> str:
    return secrets.token_urlsafe(n)


def safe_eq(a, b) -> bool:
    return hmac.compare_digest(str(a), str(b))


class RateLimiter:
    """Sliding window per key."""
    def __init__(self, limit=30, window=60):
        self.limit, self.window = limit, window
        self.d = {}
        self.lock = threading.Lock()

    def hit(self, key) -> bool:
        now = time.time()
        with self.lock:
            for k in [k for k, v in self.d.items() if not v or now - v[-1] > self.window]:
                self.d.pop(k, None)
            arr = self.d.setdefault(key, [])
            while arr and now - arr[0] > self.window:
                arr.pop(0)
            if len(arr) >= self.limit:
                return False
            arr.append(now)
            return True


EXT_KIND = {
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image", ".gif": "image",
    ".mp4": "video", ".webm": "video", ".mov": "video",
    ".mp3": "audio", ".ogg": "audio", ".m4a": "audio", ".wav": "audio",
    ".pdf": "file", ".zip": "file", ".txt": "file", ".doc": "file", ".docx": "file",
    ".xls": "file", ".xlsx": "file", ".ppt": "file", ".pptx": "file", ".json": "file",
}
ALLOWED_EXT = set(EXT_KIND)
MAX_UPLOAD = 25 * 1024 * 1024


def kind_of(filename: str, mime: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in EXT_KIND:
        return EXT_KIND[ext]
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "file"


def parse_multipart(body: bytes, ctype: str):
    """Minimal multipart/form-data parser. Returns (fields, files)."""
    fields, files = {}, []
    m = re.search(r'boundary="?([^";]+)"?', ctype or "")
    if not m:
        return fields, files
    boundary = ("--" + m.group(1)).encode()
    parts = body.split(boundary)
    for p in parts:
        p = p.strip(b"\r\n")
        if not p or p == b"--":
            continue
        if b"\r\n\r\n" not in p:
            continue
        head, content = p.split(b"\r\n\r\n", 1)
        headtxt = head.decode("utf-8", "ignore")
        nm = re.search(r'name="([^"]*)"', headtxt)
        fn = re.search(r'filename="([^"]*)"', headtxt)
        mt = re.search(r'Content-Type:\s*([^\r\n]+)', headtxt, re.I)
        if not nm:
            continue
        if fn:
            files.append({"field": nm.group(1), "filename": fn.group(1),
                          "mime": (mt.group(1).strip() if mt else "application/octet-stream"),
                          "data": content})
        else:
            fields[nm.group(1)] = content.decode("utf-8", "ignore")
    return fields, files
