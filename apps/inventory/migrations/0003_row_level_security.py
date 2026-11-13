from django.db import migrations

from apps.core.rls import EnableRowLevelSecurity


class Migration(migrations.Migration):
    """Store isolation: see apps/core/tenancy.py."""

    dependencies = [("inventory", "0002_initial")]

    operations = [
        EnableRowLevelSecurity("receipt"),
        EnableRowLevelSecurity("receiptline"),
        EnableRowLevelSecurity("serialunit"),
        EnableRowLevelSecurity("stockadjustment"),
        EnableRowLevelSecurity("stockmovement"),
        EnableRowLevelSecurity("storeproduct"),
        EnableRowLevelSecurity("supplier"),
    ]
