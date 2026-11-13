# API changelog

Every change the web app should know about (new or changed endpoints, fields, error
codes). Newest first. The full contract is always at `/api/schema/` on each environment.

## 2026-11-13

- `GET /platform` (public): `announcement`, `signups_open`. Register and store creation
  answer 403 `signups_closed` when the Mahali team closes sign-ups.
- Public docs: `/api/docs/` (Swagger), `/api/redoc/` (guide + reference), `/api/schema/`.
- First version of the API (PR #16): auth, onboarding and review, console, catalog,
  inventory with IMEI, till, sales, credits, credit notes, expenses, reports.
