"""The owner's dashboard (P7-T01, D-104): the month so far, profit and cash kept apart, and what needs a look.

Nothing is computed here that another app already knows: the month's sales, margin and net result come
from `monthly.month_report` (the figures the accountant closes with), receivables and cash from the sales
selectors, the waiting items from the apps that own them. The month is the current one, up to today.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from apps.core.models import Organization
from apps.dayclose import selectors as dayclose
from apps.expenses import selectors as expenses
from apps.inventory import selectors as inventory
from apps.partners import selectors as partners
from apps.partnerships import selectors as partnerships
from apps.purchasing import selectors as purchasing
from apps.sales import selectors as sales

from . import monthly

ZERO = Decimal("0.000")
# Customers named in the alert; the rest are counted.
OVERDUE_SHOWN = 5
# Items named in the other alerts; the rest are counted.
ALERT_ITEMS_SHOWN = 5
# A lot is "expiring" this many days before its use-by date (provisional, to confirm with the client).
EXPIRY_ALERT_DAYS = 3


@dataclass(frozen=True)
class OverdueRow:
    customer_id: int
    name: str
    overdue: Decimal


@dataclass(frozen=True)
class LowStockRow:
    product_id: int
    name: str
    quantity: Decimal
    min_stock: Decimal


@dataclass(frozen=True)
class ExpiringRow:
    batch_id: int
    batch_number: str
    product_name: str
    use_by: dt.date
    quantity: Decimal


@dataclass(frozen=True)
class CashDifferenceRow:
    closing_id: int
    day: dt.date
    driver_name: str
    difference: Decimal


@dataclass(frozen=True)
class PendingTermsRow:
    partnership_id: int
    batch_id: int
    batch_number: str
    partner_name: str


@dataclass(frozen=True)
class Dashboard:
    month: dt.date
    # Profit (what the business earned): sales less the cost of what was sold, spoilage, expenses and payroll.
    sales: Decimal
    previous_sales: Decimal
    gross_margin: Decimal
    net_result: Decimal
    # Cash (what came in): never mixed with profit. Receivables are sales not yet paid.
    cash_collected: Decimal
    receivables: Decimal
    receivables_overdue: Decimal
    # What the company holds in stock, at cost.
    stock_value: Decimal
    # Alerts
    overdue_customers: tuple[OverdueRow, ...]
    overdue_customer_count: int
    days_waiting: int
    expenses_waiting: int
    # Each list shows at most ALERT_ITEMS_SHOWN items; the count is of all of them.
    low_stock: tuple[LowStockRow, ...]
    low_stock_count: int
    expiring: tuple[ExpiringRow, ...]
    expiring_count: int
    cash_differences: tuple[CashDifferenceRow, ...]
    cash_difference_count: int
    # Lots whose partner was named at the receipt and whose capital and rates are not filled in (D-100).
    pending_terms: tuple[PendingTermsRow, ...]
    pending_terms_count: int
    # Purchases at the port waiting for the office, and those of them sent more than 24 hours ago (D-176).
    field_purchases_waiting: int
    field_purchases_late: int
    # Supplier invoices with part of what is owed still without a settlement plan, posted over 24 h ago (D-192).
    settlements_undefined_late: int


def dashboard_of(organization: Organization, *, today: dt.date) -> Dashboard:
    month = monthly.month_start(today)
    report = monthly.month_report(organization, month=month)
    previous = monthly.month_start(month - dt.timedelta(days=1))
    previous_sales = sales.month_sales(organization, date_from=previous, date_to=monthly.month_end(previous)).revenue
    receivables = sales.receivables_overview(organization, today=today)
    names = {c.pk: c.name for c in partners.customers_of(organization, status="all")}
    late = tuple(
        OverdueRow(customer_id=row.customer_id, name=names.get(row.customer_id, ""), overdue=row.overdue)
        for row in receivables.overdue_customers[:OVERDUE_SHOWN]
    )
    low = inventory.low_stock_products(organization)
    expiring = inventory.expiring_batches(organization, today=today, within_days=EXPIRY_ALERT_DAYS)
    differences = dayclose.unexplained_cash_differences(organization)
    pending = list(partnerships.pending_terms(organization))
    field_purchases = purchasing.field_purchases_waiting(organization)
    return Dashboard(
        month=month,
        sales=report.revenue,
        previous_sales=previous_sales,
        gross_margin=report.gross_margin,
        net_result=report.net_result,
        cash_collected=sales.cash_collected(organization, date_from=month, date_to=today),
        receivables=receivables.total,
        receivables_overdue=receivables.overdue,
        # The month-end valuation replays the ledger by date, so for this month it is the stock as of today.
        stock_value=report.closing_value,
        overdue_customers=late,
        overdue_customer_count=len(receivables.overdue_customers),
        days_waiting=dayclose.waiting_for_office(organization),
        expenses_waiting=expenses.waiting_for_approval(organization),
        low_stock=tuple(
            LowStockRow(
                product_id=stock.product.pk,
                name=stock.product.name,
                quantity=stock.quantity,
                min_stock=stock.product.min_stock,
            )
            for stock in low[:ALERT_ITEMS_SHOWN]
        ),
        low_stock_count=len(low),
        expiring=tuple(
            ExpiringRow(
                batch_id=row.batch_id,
                batch_number=row.batch_number,
                product_name=row.product_name,
                use_by=row.use_by,
                quantity=row.quantity,
            )
            for row in expiring[:ALERT_ITEMS_SHOWN]
        ),
        expiring_count=len(expiring),
        cash_differences=tuple(
            CashDifferenceRow(
                closing_id=row.closing_id, day=row.day, driver_name=row.driver_name, difference=row.difference
            )
            for row in differences[:ALERT_ITEMS_SHOWN]
        ),
        cash_difference_count=len(differences),
        pending_terms=tuple(
            PendingTermsRow(
                partnership_id=row.pk,
                batch_id=row.batch_id,
                batch_number=row.batch.number,
                partner_name=row.partner.name,
            )
            for row in pending[:ALERT_ITEMS_SHOWN]
        ),
        pending_terms_count=len(pending),
        field_purchases_waiting=field_purchases.waiting,
        field_purchases_late=field_purchases.late,
        settlements_undefined_late=purchasing.undefined_settlements_late(organization),
    )
