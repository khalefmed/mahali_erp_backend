from django.db import migrations

from apps.core.rls import EnableRowLevelSecurity


class Migration(migrations.Migration):
    """Store isolation: see apps/core/tenancy.py."""

    dependencies = [("sales", "0002_initial")]

    operations = [
        EnableRowLevelSecurity("cashsession"),
        EnableRowLevelSecurity("credit"),
        EnableRowLevelSecurity("creditnote"),
        EnableRowLevelSecurity("creditnoteline"),
        EnableRowLevelSecurity("customer"),
        EnableRowLevelSecurity("expense"),
        EnableRowLevelSecurity("payment"),
        EnableRowLevelSecurity("sale"),
        EnableRowLevelSecurity("saleline"),
    ]
