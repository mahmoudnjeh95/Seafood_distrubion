"""The month's figures for the accountant (P6-T05, D-073): sales, cost of goods sold, spoilage, expenses,
payroll, net result, the stock valuation at month-end and the checks before closing.

Everything is read through other apps' selectors; nothing is written here. Profit is never "purchases −
sales": unsold stock stays an asset, valued at what it cost, and only the cost of the goods *sold* is a
charge. Amounts come back as Decimal; `to_json` makes the plain form that is frozen and sent by the API.
"""

import calendar
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from apps.core.models import Organization
from apps.expenses import selectors as expenses
from apps.hr import selectors as hr
from apps.inventory import selectors as inventory
from apps.sales import selectors as sales

from . import engine, partner_costs
from .selectors import ClosingCheck, checks_to_json

ZERO = Decimal("0.000")

# The ledger kinds the roll-forward shows, in the order of a stock account.
LEDGER_ORDER = (
    "receipt",
    "customer_return",
    "supplier_return",
    "sale",
    "loss",
    "count_correction",
    "adjustment",
)
# Write-offs: what the month's spoilage is made of (a surplus found counts against it).
SPOILAGE_KINDS = ("loss", "count_correction", "adjustment")


def month_start(month: dt.date) -> dt.date:
    return month.replace(day=1)


def month_end(month: dt.date) -> dt.date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


@dataclass(frozen=True)
class MonthReport:
    month: dt.date
    # Sales and goods
    sales_count: int
    quantity_sold: Decimal
    revenue: Decimal
    cogs: Decimal
    gross_margin: Decimal
    spoilage_quantity: Decimal
    spoilage: Decimal
    # Costs
    expense_categories: tuple[expenses.CategoryTotal, ...]
    expenses_total: Decimal
    personnel: Decimal
    operating_costs: Decimal
    net_result: Decimal
    # What of the month's costs landed on a partnership lot, by partner and category (owner request,
    # 2026-10-13): the raw cost, not weighted by the partner's profit or loss %.
    partner_cost_shares: tuple[partner_costs.PartnerCostShare, ...]
    # Stock
    opening_value: Decimal
    closing_value: Decimal
    ledger: tuple[inventory.LedgerKind, ...]
    stock_rows: tuple[inventory.BatchValue, ...]
    purchases: Decimal
    # What the ledger's roll-forward and the lot-by-lot valuation differ by (rounding only: millimes).
    rounding_difference: Decimal
    checks: tuple[ClosingCheck, ...]


def net_result_of(*, revenue: Decimal, cogs: Decimal, spoilage: Decimal, operating_costs: Decimal) -> Decimal:
    """sales − cost of goods sold − spoilage − expenses and payroll."""
    return revenue - cogs - spoilage - operating_costs


def month_report(organization: Organization, *, month: dt.date) -> MonthReport:
    first, last = month_start(month), month_end(month)
    sold = sales.month_sales(organization, date_from=first, date_to=last)
    spent = expenses.month_expenses(organization, date_from=first, date_to=last)
    payroll = hr.payroll_summary(organization, month=first)
    personnel = hr.monthly_personnel_expense(organization, month=first)
    ledger = tuple(
        sorted(
            inventory.ledger_by_kind(organization, date_from=first, date_to=last),
            key=lambda row: LEDGER_ORDER.index(row.kind) if row.kind in LEDGER_ORDER else len(LEDGER_ORDER),
        )
    )
    spoiled = [row for row in ledger if row.kind in SPOILAGE_KINDS]
    # A write-off leaves the stock (negative); the charge is positive.
    spoilage = -sum((row.value for row in spoiled), ZERO)
    spoilage_quantity = -sum((row.quantity for row in spoiled), ZERO)
    opening_rows = inventory.stock_valuation(organization, day=first - dt.timedelta(days=1))
    closing_rows = tuple(inventory.stock_valuation(organization, day=last))
    opening_value = sum((row.value for row in opening_rows), ZERO)
    closing_value = sum((row.value for row in closing_rows), ZERO)
    purchases = sum((row.value for row in ledger if row.kind == "receipt"), ZERO)
    rounding = closing_value - (opening_value + sum((row.value for row in ledger), ZERO))
    operating = spent.total + personnel
    shares = partner_costs.month_partner_cost_shares(organization, date_from=first, date_to=last)
    return MonthReport(
        month=first,
        sales_count=sold.sales,
        quantity_sold=sold.quantity,
        revenue=sold.revenue,
        cogs=sold.cogs,
        gross_margin=sold.revenue - sold.cogs,
        spoilage_quantity=spoilage_quantity,
        spoilage=spoilage,
        expense_categories=spent.categories,
        expenses_total=spent.total,
        personnel=personnel,
        operating_costs=operating,
        net_result=net_result_of(revenue=sold.revenue, cogs=sold.cogs, spoilage=spoilage, operating_costs=operating),
        partner_cost_shares=shares,
        opening_value=opening_value,
        closing_value=closing_value,
        ledger=ledger,
        stock_rows=closing_rows,
        purchases=purchases,
        rounding_difference=rounding,
        checks=tuple(_checks(organization, first, last, sold, ledger, spent, payroll)),
    )


