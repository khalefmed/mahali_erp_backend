from django.db import connection
from django.utils import timezone

from .models import DocumentSequence


def next_number(store_id, prefix: str, *, monthly: bool = False, width: int = 4) -> str:
    """Next gapless document number, e.g. ``V-2611-0042`` (monthly) or ``CR-0007``.

    The counter row stays locked until the transaction commits, so two tills selling
    at the same time get different numbers and a rolled-back sale frees its number.
    """
    series = f"{prefix}-{timezone.localdate():%y%m}" if monthly else prefix
    table = DocumentSequence._meta.db_table  # a model constant; values are parameters
    sql = (
        f"INSERT INTO {table} (store_id, series, last_value) VALUES (%s, %s, 1) "  # noqa: S608  # nosec B608
        f"ON CONFLICT (store_id, series) DO UPDATE SET last_value = {table}.last_value + 1 "
        "RETURNING last_value"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, [str(store_id), series])
        value = cursor.fetchone()[0]
    return f"{series}-{value:0{width}d}"
