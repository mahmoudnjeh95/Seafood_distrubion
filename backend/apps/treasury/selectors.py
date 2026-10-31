"""Read queries of the treasury: banks and effets (D-196)."""

import datetime as dt

from django.db.models import Q, QuerySet

from apps.core.models import Organization

from .models import Bank, Instrument, InstrumentDirection, InstrumentKind, InstrumentStatus


def banks_of(organization: Organization, *, active_only: bool = False) -> QuerySet[Bank]:
    banks = Bank.objects.for_organization(organization)
    return banks.filter(is_active=True) if active_only else banks


def bank_of(organization: Organization, bank_id: int) -> Bank:
    """One bank of the organization. Raises Bank.DoesNotExist outside it."""
    return Bank.objects.for_organization(organization).get(pk=bank_id)


def instruments_of(
    organization: Organization,
    *,
    direction: str | None = None,
    kind: str | None = None,
    statuses: list[str] | None = None,
    customer_id: int | None = None,
    supplier_id: int | None = None,
    due_from: dt.date | None = None,
    due_to: dt.date | None = None,
    search: str = "",
) -> QuerySet[Instrument]:
    """Effets, soonest due first, with their bank and party. `search` looks in the number, the drawer, the
    règlement number and the party's name."""
    rows = Instrument.objects.for_organization(organization).select_related("bank", "customer", "supplier")
    if direction:
        rows = rows.filter(direction=direction)
    if kind:
        rows = rows.filter(kind=kind)
    if statuses:
        rows = rows.filter(status__in=statuses)
    if customer_id is not None:
        rows = rows.filter(customer_id=customer_id)
    if supplier_id is not None:
        rows = rows.filter(supplier_id=supplier_id)
    if due_from is not None:
        rows = rows.filter(due_on__gte=due_from)
    if due_to is not None:
        rows = rows.filter(due_on__lte=due_to)
    search = search.strip()
    if search:
        rows = rows.filter(
            Q(number__icontains=search)
            | Q(drawer__icontains=search)
            | Q(source_number__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(supplier__name__icontains=search)
        )
    return rows.order_by("due_on", "id")


# The choices of an effet, for other apps' serializers (they may not import this app's models).
INSTRUMENT_KIND_CHOICES = InstrumentKind.choices
INSTRUMENT_STATUS_CHOICES = InstrumentStatus.choices
INSTRUMENT_DIRECTION_CHOICES = InstrumentDirection.choices
