#!/usr/bin/env bash
# Runs ON THE VPS, called by GitHub Actions: deploy.sh <env> <git sha>
set -euo pipefail
ENV_NAME="$1"; SHA="$2"
cd "/opt/mahali/${ENV_NAME}"
git fetch --quiet origin
git checkout --quiet --force "$SHA"
cd deploy
docker compose build --quiet api
docker compose up -d db redis
docker compose run --rm api python manage.py migrate --noinput
docker compose up -d --remove-orphans
docker image prune -f >/dev/null
for i in $(seq 1 30); do
  if docker compose exec -T api python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://localhost:8000/health').status!=200)" 2>/dev/null; then
    echo "deployed ${SHA} to ${ENV_NAME}"; exit 0
  fi
  sleep 2
done
echo "health check failed" >&2; docker compose logs --tail 50 api >&2; exit 1
