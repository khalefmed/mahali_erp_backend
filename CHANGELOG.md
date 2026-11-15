# API changelog

Every change the web app should know about (new or changed endpoints, fields, error
codes). Newest first. The full contract is always at `/api/schema/` on each environment.

## 2026-11-15 — Marketplace v2: Meysara, facets, shoppers' reset link (#27)

- **Meysara** (pay in 4, no fees): `GET marketplace/meysara/offer?total=` → `eligible`,
  `reason`, `max_percent`, `choices`, `paid_orders`, `required_orders`, `min_total`,
  `max_financed`. Reasons: `meysara_history_insufficient`, `meysara_overdue`,
  `meysara_plan_in_progress`, `meysara_amount_too_low`, `meysara_limit_exceeded`,
  `meysara_disabled`.
- `POST marketplace/orders`: `payment_method` (`cash_on_delivery` | `meysara`) and
  `meysara_percent`. New codes: `meysara_percent_required`, `meysara_not_allowed` (409, with
  `reason`, `choices`).
- Orders (shopper and console) get `meysara` (null when paid on delivery): `percent`,
  `financed`, `on_delivery`, `status` (`reserved` → `active` at delivery → `paid` /
  `cancelled`) and 4 `instalments` (`amount`, `due_date`, `paid_at`, `paid_via`, `status`:
  `waiting_delivery`, `upcoming`, `due`, `overdue`, `paid`).
- Console: `POST console/marketplace/orders/{id}/meysara/pay {number, via}` (`bankily`,
  `masrvi`, `sedad`, `cash`). Codes: `not_a_meysara_order`, `meysara_plan_not_active`,
  `invalid_instalment`, `instalment_already_paid`. `console/settings` gains
  `meysara_enabled`, `meysara_required_orders`, `meysara_min_total`, `meysara_max_financed`.
- `GET marketplace/products/facets` (same filters as the list): `brands` with counts
  (ignoring `brand`), `min_price`, `max_price`, `count`.
- `POST marketplace/auth/password/forgot`: link to
  `{MARKETPLACE_URL}/{lang}/mot-de-passe/nouveau?uid=&token=` (new setting `MARKETPLACE_URL`).

## 2026-11-15 — Marketplace v1 (PR for #25)

- Shop window, public: `GET marketplace/categories`, `GET marketplace/products`
  (search, filters, ordering), `GET marketplace/products/{id}`, `POST marketplace/cart/quote`.
  Price = cheapest store in stock + `marketplace_margin_percent`. Stores never appear.
- Shopper accounts (customer tokens): `marketplace/auth/register|verify-email|login|logout`,
  `GET/PATCH marketplace/me`.
- Orders: `POST/GET marketplace/orders`, `POST marketplace/orders/{id}/cancel`.
  New codes: `empty_cart`, `invalid_quantity`, `whole_quantity_required`,
  `insufficient_stock` (409, with `available`), `order_not_cancellable`.
- ERP: `stores/{id}/marketplace-orders` with `accept`, `reject`, `ready`; new permission
  `marketplace.orders` (in `GET /me/stores`). Codes: `store_order_not_pending`,
  `store_order_not_accepted`, `order_cancelled`, `serials_required`, `serial_not_in_stock`.
  Stock movements of kind `marketplace`.
- Console: `console/marketplace/orders` (+ `deliver`, `cancel`), `marketplace_margin_percent`
  in `console/settings`; permissions `marketplace.view`, `marketplace.manage`.
  Code: `order_not_ready`.

## 2026-11-13

- `GET /platform` (public): `announcement`, `signups_open`. Register and store creation
  answer 403 `signups_closed` when the Mahali team closes sign-ups.
- Public docs: `/api/docs/` (Swagger), `/api/redoc/` (guide + reference), `/api/schema/`.
- First version of the API (PR #16): auth, onboarding and review, console, catalog,
  inventory with IMEI, till, sales, credits, credit notes, expenses, reports.
