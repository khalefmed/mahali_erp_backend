"""Store isolation is enforced by PostgreSQL itself. These tests fail if a store-scoped
table is added without its row-level security migration."""

import pytest
from django.apps import apps
from django.db import connection

from apps.core.models import DocumentSequence, StoreScopedModel
from apps.core.tenancy import store_context
from apps.sales.models import Customer
from conftest import make_store, make_user

pytestmark = pytest.mark.django_db


def scoped_tables():
    models = [m for m in apps.get_models() if issubclass(m, StoreScopedModel)]
    return [m._meta.db_table for m in [*models, DocumentSequence]]


def test_every_store_scoped_table_has_forced_rls():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname FROM pg_class WHERE relname = ANY(%s) "
            "AND relrowsecurity AND relforcerowsecurity",
            [scoped_tables()],
        )
        protected = {row[0] for row in cursor.fetchall()}
    assert set(scoped_tables()) - protected == set()


def test_app_role_cannot_bypass_rls():
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        assert cursor.fetchone() == (False, False)


def test_a_store_never_sees_another_store_rows():
    store_a = make_store(make_user("a@example.com"), name="A")
    store_b = make_store(make_user("b@example.com"), name="B")
    with store_context(store_a.id):
        Customer.objects.create(store=store_a, name="Client de A")
    with store_context(store_b.id):
        Customer.objects.create(store=store_b, name="Client de B")
        assert list(Customer.objects.values_list("name", flat=True)) == ["Client de B"]
    with store_context(store_a.id):
        assert list(Customer.objects.values_list("name", flat=True)) == ["Client de A"]


def test_no_store_activated_means_no_rows_and_no_writes():
    store = make_store(make_user())
    with store_context(store.id):
        Customer.objects.create(store=store, name="X")
    assert Customer.objects.count() == 0


def test_cannot_write_a_row_for_another_store():
    store_a = make_store(make_user("a@example.com"), name="A")
    store_b = make_store(make_user("b@example.com"), name="B")
    from django.db import DatabaseError, transaction

    with pytest.raises(DatabaseError), store_context(store_a.id), transaction.atomic():
        Customer.objects.create(store=store_b, name="Intrus")
