from django.db import migrations

from apps.core.rls import EnableRowLevelSecurity


class Migration(migrations.Migration):
    """Store isolation: see apps/core/tenancy.py."""

    dependencies = [("finance", "0003_recurring_budgets_transfers")]

    operations = [
        EnableRowLevelSecurity("expensebudget"),
        EnableRowLevelSecurity("moneytransfer"),
        EnableRowLevelSecurity("recurringexpense"),
    ]
