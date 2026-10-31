"""A new organization starts with the list of Tunisian banks (D-197)."""

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core.models import Organization

from . import services


@receiver(post_save, sender=Organization, dispatch_uid="treasury.default_banks")
def give_default_banks(sender: type[Organization], instance: Organization, created: bool, **kwargs: Any) -> None:
    if created and not kwargs.get("raw", False):
        services.ensure_default_banks(organization=instance)
