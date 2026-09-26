"""Unmute — minimal RFC6455 WebSocket server + connection hub."""
import base64
import hashlib
import json
import os
import struct
import threading

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


class WSConn:
    def __init__(self, sock, user_id):
        self.sock = sock
        self.user_id = user_id
        self.alive = True
        self.wlock = threading.Lock()

    # ---- send ----
    def _frame(self, opcode, payload: bytes):
        head = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head += bytes([n])
        elif n < 65536:
            head += bytes([126]) + struct.pack(">H", n)
        else:
            head += bytes([127]) + struct.pack(">Q", n)
        with self.wlock:
            self.sock.sendall(head + payload)

    def send_text(self, obj):
        try:
            self._frame(1, json.dumps(obj, ensure_ascii=False).encode())
        except Exception:
            self.alive = False

    def send_pong(self, payload=b""):
        try:
            self._frame(10, payload)
        except Exception:
            pass

    def close(self):
        self.alive = False
        try:
            self._frame(8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

    # ---- recv ----
    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    def recv_text(self):
        """Returns next text payload (str) or raises. Handles ping/pong/close."""
        while True:
            b1, b2 = self._read_exact(2)
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            ln = b2 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._read_exact(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            data = self._read_exact(ln) if ln else b""
            if mask:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            if opcode == 8:
                raise ConnectionError("close")
            if opcode == 9:
                self.send_pong(data)
                continue
            if opcode == 10:
                continue
            if opcode in (1, 2):
                return data.decode("utf-8", "ignore")


class Hub:
    def __init__(self):
        self.conns = {}          # user_id -> set(WSConn)
        self.lock = threading.Lock()

    def add(self, c: WSConn):
        with self.lock:
            self.conns.setdefault(c.user_id, set()).add(c)

    def remove(self, c: WSConn):
        with self.lock:
            s = self.conns.get(c.user_id)
            if s:
                s.discard(c)
                if not s:
                    self.conns.pop(c.user_id, None)

    def online_count(self, user_id) -> int:
        with self.lock:
            return len(self.conns.get(user_id, ()))

    def online_ids(self):
        with self.lock:
            return list(self.conns.keys())

    def send_user(self, user_id, obj):
        with self.lock:
            conns = list(self.conns.get(user_id, ()))
        for c in conns:
            c.send_text(obj)

    def send_many(self, user_ids, obj):
        for uid in set(user_ids):
            self.send_user(uid, obj)
