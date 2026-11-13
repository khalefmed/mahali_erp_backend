#!/usr/bin/env bash
# Nightly (cron on the VPS): encrypted pg_dump, kept 14 days locally.
# Copy /opt/mahali/backups off the server (see README → Backups).
set -euo pipefail
ENV_NAME="${1:-staging}"
OUT=/opt/mahali/backups; mkdir -p "$OUT"
FILE="$OUT/${ENV_NAME}-$(date +%Y%m%d-%H%M).sql.gz.gpg"
cd "/opt/mahali/${ENV_NAME}/deploy"
docker compose exec -T db pg_dump -U postgres -d mahali --no-owner \
  | gzip | gpg --batch --yes --symmetric --cipher-algo AES256 \
      --passphrase-file /opt/mahali/backup.key -o "$FILE"
find "$OUT" -name "${ENV_NAME}-*.gpg" -mtime +14 -delete
