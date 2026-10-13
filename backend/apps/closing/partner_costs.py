"""Each partner's participation in the month's shared costs (owner request, 2026-10-13).

Rent, electricity, fuel and the other costs the lot result engine splits over the lots in stock (D-041)
land on partnership lots too: a partner's lot carries its share of them exactly like an own-stock lot.
This groups what landed on each partner's lots this month by cost category, so the month-closing screen
can show, next to "Dépenses approuvées", how much of each charge a partner's lots actually carried. The
amount is the raw cost line (not weighted by the partner's profit or loss %): it answers "where did this
charge go", the same per-lot breakdown already on the lot page, totalled by partner.
"""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from apps.core.models import Organization
from apps.partnerships import selectors as partnerships

from . import engine, selectors

ZERO = Decimal("0.000")

# A cost row of this kind has no single category (its title is an employee's name): grouped together.
EMPLOYEE_KEY = "employee"


@dataclass(frozen=True)
class PartnerCostCategory:
    # Stable within the month: the expense category name, or `EMPLOYEE_KEY` for day and monthly salaries.
    key: str
    name: str
    is_employee: bool
    # None for a cost not tied to one category id (an employee's day): the screen cannot link it.
    category_id: int | None
    amount: Decimal
    count: int


@dataclass(frozen=True)
class PartnerCostShare:
    partner_id: int
    partner_name: str
    total: Decimal
    categories: tuple[PartnerCostCategory, ...]


def month_partner_cost_shares(
    organization: Organization, *, date_from: dt.date, date_to: dt.date
) -> tuple[PartnerCostShare, ...]:
    """Every partner who had a lot in stock this month, with the month's cost lines their lots carried, by
    category. A partner with no cost line this month (a lot received but not yet charged) is left out."""
    names: dict[int, str] = {}
    totals: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for partnership in partnerships.partnerships_of(organization):
        rows = selectors.cost_rows_for_batch(
            organization, batch_id=partnership.batch_id, date_from=date_from, date_to=date_to
        )
        if not rows:
            continue
        names[partnership.partner_id] = partnership.partner.name
        bucket = totals[partnership.partner_id]
        for row in rows:
            is_employee = row.kind == EMPLOYEE_KEY
            name = "" if is_employee else (row.title or row.kind)
            key = EMPLOYEE_KEY if is_employee else name
            entry = bucket.setdefault(
                key,
                {"name": name, "is_employee": is_employee, "category_id": row.category_id, "amount": ZERO, "count": 0},
            )
            entry["amount"] += row.amount
            entry["count"] += 1
    shares = []
    for partner_id, categories in totals.items():
        cats = tuple(
            PartnerCostCategory(
                key=key,
                name=data["name"],
                is_employee=data["is_employee"],
                category_id=data["category_id"],
                amount=data["amount"],
                count=data["count"],
            )
            for key, data in sorted(categories.items(), key=lambda item: (item[1]["is_employee"], item[1]["name"]))
        )
        shares.append(
            PartnerCostShare(
                partner_id=partner_id,
                partner_name=names[partner_id],
                total=sum((category.amount for category in cats), ZERO),
                categories=cats,
            )
        )
    return tuple(sorted(shares, key=lambda share: share.partner_name))


def to_json(shares: tuple[PartnerCostShare, ...]) -> list[dict[str, Any]]:
    plain = engine.plain
    return [
        {
            "partner_id": share.partner_id,
            "partner_name": share.partner_name,
            "total": plain(share.total),
            "categories": [
                {
                    "key": category.key,
                    "name": category.name,
                    "is_employee": category.is_employee,
                    "category_id": category.category_id,
                    "amount": plain(category.amount),
                    "count": category.count,
                }
                for category in share.categories
            ],
        }
        for share in shares
    ]
