from django.apps import AppConfig


class PurchasingConfig(AppConfig):
    name = "apps.purchasing"
    label = "purchasing"
    verbose_name = "Achats"

    def ready(self) -> None:
        from . import printing

        # The PDF receipt of a supplier règlement (P9-T03c).
        printing.register_printables()
