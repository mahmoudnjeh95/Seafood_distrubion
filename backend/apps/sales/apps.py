from django.apps import AppConfig


class SalesConfig(AppConfig):
    name = "apps.sales"
    label = "sales"
    verbose_name = "Ventes"

    def ready(self) -> None:
        # A new organization gets its first finance settings version (D-056).
        from . import printing, signals  # noqa: F401

        # The PDFs of quotes, invoices, credit notes and receipts (P2-T08).
        printing.register_printables()
        # The documents files can be attached to (D-288).
        printing.register_attachables()
