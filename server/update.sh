#!/bin/bash
# گارد جاویدان — نصب/به‌روزرسانی سایت هوش مصنوعی (جایگزین پنل قدیمی)
set -u
cd /opt/gard || { echo "FATAL: /opt/gard not found"; exit 1; }
B=https://raw.githubusercontent.com/HOTKYNTAKY/MUNU/arena/01a0d918-munu

echo "== دانلود نسخه جدید"
curl -fsSL $B/server/ai_server.py -o ai_server.py.new && echo "server OK" || { echo "server download FAILED"; exit 1; }
curl -fsSL $B/index.html -o index.html.new && echo "client OK" || { echo "client download FAILED"; exit 1; }
mv -f ai_server.py.new ai_server.py
mv -f index.html.new index.html

echo "== توقف سرویس‌های قدیمی"
kill $(cat gard.pid 2>/dev/null) 2>/dev/null || true
pkill -f "panel_server.py" 2>/dev/null || true
pkill -f "ai_server.py" 2>/dev/null || true
sleep 1

echo "== پاکسازی پنل قدیمی"
rm -rf panel_server.py msgs.json users.json sess.json logs.json media/ assets/

echo "== اجرای سایت هوش مصنوعی"
PORT=8787 nohup python3 ai_server.py > gard.log 2>&1 &
echo $! > gard.pid
sleep 2
tail -2 gard.log
if curl -s -m 5 http://127.0.0.1:8787/api/health >/dev/null 2>&1; then
  echo "✅ در حال اجرا"
  echo "🌐 با آی‌پی:  http://89.251.8.193:8787/"
  echo "🌐 با دامنه: http://gavidan.norkhizstudio.com:8787/"
else
  echo "❌ خطا در اجرا:"
  tail -8 gard.log
fi
echo "== DONE"
