from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "apps.catalog"
    label = "catalog"
    verbose_name = "Catalogue"

    def ready(self) -> None:
        # A new organization gets the default VAT rates (D-283).
        from . import signals  # noqa: F401
