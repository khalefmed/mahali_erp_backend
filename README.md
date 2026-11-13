# Mahali ERP — API

Django REST Framework backend of Mahali ERP. Interactive docs: `/api/docs/`,
OpenAPI schema: `/api/schema/` (snapshot committed in `openapi/schema.yaml`).

| Environment | URL |
| --- | --- |
| Local | http://localhost:8000/api/v1/ |
| Staging | https://mahali-api-staging.infinity.mr/api/v1/ (docs: `/api/docs/`) |

## Run it locally

Needs Docker, [uv](https://docs.astral.sh/uv/) and Python 3.13 (`uv python install 3.13`).

```bash
docker compose up -d            # Postgres 17 on :5433, Redis on :6381
cp .env.example .env
uv sync
uv run python manage.py migrate
uv run python manage.py seed_demo --password 'Demo-Mahali-2026'
uv run python manage.py runserver
```

`seed_demo` creates the Téléphones catalog, the shop **Sahel Phones** (stock, IMEIs,
7 days of sales) and a store waiting for review:

| Account | Email |
| --- | --- |
| Console super-admin | `admin@mahali.infinity.mr` |
| Owner of Sahel Phones | `demo@mahali.infinity.mr` |
| Cashier / stock keeper | `caisse@…` / `stock@mahali.infinity.mr` |
| Store pending review | `attente@mahali.infinity.mr` |

Emails (verification codes, invitations) are printed in the runserver console locally.

## For the web app

- Generate the client: `OPENAPI_URL=http://localhost:8000/api/schema/ pnpm api:generate`
  (or copy `openapi/schema.yaml` into the web repo).
- **Tokens.** `auth/login` and `auth/verify-email` return `{access, refresh, user}`.
  The Worker keeps both in `httpOnly` cookies and sends `Authorization: Bearer <access>`.
  Access lasts 10 min; call `auth/refresh` with the refresh token: it returns a **new**
  pair, and the old refresh token stops working (reusing it ends the session).
- **Which screen after login.** `GET /me/stores` lists stores with `status`, `role`
  and `permissions`. No store → onboarding (create a store). `draft`/`info_requested` →
  documents (AUTH-12, `GET /stores/{id}/onboarding`). `pending_approval` → waiting
  screen (AUTH-11). `active` → the ERP. `suspended`/`archived` → read-only.
- **Store routes** are `/stores/{store_id}/…`. A store you cannot access answers 404.
- **Errors** are RFC 9457 problem details. Translate `code`, never show `detail`.
  Validation errors list `errors[]` with `field` (dotted path, e.g. `lines.0.serial`)
  and `code`.
- Money: integer MRU. Quantities: decimal strings (`"1.000"`).
- Typical till flow: `POST cash-sessions` (opening float) → `GET products?barcode=` or
  `GET serials?serial=<IMEI>` → `POST sales` → `POST cash-sessions/{id}/close`.

## Deployment (VPS)

GitHub Actions deploys: push to `main` → staging, tag `v*` → production
(`.github/workflows/deploy.yml` → `deploy/deploy.sh` on the server). Stack:
`deploy/compose.yml` (Postgres, Redis, API under gunicorn on `127.0.0.1:8010`). The VPS
also hosts other projects: its existing nginx terminates TLS (certbot) and proxies to the
API (`deploy/nginx/mahali-staging.conf`). Don't bind ports 80/443 from this stack.
Server secrets are in `/opt/mahali/<env>/deploy/.env` (template: `deploy/env.example`).

### Backups

`deploy/backup.sh` runs nightly from cron: encrypted `pg_dump` kept 14 days in
`/opt/mahali/backups`, to be copied off the server. Test a restore every month.
