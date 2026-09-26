#!/bin/bash
# Gard Javidan — IP-only mode: remove domain/tunnel/https, run plain HTTP on 8787
cd /opt/gard || { echo "FATAL: /opt/gard not found"; exit 1; }

echo "== cleanup domain stuff"
rm -f cert.pem key.pem
if [ -f /etc/nginx/conf.d/gavidan.conf ]; then
  rm -f /etc/nginx/conf.d/gavidan.conf
  if command -v nginx >/dev/null 2>&1 && nginx -t 2>/dev/null; then
    systemctl reload nginx && echo "nginx vhost removed"
  fi
fi
if [ -f tunnel.pid ]; then
  kill $(cat tunnel.pid) 2>/dev/null || true
  rm -f tunnel.pid
  echo "tunnel stopped"
fi
( crontab -l 2>/dev/null | grep -v cloudflared ) | crontab - 2>/dev/null || true

echo "== download latest code"
B=https://raw.githubusercontent.com/HOTKYNTAKY/MUNU/arena/01a0d918-munu
curl -fsSL $B/server/panel_server.py -o panel_server.py && echo "server code updated" || echo "server download failed"
curl -fsSL $B/index.html -o index.html && echo "client code updated" || echo "client download failed"
mkdir -p assets
curl -fsSL $B/assets/flag.png -o assets/flag.png 2>/dev/null || echo "flag download failed"

echo "== restart panel (plain HTTP)"
kill $(cat gard.pid 2>/dev/null) 2>/dev/null || true
sleep 1
nohup python3 panel_server.py 8787 > gard.log 2>&1 &
echo $! > gard.pid
sleep 2
tail -2 gard.log
echo "OK-IP: http://89.251.8.193:8787/"
echo "== DONE"
