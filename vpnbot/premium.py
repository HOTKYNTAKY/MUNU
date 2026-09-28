"""ایموجی پریمیوم تلگرام + تبدیل HTML ساده به entities.

- ادمین با فوروارد پیام حاوی ایموجی پریمیوم، آن را با یک نام ثبت می‌کند.
- در متن‌ها و دکمه‌ها با {e:name} استفاده می‌شود:
    - در متن پیام → انتیتی custom_emoji
    - در دکمه → icon_custom_emoji_id (قابلیت جدید Bot API)
- چون انتیتی و parse_mode را نمی‌شود قاطی کرد، px() تگ‌های HTML ساده
  را هم خودش به انتیتی تبدیل می‌کند و پیام بدون parse_mode ارسال می‌شود.
"""
from __future__ import annotations

import html as _html
import re

from aiogram.types import MessageEntity, Message

import database as db

TOKEN_RE = re.compile(r"\{e:([A-Za-z0-9_]{1,32})\}")
CARRIER = "⭐"  # کاراکتر نگه‌دارنده ایموجی (تک‌واحدی در UTF-16)

# تگ‌های HTML پشتیبانی‌شده: تگ -> نوع انتیتی
TAG_MAP = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic",
           "u": "underline", "ins": "underline", "s": "strikethrough",
           "strike": "strikethrough", "del": "strikethrough",
           "code": "code", "pre": "pre", "tg-spoiler": "spoiler"}
TAG_RE = re.compile(r"<(/?)([a-z-]+)(?:\s+href=[\"']([^\"']+)[\"'])?\s*/?>", re.IGNORECASE)


def _u16(s: str) -> int:
    """طول رشته بر حسب واحد UTF-16 (واحد offset تلگرام)."""
    return len(s.encode("utf-16-le")) // 2


def extract_ids(m: Message) -> list[str]:
    """استخراج custom_emoji_idها از پیام/کپشن فورواردشده ادمین."""
    out: list[str] = []
    for ent in list(m.entities or []) + list(m.caption_entities or []):
        if ent.type == "custom_emoji" and ent.custom_emoji_id:
            if ent.custom_emoji_id not in out:
                out.append(ent.custom_emoji_id)
    return out


def parse_text(text: str) -> tuple[str, list[MessageEntity]]:
    """متن با HTML ساده و {e:name} → (متن تمیز، انتیتی‌ها)."""
    entities: list[MessageEntity] = []
    out: list[str] = []
    stack: list[tuple[str, int, dict]] = []  # (نوع, آفست شروع, فیلد اضافه)

    def emit(chunk: str) -> None:
        if chunk:
            out.append(chunk)

    def cur_len() -> int:
        return _u16("".join(out))

    pos = 0
    # اول توکن‌های {e:} شناخته‌شده را با حفره تک‌کاراکتری جایگزین می‌کنیم
    # (ناشناس‌ها دست‌نخورده می‌مانند تا آفست‌ها به‌هم نریزند)
    eids: list[str] = []
    tmp: list[str] = []
    for mt in TOKEN_RE.finditer(text):
        tmp.append(text[pos:mt.start()])
        eid = db.get_emoji(mt.group(1))
        if eid:
            tmp.append("\x00")
            eids.append(eid)
        else:
            tmp.append(mt.group(0))
        pos = mt.end()
    tmp.append(text[pos:])
    text = "".join(tmp)

    pos = 0
    for m in TAG_RE.finditer(text):
        emit(_html.unescape(text[pos:m.start()]))
        closing, tag, href = m.group(1), m.group(2).lower(), m.group(3)
        if tag == "a" and href and not closing:
            stack.append(("text_link", cur_len(), {"url": href}))
        elif tag == "a" and closing:
            _close(stack, entities, "text_link", cur_len())
        elif tag in TAG_MAP and not closing:
            stack.append((TAG_MAP[tag], cur_len(), {}))
        elif tag in TAG_MAP and closing:
            _close(stack, entities, TAG_MAP[tag], cur_len())
        else:
            emit(m.group(0))  # تگ ناشناس: دست‌نخورده
        pos = m.end()
    emit(_html.unescape(text[pos:]))

    plain = "".join(out)
    # جایگزینی حفره‌ها با ایموجی (تک‌واحدی → آفست‌ها ثابت می‌مانند)
    result: list[str] = []
    hole_idx = 0
    for ch in plain:
        if ch == "\x00" and hole_idx < len(eids):
            entities.append(MessageEntity(type="custom_emoji", offset=_u16("".join(result)),
                                          length=_u16(CARRIER),
                                          custom_emoji_id=eids[hole_idx]))
            result.append(CARRIER)
            hole_idx += 1
        else:
            result.append(ch)
    final = "".join(result)

    # مرتب‌سازی انتیتی‌ها (تلگرام ترتیب صعودی می‌خواهد)
    entities.sort(key=lambda e: (e.offset, e.length))
    return final, entities


def _close(stack: list, entities: list, kind: str, end: int) -> None:
    for i in range(len(stack) - 1, -1, -1):
        if stack[i][0] == kind:
            _, start, extra = stack.pop(i)
            if end > start:
                entities.append(MessageEntity(type=kind, offset=start,
                                              length=end - start, **extra))
            return


def parse_button(label: str) -> tuple[str, str | None]:
    """لیبل دکمه: اولین {e:name} معتبر → (متن تمیز، icon_custom_emoji_id)."""
    m = TOKEN_RE.search(label)
    if not m:
        return label, None
    eid = db.get_emoji(m.group(1))
    if not eid:
        return label, None
    clean = (label[:m.start()] + label[m.end():]).strip()
    return clean or CARRIER, eid
