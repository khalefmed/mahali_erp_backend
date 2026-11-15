"""Store isolation through PostgreSQL row-level security.

Every store-scoped table has a policy `store_id = current_setting('app.store_id')`.
`activate_store` sets that variable with SET LOCAL semantics, so it only lives until
the end of the current transaction (requests run in ATOMIC_REQUESTS transactions).
With no store activated, store-scoped tables return no rows and reject writes.
"""

from contextlib import contextmanager

from django.db import connection, transaction


def activate_store(store_id) -> None:
    if not connection.in_atomic_block:
        raise RuntimeError("activate_store() must run inside a transaction")
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.store_id', %s, true)", [str(store_id)])


def deactivate_store() -> None:
    if connection.in_atomic_block:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.store_id', '', true)")


def current_store_id() -> str | None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.store_id', true)")
        value = cursor.fetchone()[0]
    return value or None


@contextmanager
def store_context(store_id):
    """For scripts, commands and tests: run a block as one store."""
    with transaction.atomic():
        previous = current_store_id()
        activate_store(store_id)
        try:
            yield
        finally:
            if previous:
                activate_store(previous)
            else:
                deactivate_store()


def enable_marketplace_read() -> None:
    """Let this transaction READ the rows the marketplace needs across stores (offers,
    marketplace orders). Writes stay limited to the activated store: the extra policy
    (`apps.core.rls.AllowMarketplaceRead`) is FOR SELECT only. Lives until the end of the
    current transaction, like `activate_store`."""
    if not connection.in_atomic_block:
        raise RuntimeError("enable_marketplace_read() must run inside a transaction")
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.marketplace_read', 'on', true)")


@contextmanager
def marketplace_read():
    """Cross-store reads for one block (services, commands, tests)."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('app.marketplace_read', true)")
            previous = cursor.fetchone()[0] or ""
        enable_marketplace_read()
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.marketplace_read', %s, true)", [previous])
