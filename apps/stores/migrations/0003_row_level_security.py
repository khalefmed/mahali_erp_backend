from django.db import migrations

from apps.core.rls import EnableRowLevelSecurity


class Migration(migrations.Migration):
    """Store isolation: see apps/core/tenancy.py."""

    dependencies = [("stores", "0002_store_settings_role_policies")]

    operations = [
        EnableRowLevelSecurity("rolepolicy"),
        EnableRowLevelSecurity("storesettings"),
    ]
