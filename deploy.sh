#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "==> Docker build & up"
docker compose up -d --build

echo "==> Nginx vhost book.islanddream.ru -> :8001"
sudo cp "$ROOT/nginx.conf" /etc/nginx/sites-available/book.conf
sudo ln -sf /etc/nginx/sites-available/book.conf /etc/nginx/sites-enabled/book.conf
sudo nginx -t
sudo systemctl reload nginx

if ! sudo test -f "/etc/letsencrypt/live/book.islanddream.ru/fullchain.pem"; then
  echo "==> SSL (certbot)"
  sudo certbot --nginx -d book.islanddream.ru --non-interactive --agree-tos -m admin@islanddream.ru || \
    sudo certbot --nginx -d book.islanddream.ru
fi

echo "==> Health"
curl -fsS "http://127.0.0.1:8001/health"
echo
curl -fsSI "http://book.islanddream.ru/health" | head -5
echo "BookHub v0.1: https://book.islanddream.ru/"
