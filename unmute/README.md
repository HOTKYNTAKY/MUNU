# Unmute — پیام‌رسان تحت وب

پیام‌رسان وب واقعی و Production-ready: ثبت‌نام/ورود، چت خصوصی Real-Time (WebSocket)،
مدیا، ویس، مخاطبین، اعلان‌ها، حریم خصوصی، تنظیمات کامل و پنل ادمین — با PWA و دو زبان فارسی/انگلیسی.

> **انتخاب استک:** به‌جای Next.js/Node/Postgres (که روی VPS فعلی بدون داکر/سرویس اضافه قابل اجرا نیست)،
> استک **Python stdlib + SQLite + Vanilla SPA** انتخاب شد تا با **صفر وابستگی خارجی** روی همین سرور
> با یک دستور نصب شود، ولی معماری کاملاً ماژولار است (لایه `db.py` جدا، API نسخه‌پذیر، کلاینت API متمرکز)
> و مهاجرت بعدی به Postgres/Next.js بدون تغییر قرارداد API ممکن است.

---

## 1. ساختار پروژه

```
unmute/
├── README.md               # همین فایل (ساختار، API، اجرا، دیپلوی، امنیت)
├── server/                 # بک‌اند پایتون — فقط کتابخانه استاندارد، بدون pip
│   ├── run.py              # نقطه ورود: HTTP + WebSocket، روتینگ، سرو فایل استاتیک
│   ├── api.py              # منطق دامنه: احراز هویت، ارسال/دریافت پیام، ابزار مشترک
│   ├── api2.py             # ادامه API: کاربر، چت، مدیا، اعلان، جستجو، ادمین
│   ├── db.py               # لایه دیتابیس SQLite (WAL) + اسکیما
│   ├── util.py             # امنیت: PBKDF2، توکن، RateLimit، اعتبارسنجی آپلود/فرم
│   ├── wsproto.py          # پیاده‌سازی RFC6455 WebSocket + Hub اتصال‌ها
│   └── update.sh           # اسکریپت نصب/آپدیت روی VPS
├── web/                    # فرانت‌اند SPA — بدون بیلد، بدون فریم‌ورک
│   ├── index.html          # شل اپ + مانیفست + فونت وزیرمتن
│   ├── app.js              # هسته: API client، WS client، روتر، تم، اعلان، کامپوننت‌ها
│   ├── chat.js             # لیست چت + پنجره چت + کامپوزر + ویس + گالری
│   ├── views.js            # صفحات: auth، پروفایل، تنظیمات، مخاطبین، اعلان، جستجو، ادمین
│   ├── i18n.js             # دیکشنری فارسی/انگلیسی + مدیریت dir
│   ├── style.css           # دیزاین‌سیستم: تم تیره/روشن، اکسنت، ریسپانسیو
│   ├── sw.js               # سرویس‌ورکر PWA (آفلاین‌شل)
│   ├── manifest.webmanifest# مانیفست نصب PWA
│   └── logo.svg            # لوگوی Unmute
└── data/                   # (روی سرور ساخته می‌شود) unmute.db + media/
```

## 2. فایل‌ها و مسئولیت‌ها

| فایل | نقش |
|---|---|
| `server/run.py` | `ThreadingHTTPServer` روی `0.0.0.0:$UM_PORT`؛ روتر REST؛ هندشیک WebSocket؛ پخش presence/typing؛ سرو استاتیک با کش |
| `server/api.py` | `register/login/forgot`، `send/fetch/read` پیام، `user_pub` (اعمال حریم خصوصی)، `msg_json` (+تیک‌ها)، `notify`/`push_msg` |
| `server/api2.py` | پروفایل/مخاطب/بلاک/ریپورت، لیست چت، ویرایش/حذف/ری‌اکشن/فوروارد/سنجاق، آپلود/مدیا، اعلان‌ها، جستجو، نشست‌ها، ادمین |
| `server/db.py` | اتصال نخ‌محلی SQLite، `PRAGMA WAL + FK`، اسکیما و ایندکس‌ها |
| `server/util.py` | `PBKDF2-HMAC-SHA256 ×200k`، `secrets.token_urlsafe`، `RateLimiter` پنجره لغزان، مجازهای آپلود (پسوند/MIME/۲۵MB)، پارسر multipart |
| `server/wsproto.py` | فریم‌بندی RFC6455 (mask/ping/pong/close) + `Hub`: ارسال به کاربر/گروه، شمارش آنلاین |
| `web/app.js` | `api()` با مدیریت 401، `wsConnect` با reconnect نمایی، `S` (استور)، روتر هش، `toast/modal/ctxMenu`، بیپ WebAudio، بج اپ، `boot()` |
| `web/chat.js` | `loadChats/paintPane`، `openChat/loadMsgs/loadOlder`، `msgHTML/attHTML/audioHTML`، آپلود XHR با پروگرس، `MediaRecorder` + وِی‌فورم، گالری، `onWSMsg/onWSRead` |
| `web/views.js` | فرم‌های auth با اعتبارسنجی، پروفایل + مودال‌ها، تنظیمات ۶ بخشی، مخاطبین، جستجو، اعلان‌ها، ادمین ۴ زبانه‌ای |
| `web/i18n.js` | `STR.fa/en` (‎~۱۸۰ کلید)، `t(k)`، `setLang` (تغییر `lang/dir`) |

