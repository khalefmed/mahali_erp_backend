#!/usr/bin/env bash
# One-time setup of a Mahali environment on the shared VPS (run as ubuntu, with sudo):
#
#   ssh ubuntu@<vps> 'bash -s' -- staging "<github-actions public key>" < deploy/setup-vps.sh
#
# Only touches Mahali things: the `deploy` user, /opt/mahali, one nginx site.
# Other projects on the server (nginx sites, containers, SSH settings) are left alone.
# Safe to run again: existing secrets are kept.
set -euo pipefail
ENV_NAME="${1:-staging}"
CI_PUBLIC_KEY="${*:2}"  # all remaining args: ssh re-splits the key on spaces
[ -n "$CI_PUBLIC_KEY" ] || { echo "GitHub Actions public key required" >&2; exit 1; }
# Vercel DNS (infinity.mr) only accepts one-level names: mahali-api[-staging].infinity.mr
DOMAIN="mahali-api-${ENV_NAME}.infinity.mr"
[ "$ENV_NAME" = production ] && DOMAIN="mahali-api.infinity.mr"
PORT=8010; [ "$ENV_NAME" = production ] && PORT=8011
DIR="/opt/mahali/${ENV_NAME}"

# 1. deploy user: SSH key only (password locked), can run docker
sudo useradd --create-home --shell /bin/bash deploy 2>/dev/null || true
sudo usermod -aG docker deploy
sudo passwd -l deploy >/dev/null
sudo install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
echo "$CI_PUBLIC_KEY" | sudo tee /home/deploy/.ssh/authorized_keys >/dev/null
sudo chown deploy:deploy /home/deploy/.ssh/authorized_keys
sudo chmod 600 /home/deploy/.ssh/authorized_keys

# 2. code
sudo install -d -o deploy -g deploy /opt/mahali /opt/mahali/backups
if [ ! -d "$DIR/.git" ]; then
  sudo -u deploy git clone -q https://github.com/khalefmed/mahali_erp_backend.git "$DIR"
fi
[ -d "$DIR/deploy" ] || { echo "deploy/ missing in $DIR: check out a commit that has it" >&2; exit 1; }

# 3. secrets, generated here so they never leave the server
if ! sudo test -f "$DIR/deploy/.env"; then
  r() { openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-50; }
  sudo -u deploy tee "$DIR/deploy/.env" >/dev/null <<ENV
MAHALI_ENV=${ENV_NAME}
API_BIND=127.0.0.1:${PORT}
POSTGRES_SUPERUSER_PASSWORD=$(r)
APP_DB_PASSWORD=$(r)
DJANGO_SECRET_KEY=$(r)
JWT_SIGNING_KEY=$(r)
DJANGO_ALLOWED_HOSTS=${DOMAIN},localhost
DJANGO_DEBUG=false
SECURE_SSL_REDIRECT=false
WEB_APP_URL=https://staging.mahali.infinity.mr
EMAIL_URL=consolemail://
DEFAULT_FROM_EMAIL=Mahali <no-reply@mahali.infinity.mr>
PWNED_PASSWORDS_CHECK=true
DJANGO_ADMIN_PATH=
SENTRY_DSN=
SENTRY_ENVIRONMENT=${ENV_NAME}
ENV
  sudo chmod 600 "$DIR/deploy/.env"
fi
if ! sudo test -f /opt/mahali/backup.key; then
  openssl rand -base64 48 | sudo tee /opt/mahali/backup.key >/dev/null
  sudo chown deploy /opt/mahali/backup.key && sudo chmod 600 /opt/mahali/backup.key
fi

# 4. nginx site (HTTP; run certbot once DNS points here)
SITE="/etc/nginx/sites-available/mahali-${ENV_NAME}"
if [ ! -f "$SITE" ]; then
  sed -e "s/mahali-api-staging.infinity.mr/${DOMAIN}/" -e "s/127.0.0.1:8010/127.0.0.1:${PORT}/" \
    "$DIR/deploy/nginx/mahali-staging.conf" | sudo tee "$SITE" >/dev/null
  sudo ln -sf "$SITE" "/etc/nginx/sites-enabled/mahali-${ENV_NAME}"
  sudo nginx -t && sudo systemctl reload nginx
fi

# 5. nightly backup at 02:30
CRON="30 2 * * * $DIR/deploy/backup.sh ${ENV_NAME} >> /opt/mahali/backups/backup.log 2>&1"
{ sudo crontab -u deploy -l 2>/dev/null || true; } | { grep -v "backup.sh ${ENV_NAME}" || true; } \
  | { cat; echo "$CRON"; } | sudo crontab -u deploy -

echo "Ready: $DIR (port ${PORT}, ${DOMAIN}). Next: deploy/deploy.sh ${ENV_NAME} <sha> as deploy."
echo "TLS once DNS resolves: sudo certbot --nginx --redirect -d ${DOMAIN}, then SECURE_SSL_REDIRECT=true in .env"
