from django.apps import AppConfig


class PartnersConfig(AppConfig):
    name = "apps.partners"
    label = "partners"
    verbose_name = "Partenaires"

    def ready(self) -> None:
        # A new organization gets the default customer types (D-283).
        from . import signals  # noqa: F401