## 3. اسکیمای دیتابیس (SQLite)

```sql
users(id, username UNIQUE NOCASE, display_name, email UNIQUE NOCASE,
      pass_hash, salt, avatar, cover, bio, role[user|admin],
      status[active|banned|suspended], verified, created_at, last_seen)
sessions(token PK, user_id→users, created_at, last_active, expires_at,
         remember, ua, ip)
chats(id, type[dm], created_at)
chat_members(chat_id, user_id, pinned, archived, muted, deleted_at, last_read)  -- PK(chat_id,user_id)
messages(id, chat_id→chats, sender_id→users, type[text|image|video|file|audio|voice],
         text, reply_to→messages [thread], edited_at, deleted, deleted_me CSV, created_at)
message_state(message_id, user_id, delivered_at, read_at)  -- PK(message_id,user_id): تیک‌ها
reactions(message_id, user_id, emoji)                       -- PK هر سه‌تایی
attachments(id, owner_id, message_id, kind, filename, mime, size, path, meta JSON)
pins(chat_id, message_id, by_id, created_at)                -- PK(chat_id,message_id)
contacts(owner_id, user_id, created_at)      blocked(user_id, blocked_id, created_at)
reports(id, reporter_id, target_id, reason, details, status[open|resolved], created_at)
notifications(id, user_id, kind[message|system], payload JSON, read, created_at)
settings(user_id PK, theme, accent, font_size, lang,
         notif_msg, notif_sound, notif_browser,
         priv_msg, priv_photo, priv_lastseen, priv_online, priv_profile)
tokens(token PK, user_id, kind[verify|reset], expires_at)
INDEX: messages(chat_id,id), messages(sender_id), sessions(user_id),
       notifications(user_id,read), attachments(message_id)
```

نکته‌ها: `reply_to` همان Thread/Reply است؛ `deleted_me` لیست جداشده با کاما؛
`meta` پیوست JSON است (`{voice, duration, waveform[]}` برای ویس).

## 4. مستندات API

بیس: `http(s)://host:8788` — احراز هویت همه مسیرها (جز موارد مشخص) با هدر
`Authorization: Bearer <token>`؛ پاسخ‌ها `{ok:true,...}` یا `{ok:false,error:"code"}`.

### 4.1 عمومی (بدون توکن)
| متد | مسیر | ورودی | خروجی |
|---|---|---|---|
| GET | `/api/health` | — | `{ok, app:"unmute"}` |
| POST | `/api/auth/register` | `{username, display_name, password, email?, bio?, avatar?, lang?, remember?}` | `{token, user, settings}` |
| POST | `/api/auth/login` | `{username, password, remember?}` | `{token, user, settings}` |
| POST | `/api/auth/forgot` | `{username}` (یا ایمیل) | `{sent}` |
| POST | `/api/auth/reset` | `{token, password}` | `{}` |
| GET | `/api/dev/inbox` | فقط `UM_DEV=1` | کدهای verify/reset برای توسعه |

### 4.2 من / تنظیمات (توکن)
| متد | مسیر | توضیح |
|---|---|---|
| GET/PATCH/DELETE | `/api/me` | پروفایل خود / ویرایش `{display_name,bio,avatar,cover}` / حذف حساب |
| POST | `/api/me/username`, `/api/me/password`, `/api/me/email` | تغییر نام‌کاربری / رمز `{old,new}` / ایمیل |
| POST | `/api/me/verify` | `{code}` تأیید ایمیل |
| POST | `/api/auth/logout` | ابطال نشست جاری |
| GET/PATCH | `/api/settings` | خواندن/ذخیره تم، اکسنت، فونت، زبان، اعلان‌ها، حریم‌ها |
| GET | `/api/sessions` | لیست دستگاه‌ها (توکن کوتاه‌شده + current) |
| DELETE | `/api/sessions` | `{all:true}` یا `{prefix}` برای ابطال |

