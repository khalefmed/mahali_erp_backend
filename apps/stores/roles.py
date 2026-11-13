"""Store roles and what they can do. The single source of truth for permissions:
the web app reads them from `GET /me/stores` and only hides UI; the API enforces."""

from django.db import models


class Role(models.TextChoices):
    OWNER = "owner", "Propriétaire"
    MANAGER = "manager", "Gérant"
    CASHIER = "cashier", "Caissier"
    STOCK_KEEPER = "stock_keeper", "Magasinier"
    SELLER = "seller", "Vendeur"


class Perm:
    STORE_VIEW = "store.view"
    STORE_MANAGE = "store.manage"
    MEMBERS_MANAGE = "members.manage"
    PRODUCTS_VIEW = "products.view"
    PRODUCTS_MANAGE = "products.manage"
    PRICES_EDIT = "prices.edit"
    COSTS_VIEW = "costs.view"
    PRODUCT_REQUESTS_CREATE = "product_requests.create"
    STOCK_RECEIVE = "stock.receive"
    STOCK_ADJUST = "stock.adjust"
    SUPPLIERS_MANAGE = "suppliers.manage"
    CUSTOMERS_VIEW = "customers.view"
    CUSTOMERS_MANAGE = "customers.manage"
    CASH_SESSION = "cash.session"
    SALES_VIEW = "sales.view"
    SALES_CREATE = "sales.create"
    SALES_DISCOUNT_OVERRIDE = "sales.discount_override"
    SALES_REFUND = "sales.refund"
    CREDITS_MANAGE = "credits.manage"
    EXPENSES_MANAGE = "expenses.manage"
    REPORTS_VIEW = "reports.view"


_ALL = {v for k, v in vars(Perm).items() if k.isupper()}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.OWNER: frozenset(_ALL),
    Role.MANAGER: frozenset(_ALL - {Perm.STORE_MANAGE}),
    Role.CASHIER: frozenset(
        {
            Perm.STORE_VIEW,
            Perm.PRODUCTS_VIEW,
            Perm.CUSTOMERS_VIEW,
            Perm.CUSTOMERS_MANAGE,
            Perm.CASH_SESSION,
            Perm.SALES_VIEW,
            Perm.SALES_CREATE,
            Perm.CREDITS_MANAGE,
            Perm.EXPENSES_MANAGE,
        }
    ),
    Role.STOCK_KEEPER: frozenset(
        {
            Perm.STORE_VIEW,
            Perm.PRODUCTS_VIEW,
            Perm.PRODUCTS_MANAGE,
            Perm.COSTS_VIEW,
            Perm.PRODUCT_REQUESTS_CREATE,
            Perm.STOCK_RECEIVE,
            Perm.STOCK_ADJUST,
            Perm.SUPPLIERS_MANAGE,
        }
    ),
    Role.SELLER: frozenset(
        {
            Perm.STORE_VIEW,
            Perm.PRODUCTS_VIEW,
            Perm.CUSTOMERS_VIEW,
            Perm.CUSTOMERS_MANAGE,
            Perm.SALES_VIEW,
            Perm.SALES_CREATE,
        }
    ),
}

ALL_PERMISSIONS = sorted(_ALL)
INVITABLE_ROLES = [r for r in Role if r != Role.OWNER]
