from django.contrib.postgres.operations import CreateExtension
from django.db import migrations

from apps.core.rls import EnableRowLevelSecurity


class Migration(migrations.Migration):
    """Store isolation: see apps/core/tenancy.py."""

    dependencies = [("core", "0002_initial")]

    operations = [
        CreateExtension("unaccent"),
        CreateExtension("pg_trgm"),
        EnableRowLevelSecurity("documentsequence"),
    ]
