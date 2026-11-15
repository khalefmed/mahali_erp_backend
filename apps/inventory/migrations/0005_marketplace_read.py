from django.db import migrations

from apps.core.rls import AllowMarketplaceRead


class Migration(migrations.Migration):
    """The marketplace lists every store's offers (SELECT only, see apps/core/tenancy.py)."""

    dependencies = [("inventory", "0004_alter_stockmovement_kind")]

    operations = [AllowMarketplaceRead("storeproduct")]
