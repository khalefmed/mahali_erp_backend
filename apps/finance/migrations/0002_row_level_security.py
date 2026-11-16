from django.db import migrations

from apps.core.rls import EnableRowLevelSecurity


class Migration(migrations.Migration):
    """Store isolation: see apps/core/tenancy.py."""

    dependencies = [("finance", "0001_initial")]

    operations = [EnableRowLevelSecurity("supplierpayment")]