### 4.3 کاربر/اجتماعی
| متد | مسیر | توضیح |
|---|---|---|
| GET | `/api/users/search?q=` | جستجوی کاربر (username/display_name) |
| GET | `/api/users/:u` | پروفایل عمومی + `chat_id` (با اعمال حریم خصوصی) |
| POST | `/api/users/:u/contact` | `{add:true/false}` |
| POST | `/api/users/:u/block` | `{block:true/false}` |
| POST | `/api/users/:u/report` | `{reason: spam|harassment|fake|inappropriate|other, details?}` |
| GET | `/api/contacts` | لیست مخاطبین |

### 4.4 چت و پیام
| متد | مسیر | توضیح |
|---|---|---|
| GET | `/api/chats` | لیست چت‌ها: `peer,last,unread,pinned,archived,muted` (مرتب: سنجاق → تازه‌ترین) |
| POST | `/api/chats/dm` | `{username}` ساخت/بازگشایی دایرکت → `{chat_id}` |
| GET | `/api/chats/:id/messages?before=&around=&limit=` | صفحه‌بندی تاریخچه + `pins` + `older` |
| POST | `/api/chats/:id/messages` | `{text?, atts?[], reply_to?}` → `{msg}` (با `delivered`) |
| POST | `/api/chats/:id/read` | `{last_id?}` رسید خوانده‌شدن (پخش WS `read`) |
| POST | `/api/chats/:id/meta` | `{pinned?,archived?,muted?,deleted?}` |
| PATCH | `/api/messages/:id` | `{text}` ویرایش (فقط فرستنده) |
| DELETE | `/api/messages/:id?scope=me\|all` | حذف (all فقط فرستنده) |
| POST | `/api/messages/:id/react` | `{emoji}` تاگل ری‌اکشن |
| POST | `/api/messages/:id/forward` | `{chat_id}` فوروارد (با کپی پیوست) |
| POST | `/api/messages/:id/pin` | `{pin:true/false}` |

### 4.5 مدیا / اعلان / جستجو
| متد | مسیر | توضیح |
|---|---|---|
| POST | `/api/upload` | `multipart/form-data`: `file` + `meta?` → `{att}` (محدودیت ۲۵MB، اعتبارسنجی پسوند/MIME) |
| GET | `/api/media/:id[?token=]` | دانلود/استریم (هدر یا کوئری‌توکن برای `<img>/<video>`) با کنترل عضویت در چت |
| GET | `/api/notifications` | ۶۰ اعلان آخر |
| POST | `/api/notifications/read` | خواندن همه |
| GET | `/api/search?q=` | `{users[], messages[]}` (پیام‌ها با `chat_id` برای پرش) |

### 4.6 ادمین (`role=admin`)
| متد | مسیر | توضیح |
|---|---|---|
| GET | `/api/admin/stats` | `{users, messages, online, regs_day, series[14]}` |
| GET | `/api/admin/users?q=` | لیست + جستجو |
| POST | `/api/admin/users/:id/action` | `{act: ban\|unban\|suspend\|delete}` |
| GET | `/api/admin/reports` | گزارش‌ها با نام گزارش‌دهنده/شونده |
| POST | `/api/admin/reports/:id/resolve` | بستن گزارش |
| POST | `/api/admin/broadcast` | `{text}` اعلان سیستمی برای همه |

### 4.7 WebSocket — `GET /ws?token=...`
پیام‌های کلاینت→سرور: `{t:"ping"}`، `{t:"typing", chat_id}`.
رویدادهای سرور→کلاینت:

| `t` | payload | معنی |
|---|---|---|
| `msg` | `{msg}` | پیام جدید/ویرایش (جایگزینی با `id`) |
| `react` | `{id, chat_id, reactions}` | تغییر ری‌اکشن‌ها |
| `pin` | `{chat_id, pins[]}` | تغییر سنجاق‌ها |
| `deleted_all` | `{id, chat_id}` | حذف برای همه |
| `read` | `{chat_id, reader, up_to}` | رسید خواندن (تیک آبی) |
| `typing` | `{chat_id, uid, name}` | در حال نوشتن |
| `presence` | `{uid, online}` | تغییر وضعیت آنلاین |
| `notify` | `{kind, payload}` | اعلان جدید |

## 5. اجرای محلی (Local)

```bash
# بدون هیچ وابستگی (فقط python3)
cd unmute/server
UM_DEV=1 UM_DATA=/tmp/umdata UM_PORT=8788 python3 run.py
# → http://127.0.0.1:8788  (صفحه ورود)
```

تست خودکار بک‌اند (ثبت‌نام ۲ کاربر، چت، تیک‌ها، ری‌اکشن، ویرایش، آپلود، ادمین، WS):

