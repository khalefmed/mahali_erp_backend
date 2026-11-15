# API changelog

Every change the web app should know about (new or changed endpoints, fields, error
codes). Newest first. The full contract is always at `/api/schema/` on each environment.

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
