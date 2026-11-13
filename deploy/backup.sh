#!/usr/bin/env bash
# Nightly (cron on the VPS): encrypted Postgres dump + uploaded files (store documents),
# kept 14 days in /opt/mahali/backups. Copy that folder off the server too.
# Restore: gpg -d <file> | gunzip | docker compose exec -T db psql -U postgres -d mahali
#          gpg -d <media file> | docker compose run --rm -T api tar -xzf - -C /data/media
set -euo pipefail
ENV_NAME="${1:-staging}"
OUT=/opt/mahali/backups; mkdir -p "$OUT"
STAMP="$(date +%Y%m%d-%H%M)"
KEY=/opt/mahali/backup.key
encrypt() { gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-file "$KEY" -o "$1"; }
cd "/opt/mahali/${ENV_NAME}/deploy"
docker compose exec -T db pg_dump -U postgres -d mahali --no-owner \
  | gzip | encrypt "$OUT/${ENV_NAME}-db-${STAMP}.sql.gz.gpg"
docker compose exec -T api tar -czf - -C /data/media . \
  | encrypt "$OUT/${ENV_NAME}-media-${STAMP}.tar.gz.gpg"
find "$OUT" -name "${ENV_NAME}-*.gpg" -mtime +14 -delete
echo "backup ${ENV_NAME} ${STAMP} ok"
