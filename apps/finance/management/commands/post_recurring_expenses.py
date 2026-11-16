"""Record the recurring charges that are due, in every active store. Idempotent: each
charge's next date moves on once posted. Meant to run daily (cron) until Celery.

    uv run python manage.py post_recurring_expenses
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.tenancy import store_context
from apps.finance.services import post_due_recurring
from apps.stores.models import Store, StoreStatus


class Command(BaseCommand):
    help = "Record due recurring expenses in every active store."

    def handle(self, *args, **options):
        today = timezone.localdate()
        total = 0
        for store_id in Store.objects.filter(status=StoreStatus.ACTIVE).values_list(
            "id", flat=True
        ):
            with store_context(store_id):
                total += post_due_recurring(today)
        self.stdout.write(self.style.SUCCESS(f"{total} expenses recorded"))
