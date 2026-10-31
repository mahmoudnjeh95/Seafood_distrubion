"""Read queries of the treasury: banks and effets (D-197)."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db.models import Count, Prefetch, Q, QuerySet, Sum

from apps.core.models import Organization

from .models import Bank, Deposit, Instrument, InstrumentDirection, InstrumentKind, InstrumentStatus


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
    bank_id: int | None = None,
    deposit_id: int | None = None,
) -> QuerySet[Instrument]:
    """Effets, soonest due first, with their bank and party. `search` looks in the number, the drawer, the
    règlement number and the party's name."""
    rows = Instrument.objects.for_organization(organization).select_related("bank", "customer", "supplier", "deposit")
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
    if bank_id is not None:
        rows = rows.filter(bank_id=bank_id)
    if deposit_id is not None:
        rows = rows.filter(deposit_id=deposit_id)
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


@dataclass(frozen=True)
class InstrumentTotals:
    """The count and amount of filtered effets, by status, and those whose échéance has passed while not done."""

    count: int
    total: Decimal
    by_status: dict[str, dict[str, Any]]
    overdue_count: int
    overdue_total: Decimal


# Waiting for the bank: an échéance past while in one of these is late.
WAITING_STATUSES = (InstrumentStatus.PORTFOLIO, InstrumentStatus.DEPOSITED, InstrumentStatus.ISSUED)


def instrument_totals(rows: QuerySet[Instrument], *, today: dt.date) -> InstrumentTotals:
    """The totals of an `instruments_of` queryset (its filters applied)."""
    by_status = {
        row["status"]: {"count": row["count"], "total": row["total"]}
        for row in rows.order_by().values("status").annotate(count=Count("id"), total=Sum("amount"))
    }
    late = rows.filter(status__in=WAITING_STATUSES, due_on__lt=today).aggregate(count=Count("id"), total=Sum("amount"))
    return InstrumentTotals(
        count=sum(row["count"] for row in by_status.values()),
        total=sum((row["total"] for row in by_status.values()), Decimal("0.000")),
        by_status=by_status,
        overdue_count=late["count"] or 0,
        overdue_total=late["total"] or Decimal("0.000"),
    )


def deposits_of(organization: Organization) -> QuerySet[Deposit]:
    """Bordereaux, newest first, with their bank, effets, `effets_count` and `effets_total`."""
    effets = Instrument.objects.select_related("bank", "customer").order_by("due_on", "id")
    return (
        Deposit.objects.for_organization(organization)
        .select_related("bank", "created_by")
        .prefetch_related(Prefetch("instruments", queryset=effets))
        .annotate(effets_count=Count("instruments"), effets_total=Sum("instruments__amount"))
        .order_by("-deposited_on", "-id")
    )


def deposit_of(organization: Organization, deposit_id: int) -> Deposit:
    """One bordereau. Raises Deposit.DoesNotExist outside the organization."""
    return deposits_of(organization).get(pk=deposit_id)


# The choices of an effet, for other apps' serializers (they may not import this app's models).
INSTRUMENT_KIND_CHOICES = InstrumentKind.choices
INSTRUMENT_STATUS_CHOICES = InstrumentStatus.choices
INSTRUMENT_DIRECTION_CHOICES = InstrumentDirection.choices
