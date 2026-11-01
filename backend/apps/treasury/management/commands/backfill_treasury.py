from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from apps.core.models import Organization
from apps.hr import services as hr
from apps.purchasing import services as purchasing
from apps.sales import services as sales
from apps.treasury import services
from apps.treasury.models import TreasuryMovement


class Command(BaseCommand):
    help = (
        "Write the treasury movements of what was recorded before the accounts existed (D-219): the cash, transfer "
        "and card lines of the customer and supplier règlements, the effets cashed, taken back or debited, the "
        "undoing of the voided règlements, and the salary payments (D-234). Safe to run again: a record's movement "
        "is never written twice."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--organization", type=int, help="Only this organization id.")

    def handle(self, *args: Any, **options: Any) -> None:
        organizations = Organization.objects.order_by("id")
        if options["organization"] is not None:
            organizations = organizations.filter(pk=options["organization"])
        for organization in organizations:
            before = TreasuryMovement.objects.filter(organization=organization).count()
            with transaction.atomic():
                services.ensure_default_accounts(organization=organization)
                sales.post_treasury_history(organization=organization)
                purchasing.post_treasury_history(organization=organization)
                services.post_effet_history(organization=organization)
                hr.post_treasury_history(organization=organization)
            written = TreasuryMovement.objects.filter(organization=organization).count() - before
            self.stdout.write(f"{organization}: {written} movement(s) written.")
