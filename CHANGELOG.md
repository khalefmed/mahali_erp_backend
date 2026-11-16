# API changelog

Every change the web app should know about (new or changed endpoints, fields, error
codes). Newest first. The full contract is always at `/api/schema/` on each environment.

## 2026-11-16 — Meysara: e-KYC (simulated) and BCM ceilings (Instruction n°13/GR/2025)

- New `marketplace: identity` routes (customer tokens): `GET marketplace/identity`,
  `POST marketplace/identity` (details + `consent`), `POST marketplace/identity/phone/verify`,
  `POST marketplace/identity/phone/resend`, `POST marketplace/identity/documents` (multipart).
  Responses: `{identity, simulation_code}`. Errors: `consent_required`, `invalid_nni`,
  `invalid_phone`, `underage`, `nni_already_used` (409), `identity_already_verified` (409),
  `invalid_code` (`attempts_left`), `code_expired`, `identity_not_started`,
  `identity_step_done` (409), `identity_wrong_step` (409), `unsupported_file_type`,
  `file_too_large`. Codes sent: 5 per hour per shopper (429).
- The provider is simulated: `simulation_code` is the code it would send by SMS (show it as a
  demo hint), NNIs starting with `000` end `rejected` (`reject_reason: document_unreadable`).
- `GET marketplace/meysara/offer`: new reason `meysara_identity_unverified` (after
  `meysara_history_insufficient`), new fields `identity_verified` and
  `regulatory_max_financed` (60 000). `choices` now leaves out a share whose financed amount
  would pass `max_financed` (before, 100 % could be chosen above the ceiling).
- `console/settings`: `meysara_max_financed` above 60 000 is refused (400).

## 2026-11-16 — ERP web back-office, lot 2 (#36)

Same contracts as the web app's `src/features/*/schemas.ts`:
- Treasury: `GET stores/{id}/money-accounts` (one account per payment method, `id` = the method
  code), `GET money-movements?date=` (signed amounts; a transfer gives two rows),
  `POST money-transfers` (owner; `same_account`). Transfers post a `misc` journal entry.
- Expenses: `GET|POST recurring-expenses`, `DELETE recurring-expenses/{id}`;
  `GET expense-budgets` and `PUT expense-budgets {results: [{category, amount}]}` (owner,
  replaces all). The daily command `post_recurring_expenses` records the due fixed charges;
  variable bills (`variable_amount`) only move to their next date.
- Store preferences, `GET` (any member) and `PATCH` (owner): `payment-settings`, `credit-policy`,
  `reminder-settings` (`before_due_days` read-only), `setup` (`{blank?, completed?}`).
  Saved only for now: the till doesn't enforce them and no reminder is sent (SMS later).
- `GET role-policies` (`members.manage`), `PATCH role-policies/{role}` (owner; manager,
  cashier, seller, stock_keeper, else `invalid_role` 404). Defaults until changed.

## 2026-11-16 — ERP web back-office, lot 1 (#34)

Routes the web app already calls by hand (`src/features/*/schemas.ts`), same contracts:
- `GET stores/{id}/accounting/journal?date=`: the day's entries, posted from sales, payments,
  credit notes, expenses, receipts and supplier payments (SYSCOHADA accounts; `journal`
  `sales` · `purchases` · `cash` · `bank`).
- `GET stores/{id}/accounting/closing?date_from=&date_to=`: closing checklist and VAT
  declaration (`due_date` the 15th of the next month). Purchase VAT and bank statements aren't
  recorded yet: `vat_deductible` 0, `bank_reconciled` never done.
- `GET|POST stores/{id}/supplier-payments` (`suppliers.manage`): `supplier`, `amount`, `method`,
  `reference`, `note`. A cash payment needs my open till (`no_open_cash_session`) and lowers its
  `expected_cash`; Z totals gain `supplier_payments`.
- `GET stores/{id}/reports/details?date_from=&date_to=`: `sales_by_category` (VAT excluded),
  `dormant_products` (60 days), `supplier_payables` (receipts minus supplier payments).
- `GET stores/{id}/customers/{cid}/statement?date_from=&date_to=` (default this year) and
  `GET stores/{id}/customer-advances` (always empty: no deposits or store credit yet).
- `GET stores/{id}/member-activity` (`members.manage`) and
  `GET stores/{id}/seller-performance/me?month=YYYY-MM` (commission 0, no target yet).

## 2026-11-16 — Catalog photos and Arabic names; public Meysara rules (#31)

- `GET platform` gains `meysara_enabled`, `meysara_min_total`, `meysara_max_financed`,
  `meysara_required_orders`: show « ou 4 × … » only when Meysara is on and the amount is at
  least `meysara_min_total`. Eligibility itself still comes from `marketplace/meysara/offer`.
- `POST marketplace/cart/quote`: each line gains `image_url` (the product photo, or empty) for
  the cart and mini-cart thumbnails.
- Every catalog product now has `image_url` (square 1200 px JPEG under
  `/static/catalog/products/`) and `name_ar`. No schema change.

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
