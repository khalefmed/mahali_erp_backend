from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        from . import schema  # noqa: F401 — registers OpenAPI auth extensions