```bash
# در ترمینال دیگر، با همان سرور بالا:
python3 /tmp/umtest.py   # در محیط توسعه موجود است؛ یا همان سناریو با curl
```

## 6. متغیرهای محیطی

| متغیر | پیش‌فرض | توضیح |
|---|---|---|
| `UM_PORT` | `8788` | پورت گوش‌دادن (VPS: 8788) |
| `UM_DATA` | `unmute/data` | مسیر دیتابیس `unmute.db` و پوشه `media/` |
| `UM_DEV` | `0` | اگر `1`: فعال‌سازی `/api/dev/inbox` (دیدن کدهای ایمیل بدون SMTP) |
| `UM_ADMIN_USERNAME` | — | اگر ست شود، کاربری با این یوزرنیم در ثبت‌نام `admin` می‌شود (نفر اول همیشه ادمین است) |

## 7. دیپلوی روی VPS

تک‌دستوری (فقط `/opt/unmute` و پورت `8788`؛ دست به nginx/80/443 نمی‌زند):

```bash
curl -fsSL https://raw.githubusercontent.com/HOTKYNTAKY/MUNU/arena/01a0d918-munu/unmute/server/update.sh -o /tmp/u.sh && bash /tmp/u.sh
```

بعد از اجرا: `http://89.251.8.193:8788/` و `http://gavidan.norkhizstudio.com:8788/`
لاگ: `/opt/unmute/unmute.log` — دیتا: `/opt/unmute/data/` (آپدیت‌ها دیتا را نگه می‌دارند).

## 8. چک‌لیست امنیتی

- [x] هش رمز با `PBKDF2-HMAC-SHA256` (۲۰۰هزار تکرار) + salt تصادفی به‌ازای هر کاربر
- [x] توکن نشست `secrets.token_urlsafe(26)`، انقضا (۱ روزه / ۳۰ روزه Remember)، ابطال تکی/همه
- [x] `compare_digest` برای مقایسه هش؛ بدون ذخیره رمز در فرانت (فقط توکن)
- [x] RateLimit: احراز هویت ۱۰/دقیقه/IP، کل API حدود ۴۰۰/دقیقه/IP
- [x] اعتبارسنجی همه ورودی‌ها (regex یوزرنیم/ایمیل، سقف طول متن ۴۰۰۰، سقف صفحه‌بندی)
- [x] آپلود: لیست سفید پسوند + بررسی MIME + سقف ۲۵MB + نام‌فایل sanitizeشده
- [x] Authorization همه عملیات: عضویت در چت، مالکیت پیام/پیوست، گارد ادمین، احترام به بلاک و حریم خصوصی
- [x] XSS: همه رندرهای فرانت با `esc()`؛ مارک‌داون محدود (`**`، کد، لینک امن `rel=noopener`)
- [x] CSRF: احراز هویت با هدر `Authorization` (نه کوکی) → سرفِ cross-site بی‌اثر است
- [x] مدیا فقط برای اعضا (`?token=` کوتاه‌مدت در URL تگ‌ها؛ قابل ابطال با logout)
- [x] خطاها بدون نشت جزئیات داخلی (کدهای خطای استاندارد)
- [ ] موارد آینده (اختیاری): Same-origin پشت reverse-proxy + TLS، بستن `UM_DEV` در پروداکشن (پیش‌فرض بسته است)، بکاپ دوره‌ای `data/`

## 9. بخش‌های نیازمند سرویس خارجی (Integration Layer آماده)

| قابلیت | وضعیت فعلی | اتصال آینده |
|---|---|---|
| ارسال ایمیل (تأیید/بازیابی) | کد در دیتابیس + `/api/dev/inbox` (حالت DEV) | اتصال SMTP در `api.forgot/register/change_email` (یک تابع `send_mail()` کافی است) |
| Push Notification واقعی | اعلان مرورگر + بج + صدا (داخلی) | افزودن VAPID در `sw.js` + ذخیره subscription (جدول جدید) |
| Object Storage/CDN | فایل‌ها روی دیسک `data/media` | جایگزینی `open(path)` در `api2.upload/media` با کلاینت S3 (رابط `path` حفظ می‌شود) |
| دیتابیس مقیاس‌پذیر | SQLite/WAL (کافی تا ده‌ها هزار کاربر) | مهاجرت به Postgres: فقط `db.py` + اندکی SQL (کوئری‌ها استاندارد نوشته شده‌اند) |
| فونت فارسی | CDN گوگل (Vazirmatn) با fallback سیستمی | — (آفلاین هم با fallback کار می‌کند) |

---

ساخته‌شده با ♥ برای محصول واقعی، نه دمو.
