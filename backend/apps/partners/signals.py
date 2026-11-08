"""A new organization starts with the default customer types (D-283)."""

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core.models import Organization

from . import services


@receiver(post_save, sender=Organization, dispatch_uid="partners.default_customer_types")
def give_default_customer_types(
    sender: type[Organization], instance: Organization, created: bool, **kwargs: Any
) -> None:
    if created and not kwargs.get("raw", False):
        services.ensure_default_customer_types(organization=instance)
