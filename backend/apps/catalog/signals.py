"""A new organization starts with the default VAT rates (D-283)."""

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core.models import Organization

from . import services


@receiver(post_save, sender=Organization, dispatch_uid="catalog.default_vat_rates")
def give_default_vat_rates(sender: type[Organization], instance: Organization, created: bool, **kwargs: Any) -> None:
    if created and not kwargs.get("raw", False):
        services.ensure_default_vat_rates(organization=instance)