def _checks(
    organization: Organization,
    first: dt.date,
    last: dt.date,
    sold: sales.MonthSales,
    ledger: tuple[inventory.LedgerKind, ...],
    spent: expenses.MonthExpenses,
    payroll: hr.PayrollSummary,
) -> list[ClosingCheck]:
    pending = inventory.pending_losses(organization, date_from=first, date_to=last)
    drafts = sales.draft_sales_count(organization, date_from=first, date_to=last)
    # The cost the ledger gave out for sales, less what customers brought back, against the sale snapshots.
    ledger_cogs = -sum((row.value for row in ledger if row.kind in {"sale", "customer_return"}), ZERO)
    return [
        # Expenses typed but not approved would be left out of the result.
        ClosingCheck(
            code="expenses_approved",
            ok=spent.waiting_count == 0,
            blocking=True,
            count=spent.waiting_count,
            amount=spent.waiting_amount,
        ),
        # Salaries still drafts are not an expense yet.
        ClosingCheck(code="payroll_approved", ok=payroll.drafts == 0, blocking=True, count=payroll.drafts),
        # A loss waiting for the owner has not left the stock: the month would carry it later.
        ClosingCheck(code="losses_decided", ok=not pending.exists(), blocking=True, count=pending.count()),
        # A draft sale has not left the stock nor counted anywhere.
        ClosingCheck(code="sales_confirmed", ok=drafts == 0, blocking=False, count=drafts),
        # The sale snapshots and the stock ledger should agree on the cost of the goods sold.
        ClosingCheck(
            code="cogs_matches_ledger", ok=ledger_cogs == sold.cogs, blocking=False, amount=ledger_cogs - sold.cogs
        ),
        # Not tracked yet (driver app, Phase 3): listed so the accountant knows they are not covered.
        ClosingCheck(code="cash_differences", ok=True, blocking=False),
        ClosingCheck(code="driver_days_closed", ok=True, blocking=False),
    ]


def to_json(report: MonthReport) -> dict[str, Any]:
    """The report as plain JSON (amounts as strings, dates ISO): frozen at approval and sent by the API."""
    plain = engine.plain
    return {
        "month": plain(report.month),
        "sales": {
            "count": report.sales_count,
            "quantity": plain(report.quantity_sold),
            "revenue": plain(report.revenue),
        },
        "cogs": plain(report.cogs),
        "gross_margin": plain(report.gross_margin),
        "spoilage": {"quantity": plain(report.spoilage_quantity), "value": plain(report.spoilage)},
        "expenses": {
            "categories": [
                {
                    "category_id": row.category_id,
                    "code": row.code,
                    "name": row.name,
                    "count": row.count,
                    "total": plain(row.total),
                }
                for row in report.expense_categories
            ],
            "total": plain(report.expenses_total),
        },
        "personnel": plain(report.personnel),
        "operating_costs": plain(report.operating_costs),
        "net_result": plain(report.net_result),
        "partner_costs": partner_costs.to_json(report.partner_cost_shares),
        "stock": {
            "opening_value": plain(report.opening_value),
            "purchases": plain(report.purchases),
            "closing_value": plain(report.closing_value),
            "rounding_difference": plain(report.rounding_difference),
            "ledger": [
                {"kind": row.kind, "quantity": plain(row.quantity), "value": plain(row.value)} for row in report.ledger
            ],
            "rows": [
                {
                    "batch_id": row.batch_id,
                    "batch_number": row.batch_number,
                    "product_name": row.product_name,
                    "supplier_name": row.supplier_name,
                    "received_on": plain(row.received_on),
                    "quantity": plain(row.quantity),
                    "unit_cost": plain(row.unit_cost),
                    "value": plain(row.value),
                }
                for row in report.stock_rows
            ],
        },
        "checks": checks_to_json(list(report.checks)),
    }
