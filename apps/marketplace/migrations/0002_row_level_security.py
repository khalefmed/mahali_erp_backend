from django.db import migrations

from apps.core.rls import AllowMarketplaceRead, EnableRowLevelSecurity


class Migration(migrations.Migration):
    """Store isolation (apps/core/tenancy.py) plus marketplace reads across stores
    (Mahali's console and the order status), SELECT only."""

    dependencies = [("marketplace", "0001_initial")]

    operations = [
        EnableRowLevelSecurity("storeorder"),
        EnableRowLevelSecurity("storeorderline"),
        AllowMarketplaceRead("storeorder"),
        AllowMarketplaceRead("storeorderline"),
    ]
