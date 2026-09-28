#!/usr/bin/env bash
# نصب خودکار ربات فروش فیلترشکن روی اوبونتو/دبیان
# اجرا: sudo bash install.sh  (از داخل همین پوشه)
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="vpnbot"

if [ "$EUID" -ne 0 ]; then
  echo "❌ با sudo اجرا کن: sudo bash install.sh"
  exit 1
fi

echo "📦 نصب پیش‌نیازها..."
apt-get update -y
apt-get install -y python3 python3-venv python3-pip sqlite3

echo "🐍 ساخت محیط مجازی..."
if [ ! -d "$APP_DIR/venv" ]; then
  python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

mkdir -p "$APP_DIR/data" "$APP_DIR/backups"

# ویزارد ساخت .env (فقط اگر وجود ندارد) — توکن و آیدی ادمین را می‌پرسد
if [ ! -f "$APP_DIR/.env" ]; then
  echo ""
  "$APP_DIR/venv/bin/python" "$APP_DIR/config.py"
else
  echo "✅ فایل .env از قبل وجود دارد."
fi

echo "⚙️ نصب سرویس systemd..."
sed "s|/opt/vpnbot|$APP_DIR|g" "$APP_DIR/vpnbot.service" > "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

echo ""
echo "✅ نصب تمام شد! وضعیت سرویس:"
systemctl --no-pager -l status "$SERVICE_NAME" | head -12
echo ""
echo "📋 دستورات مفید:"
echo "  sudo systemctl status $SERVICE_NAME     # وضعیت"
echo "  sudo systemctl restart $SERVICE_NAME    # ریستارت"
echo "  sudo journalctl -u $SERVICE_NAME -f     # مشاهده لاگ زنده"
