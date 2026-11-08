from typing import Any

from django.core.management.base import BaseCommand

from apps.core.models import Organization
from apps.maintenance import services


class Command(BaseCommand):
    help = (
        "Tell the office once about each maintenance that turns orange or red and each paper that reaches a warning "
        "day or expires (P10-T05, D-295). Run every night; the screens already show the states before it runs."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        total = 0
        for organization in Organization.objects.order_by("id"):
            total += services.send_warnings(organization=organization)
        self.stdout.write(self.style.SUCCESS(f"{total} maintenance warning(s) sent."))
