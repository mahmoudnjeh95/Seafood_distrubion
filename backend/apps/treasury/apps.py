from django.apps import AppConfig


class TreasuryConfig(AppConfig):
    name = "apps.treasury"
    label = "treasury"
    verbose_name = "Trésorerie"

    def ready(self) -> None:
        # A new organization gets the list of Tunisian banks (D-197).
        from . import (
            printing,
            signals,  # noqa: F401
        )

        # The PDF bordereau of a remise en banque (P9-T04a).
        printing.register_printables()
