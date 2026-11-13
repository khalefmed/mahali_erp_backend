# Mahali ERP — API backend

Django REST API for Mahali, an ERP for small shops in Mauritania, sold as one SaaS
platform for every merchant (the data will later feed the Mahali marketplace).
The web app is a separate repo (`khalefmed/mahali_erp_web`, TanStack Start on
Cloudflare Workers) and generates its typed client from `openapi/schema.yaml`.

- Figma "MAHALI ERP — Prototype" (file key `sgnapT3PC9sxuEtz9JN0ua`): auth (AUTH-01…12),
  Mahali console (SA-01…10), one page per trade.
- Trades: `telephones` (first, used for the demo), `electromenager`, `pharmacie`,
  `quincaillerie`. A store has exactly one trade, which fixes its catalog.

## Commands

```bash
docker compose up -d                       # Postgres 17 (non-superuser app role) + Redis
cp .env.example .env                       # first time
uv sync
uv run python manage.py migrate
uv run python manage.py seed_demo --password '<pwd>'   # Téléphones demo data
uv run python manage.py runserver          # http://localhost:8000/api/docs/
uv run pytest                              # all tests (reuses the test DB)
uv run pytest apps/sales/tests/test_selling.py -k imei   # one test
uv run ruff check . && uv run ruff format .
uv run python manage.py spectacular --file openapi/schema.yaml --validate --fail-on-warn
```

## Architecture

```
config/settings.py      one settings module, everything from env vars (.env.example)
apps/core               BaseModel/StoreScopedModel, RLS (tenancy.py, rls.py), RFC 9457
                        errors, OpenAPI AutoSchema, gapless numbering, audit, notify()
apps/accounts           User (email), email codes, sessions + JWT, throttles
apps/stores             Store, onboarding & documents, Membership, roles.py, access.py
apps/catalog            global catalog managed by Mahali: Category (attribute schema),
                        Brand, Product, Variant; ProductRequest ("Demander un produit")
apps/inventory          StoreProduct, SerialUnit (IMEI), StockMovement, Supplier, Receipt,
                        StockAdjustment — services.move() is the only way to change stock
apps/sales              Customer, CashSession (Z), Sale, Payment, Credit, CreditNote, Expense
apps/reports            read-only selectors
apps/console            Mahali team API (/api/v1/console/…): PlatformStaff, reviews, notes
```

Each app: `models.py`, `services.py` (writes, business rules, transactions),
`selectors.py` (complex reads), `serializers.py`, `views.py` (thin), `urls.py`,
`tests/`. Views call services; services never import views or serializers.

## Rules that must never break

**Store isolation is PostgreSQL row-level security.**
- Every table holding one store's data subclasses `StoreScopedModel` AND gets an
  `EnableRowLevelSecurity("<model>")` operation in a migration. `apps/core/tests/test_rls.py`
  fails otherwise.
- The DB role is not a superuser and has no BYPASSRLS (see `docker/postgres/init.sh`).
  Never run the app as `postgres`.
- Store-scoped views use `StoreScopedViewMixin` (route `stores/<store_id>/…`). Its
  `StoreAccess` permission checks membership + store status + permission, then runs
  `activate_store()` (SET LOCAL, lives until the request transaction ends).
  Outside requests (commands, tests) use `with store_context(store.id):`.
- With no store activated, store-scoped queries return nothing. Don't "fix" that.

**Permissions.** Roles and permission codes live only in `apps/stores/roles.py`.
Views declare `required_permissions = {action | METHOD | "*": Perm.X}`; console views
declare `console_permissions`. The web reads permissions from `GET /me/stores`.

**Errors.** Raise `ApiError(code, detail, status_code=…, extra={…})` (or `Conflict`,
`Forbidden`). `code` is a stable snake_case string the web translates in fr/ar/en —
never return user-facing text. Document new codes in the view's `extend_schema`.

**Money and stock.** Money is integer MRU (VAT included). Quantities are
`Decimal(12,3)`. Stock is never negative (service check + DB constraint) and only
changes through `inventory.services.move()` with locked rows (`lock_products`).
Sales, movements and audit events are immutable: corrections are credit notes.
Document numbers come from `core.sequences.next_number()` (gapless per store).

**Catalog is closed.** Merchants never create products: they add catalog variants to
their store (`stores/<id>/products`) or file a product request. Attributes are
validated against the category's `attribute_schema`.

**Auth.** Access JWT 10 min + rotating single-use refresh; each token carries `sid`
(a `UserSession`) and `realm` (`merchant` | `console`). Revoking the session kills its
tokens at once. Reusing an old refresh token revokes the session. Console accounts
are separate (`PlatformStaff`) and cannot use merchant routes, and vice versa.
Console "log in as" = read-only merchant session for one store, 30 min.

**Emails** go through `core.notifications.notify(user_or_email, template, ctx)`, sent
on commit; templates in `templates/notifications/`. SMS will plug in there later.

**OpenAPI is the contract.** After any API change, regenerate `openapi/schema.yaml`
(CI fails if it is stale or has warnings) and mention the change in the PR.

## Workflow: one issue → one branch → one PR

1. `gh issue view <n>`.
2. `git switch main && git pull --ff-only && git switch -c feat/<n>-short-name` (`fix/…`).
3. Build with tests. New store tables → RLS migration. New endpoint → schema.
4. `uv run ruff check . && uv run ruff format . && uv run pytest`, regenerate the schema.
5. PR with the template and `Closes #<n>`; CI green; the other person reviews and
   squash-merges. Merging to `main` deploys staging; a `v*` tag deploys production.

Never deploy by hand from a laptop. Never commit `.env` or anything from the VPS.
