Mahali ERP API — one SaaS platform for every merchant (Mauritania). This page is the
contract for the web app: it is generated from the code and redeployed on every merge,
so it is always current. Changes are listed in
[CHANGELOG.md](https://github.com/khalefmed/mahali_erp_backend/blob/main/CHANGELOG.md).

**Machine-readable:** `GET /api/schema/` (OpenAPI 3, YAML; `?format=json` for JSON).
Generate the web client with `OPENAPI_URL=<this host>/api/schema/ pnpm api:generate`.

## Conventions

- Base path `/api/v1/`. IDs are UUIDs. Money is **integer MRU** (VAT included).
  Quantities are decimal strings (`"1.000"`). Dates ISO 8601, UTC.
- Store data lives under `/stores/{store_id}/…`. A store you cannot access answers
  **404** (it does not exist for you).
- Console (Mahali team) routes live under `/console/…` with their own login.
- Lists are paginated: `?page=&page_size=` (max 100) →
  `{count, next, previous, results}`.

## Errors

Every error is an RFC 9457 problem (`application/problem+json`):

```json
{"type": "about:blank", "status": 409, "code": "insufficient_stock",
 "title": "Insufficient stock", "detail": "Only 2 in stock.", "available": "2.000"}
```

- Translate **`code`** in the UI (fr / ar / en). Never show `detail` (developer text).
- Validation: `code = "validation_error"` and `errors: [{field, code, detail}]`,
  where `field` is a dotted path (`lines.0.serial`).
- Some errors carry extra keys (`attempts_left`, `missing`, `permission`,
  `store_status`, `available`, `retry_after`…). Each endpoint lists its codes.

## Authentication

1. `POST auth/register` → 202 (always, even if the email exists). A 6-digit code is
   emailed. `POST auth/verify-email` → `{access, refresh, user}` (signed in).
2. `POST auth/login` → `{access, refresh, user}`. Errors: `invalid_credentials` (401),
   `email_not_verified` (403 → resend with `auth/resend-code`).
3. Send `Authorization: Bearer <access>`. Access tokens last **10 minutes**.
4. `POST auth/refresh {refresh}` → a **new** `{access, refresh}`. The old refresh token
   is dead; reusing it revokes the whole session (theft protection). Refresh once at a
   time per session (avoid parallel refreshes).
5. `POST auth/logout {refresh}`. `GET/DELETE me/sessions` lists / signs out devices.
6. `401` with `code` `session_revoked` or `token_not_valid` → back to login.

The web keeps tokens in **httpOnly cookies on the Worker** and calls the API server-side;
CORS is not open to browsers.

## After login: which screen?

`GET /me/stores` → `[{store, role, permissions[], is_owner}]`.

| Situation | Screen |
| --- | --- |
| Empty list | Create a store (`POST /stores`) |
| `draft`, `info_requested` | Documents — AUTH-12 (`GET /stores/{id}/onboarding`, upload `POST /stores/{id}/documents`, then `POST /stores/{id}/submit`) |
| `pending_approval` | Waiting — AUTH-11 |
| `rejected` | Show `decision_message` |
| `active` | The ERP |
| `suspended`, `archived` | ERP read-only (writes → 403 `store_read_only`) |

Hide or disable UI with `permissions` (e.g. `sales.create`, `stock.receive`,
`costs.view`); the API enforces them anyway (403 `permission_denied` + `permission`).

`GET /platform` (no auth): `announcement` banner to show everywhere and
`signups_open`.

## Typical flows

- **Add a product:** search the Mahali catalog `GET /catalog/products?search=&trade=`,
  then `POST /stores/{id}/products {variant_id, sale_price, condition}`. Missing from the
  catalog → `POST /stores/{id}/product-requests`.
- **Receive stock:** `POST /stores/{id}/receipts` with lines `{store_product, quantity,
  unit_cost, serials[]}` (one IMEI per unit for phones, laptops, consoles…).
- **Sell:** `POST cash-sessions {opening_float}` → find the item with
  `GET products?barcode=` or `GET serials?serial=<IMEI>` → `POST sales {lines, payments,
  customer?}` → at the end `POST cash-sessions/{id}/close {counted_cash}` (Z report).
  Unpaid remainder becomes a credit (needs a customer). Corrections: `POST credit-notes`.
- **Dashboard / reports:** `GET /stores/{id}/reports/summary?date_from=&date_to=`.

## Marketplace

One shop window for every store, sold under the Mahali brand: **stores are never shown**.
A product's price is the cheapest store that has it in stock **plus the Mahali margin**
(one percentage, set in `console/settings` → `marketplace_margin_percent`), rounded up to
the MRU. Payment on delivery.

- **Browse (no login):** `GET marketplace/categories` (with `product_count` in stock),
  `GET marketplace/products?search=&trade=&category=<slug>&brand=<slug>&min_price=&max_price=&ordering=price|-price|-created_at`,
  `GET marketplace/products/{id}` (variants with `price`, `available`, `max_quantity`).
- **Cart:** kept by the app. `POST marketplace/cart/quote {lines: [{variant, quantity}]}`
  prices it and flags unavailable lines.
- **Shopper account:** `marketplace/auth/register` → `marketplace/auth/verify-email` (or
  `marketplace/auth/login`) → customer tokens (`auth/refresh` to rotate,
  `marketplace/auth/logout`). Merchant and customer tokens are not interchangeable.
- **Order:** `POST marketplace/orders {lines, delivery_name, delivery_phone, delivery_city,
  delivery_address, note?}`. Prices are fixed at that moment. Status: `pending` (stores
  confirming) → `confirmed` → `ready` → `delivered`, or `cancelled` (shopper while
  pending/confirmed, a store rejecting its part, or Mahali).
- **Store side (ERP):** `GET stores/{id}/marketplace-orders` — the store's part at its
  own prices, no customer data. `accept` (takes stock out; `serials` for products that
  track them), `reject {reason}` (cancels the whole order), `ready`. Permission
  `marketplace.orders` (owner, manager, stock keeper).
- **Console:** `GET console/marketplace/orders` (with the stores to collect from),
  `deliver`, `cancel {reason}` (stock goes back to the stores).

## Environments

| | URL |
| --- | --- |
| Staging | https://mahali-api-staging.infinity.mr |
| Local | http://localhost:8000 |

Something missing or wrong? Open an issue on
[khalefmed/mahali_erp_backend](https://github.com/khalefmed/mahali_erp_backend/issues).
