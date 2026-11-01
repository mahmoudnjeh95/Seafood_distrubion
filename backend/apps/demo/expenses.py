"""Demo expenses and day labour (P5-T01, P5-T03): fuel of Camion 2's day (split over the lots it loaded),
transport typed on a lot of shrimp, the month's rent waiting as a draft, the accountant sent for approval,
a refused ice bill; three day labourers and their days in the calendar, one on a lot.

Every expense and day has a fixed `client_uuid` and labourers are found by name, so running the seed again
creates nothing. Dates are taken from the day of the first seed.
"""

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.catalog import selectors as catalog
from apps.core.models import Organization, User
from apps.expenses import selectors, services
from apps.fleet import selectors as fleet
from apps.inventory import selectors as inventory

if TYPE_CHECKING:
    from apps.inventory.models import Batch

SEED_NAMESPACE = uuid.UUID("3e8b6f4a-1c2d-4f7e-9a0b-6c5d4e3f2a19")
# key, category code, amount, description, payee, method, target ("truck:<name>", "lot:<product reference>" or
# ""), days ago, what happens to it ("approve", "submit", "reject" or "" for a draft)
EXPENSES = [
    ("fuel-camion-2", "fuel", "85.000", "Gasoil", "Station Agil Sakiet Ezzit", "cash", "truck:Camion 2", 0, "approve"),
    (
        "transport-shrimp",
        "transport",
        "45.000",
        "Transport port → dépôt",
        "Transports Ben Ammar",
        "cash",
        "lot:CR-001",
        0,
        "approve",
    ),
    ("rent-month", "rent", "1200.000", "Loyer du dépôt", "Société Immobilière Sfax", "transfer", "", 1, ""),
    (
        "accountant-month",
        "accountant",
        "300.000",
        "Honoraires comptables",
        "Cabinet Trabelsi",
        "cheque",
        "",
        2,
        "submit",
    ),
    ("ice-refused", "handling", "18.500", "Glace paillette", "Glacière du port", "cash", "", 3, "reject"),
]
# name, phone, usual daily pay
LABOURERS = [
    ("Ali Ben Salah", "98 123 456", "40.000"),
    ("Moncef Trabelsi", "22 345 678", "35.000"),
    ("Hichem Gharbi", "", None),
]
# key, labourer, days ago, amount (None: usual pay), lot (product reference) or None, work type, approved
DAYS = [
    ("ali-unloading", "Ali Ben Salah", 0, None, "CR-001", "loading", True),
    ("moncef-cleaning", "Moncef Trabelsi", 1, None, None, "cleaning", True),
    ("hichem-stock", "Hichem Gharbi", 2, "45.000", None, "stock", False),
    ("ali-store", "Ali Ben Salah", 2, None, None, "store", False),
]


def _lot_of(organization: Organization, reference: str) -> "Batch | None":
    """The newest lot of a product."""
    product = catalog.products_of(organization, status="all").get(reference=reference)
    return inventory.batches_oldest_first(organization, product_id=product.pk).last()


def seed_expenses(*, organization: Organization, actor: User | None) -> int:
    """Create the demo expenses, day labourers and days that do not exist yet. Returns how many were made."""
    today = timezone.localdate()
    trucks = {truck.location.name: truck for truck in fleet.trucks_of(organization, status="all")}
    used = set(selectors.expenses_of(organization).exclude(client_uuid=None).values_list("client_uuid", flat=True))
    created = 0
    for key, code, amount, description, payee, method, target, days_ago, outcome in EXPENSES:
        client_uuid = uuid.uuid5(SEED_NAMESPACE, key)
        if client_uuid in used:
            continue
        kind, _, name = target.partition(":")
        expense = services.create_expense(
            organization=organization,
            actor=actor,
            # Never before the 1st: a waiting expense dated last month would block that month's review once the
            # month rolls over (the seed runs on the 1st of a month, when "one day ago" is last month).
            spent_on=max(today.replace(day=1), today - dt.timedelta(days=days_ago)),
            category=selectors.category_by_code(organization, code),
            amount=amount,
            payment_method=method,
            description=description,
            payee=payee,
            batch=_lot_of(organization, name) if kind == "lot" else None,
            truck=trucks[name] if kind == "truck" else None,
            client_uuid=client_uuid,
            submit=outcome == "submit",
            approve=outcome == "approve",
        )
        if outcome == "reject":
            services.reject_expense(expense=expense, actor=actor, reason="Déjà payée avec la facture du port")
        created += 1

    labourers = {labourer.name: labourer for labourer in selectors.labourers_of(organization, status="all")}
    for name, phone, pay in LABOURERS:
        if name not in labourers:
            labourers[name] = services.create_labourer(
                organization=organization, actor=actor, name=name, phone=phone, usual_daily_pay=pay
            )
            created += 1
    for key, name, days_ago, paid, lot, work_type, approved in DAYS:
        client_uuid = uuid.uuid5(SEED_NAMESPACE, key)
        if client_uuid in used:
            continue
        services.create_day_labour(
            organization=organization,
            actor=actor,
            labourer=labourers[name],
            # Never before the 1st either: a day left waiting in last month would block that month's review.
            worked_on=max(today.replace(day=1), today - dt.timedelta(days=days_ago)),
            amount=paid,
            batch=_lot_of(organization, lot) if lot else None,
            work_type=work_type,
            approve=approved,
            client_uuid=client_uuid,
        )
        created += 1
    return created
