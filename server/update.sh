#!/bin/bash
# Gard Javidan — safe updater: restart panel + open without port
cd /opt/gard || { echo "FATAL: /opt/gard not found"; exit 1; }
B=https://raw.githubusercontent.com/HOTKYNTAKY/MUNU/arena/01a0d918-munu

echo "== 1) restart panel"
kill $(cat gard.pid 2>/dev/null) 2>/dev/null || true
sleep 1
nohup python3 panel_server.py 8787 > gard.log 2>&1 &
echo $! > gard.pid
sleep 2
tail -2 gard.log

echo "== 2) open without port"
if command -v nginx >/dev/null 2>&1; then
  echo "nginx found"
  curl -fsSL $B/server/gavidan.conf -o /etc/nginx/conf.d/gavidan.conf || { echo "conf download failed"; exit 1; }
  if nginx -t 2>/dev/null; then
    systemctl reload nginx && echo "OK-NGINX: http://gavidan.norkhizstudio.com"
    command -v certbot >/dev/null 2>&1 || apt-get install -y certbot python3-certbot-nginx >/dev/null 2>&1 || true
    if command -v certbot >/dev/null 2>&1; then
      certbot --nginx -d gavidan.norkhizstudio.com --non-interactive --agree-tos --register-unsafely-without-email --redirect && echo "OK-HTTPS: https://gavidan.norkhizstudio.com" || echo "certbot failed; http still works"
    fi
  else
    echo "nginx test failed; removing our conf (pasargad untouched)"
    rm -f /etc/nginx/conf.d/gavidan.conf
    nginx -t 2>&1 | tail -1
  fi
else
  echo "no nginx; using cloud tunnel"
  if [ ! -f /usr/local/bin/cloudflared ]; then
    curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared || { echo "cloudflared download failed"; exit 1; }
  fi
  chmod +x /usr/local/bin/cloudflared
  kill $(cat tunnel.pid 2>/dev/null) 2>/dev/null || true
  nohup /usr/local/bin/cloudflared tunnel --url http://127.0.0.1:8787 > tunnel.log 2>&1 &
  echo $! > tunnel.pid
  sleep 7
  echo "OK-TUNNEL:"
  grep -oE "https://[a-zA-Z0-9.-]+\.trycloudflare\.com" tunnel.log | tail -1
  ( crontab -l 2>/dev/null | grep -v cloudflared; echo "@reboot nohup /usr/local/bin/cloudflared tunnel --url http://127.0.0.1:8787 >> /opt/gard/tunnel.log 2>&1 &" ) | crontab -
fi
echo "== DONE"
