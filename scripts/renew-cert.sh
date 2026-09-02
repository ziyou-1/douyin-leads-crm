#!/bin/bash
# Let's Encrypt 证书自动续期脚本，由 crontab 定时调用。
# 续期成功后 reload nginx 让新证书生效(certbot本身不会通知nginx容器)。
set -euo pipefail

cd "$(dirname "$0")/.."

LOG_FILE="/var/log/certbot-renew.log"

{
    echo "==== $(date '+%Y-%m-%d %H:%M:%S') ===="
    docker compose run --rm certbot renew --webroot -w /var/www/certbot --quiet
    docker compose exec nginx nginx -s reload
    echo "renew check done"
} >> "$LOG_FILE" 2>&1
