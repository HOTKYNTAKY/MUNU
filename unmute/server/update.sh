#!/bin/bash
# Unmute — نصب/به‌روزرسانی پیام‌رسان (پورت 8788، بدون دستکاری nginx و پورت‌های 80/443)
set -u
mkdir -p /opt/unmute/server /opt/unmute/web /opt/unmute/data/media
cd /opt/unmute || { echo "FATAL: /opt/unmute"; exit 1; }
B=https://raw.githubusercontent.com/HOTKYNTAKY/MUNU/arena/01a0d918-munu/unmute

echo "== دانلود نسخه جدید"
ok=1
for b in db.py util.py wsproto.py api.py api2.py run.py; do
  curl -fsSL $B/server/$b -o server/$b.new && mv -f server/$b.new server/$b && echo "  $b OK" || { echo "  $b FAILED"; ok=0; }
done
for b in index.html app.js chat.js views.js i18n.js style.css sw.js manifest.webmanifest logo.svg; do
  curl -fsSL $B/web/$b -o web/$b.new && mv -f web/$b.new web/$b && echo "  $b OK" || { echo "  $b FAILED"; ok=0; }
done
[ $ok -eq 0 ] && { echo "❌ دانلود ناقص ماند"; exit 1; }

echo "== توقف نسخه قبلی (فقط خودمان)"
kill $(cat unmute.pid 2>/dev/null) 2>/dev/null || true
pkill -f "opt/unmute/server/run.py" 2>/dev/null || true
sleep 1

echo "== اجرا"
cd /opt/unmute/server
 UM_PORT=8788 UM_DATA=/opt/unmute/data nohup python3 run.py > /opt/unmute/unmute.log 2>&1 &
echo $! > /opt/unmute/unmute.pid
sleep 2
tail -2 /opt/unmute/unmute.log
if curl -s -m 5 http://127.0.0.1:8788/api/health | grep -q '"ok": *true'; then
  echo "✅ Unmute در حال اجرا"
  echo "🌐 با آی‌پی:  http://89.251.8.193:8788/"
  echo "🌐 با دامنه: http://gavidan.norkhizstudio.com:8788/"
else
  echo "❌ خطا در اجرا:"
  tail -8 /opt/unmute/unmute.log
fi
echo "== DONE"
