"""Reads of lot results: the snapshot a result is computed from, the live result and the closing checks
(P6-T02, D-061). Every number comes from another app's selectors; nothing here writes."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import Organization
from apps.expenses import selectors as expenses
from apps.hr import selectors as hr
from apps.inventory import selectors as inventory
from apps.partnerships import selectors as partnerships
from apps.purchasing import selectors as purchasing
from apps.sales import selectors as sales

from . import engine
from .models import LotResult, LotResultStatus, PartnershipResult

ZERO = Decimal("0.000")

# Movement kinds (inventory.MovementKind values) that write kg of a lot off or back on: the spoilage step.
WRITE_OFF_KINDS = frozenset({"loss", "count_correction", "adjustment"})
RECEIPT = "receipt"
# A correction of what a goods receipt received (D-270): kg received, never written off.
RECEIPT_CORRECTION = "receipt_correction"
SUPPLIER_RETURN = "supplier_return"
# Kilos turned into another lot (D-304): out of this lot's cost, into the new lot's.
TRANSFORMATION_OUT = "transformation_out"
TRANSFORMATION_IN = "transformation_in"

# Customer payments exist since P2-T06 (D-062): a lot with a sale still owed money cannot be closed (Q19).
CUSTOMER_PAYMENTS_BLOCK = True


def _sale_rows(organization: Organization, batch_id: int) -> tuple[engine.SaleRow, ...]:
    """The lot's confirmed sale rows, net of what customer returns took back (D-070)."""
    rows = []
    for row in sales.batch_sales(organization, batch_id=batch_id):
        net = sales.net_of(row)
        rows.append(
            engine.SaleRow(
                sale_id=row.line.sale_id,
                sale_number=row.line.sale.number,
                sold_on=timezone.localtime(row.line.sale.sold_at).date(),
                customer=row.line.sale.customer.name,
                quantity=net.quantity,
                unit_price=row.line.unit_price,
                revenue=net.revenue,
                cost=net.cost,
                amount_due=row.line.sale.amount_due,
            )
        )
    return tuple(rows)


@dataclass(frozen=True)
class _Stock:
    received: Decimal
    returned: Decimal
    rows: tuple[engine.StockRow, ...]


def _stock(organization: Organization, batch_id: int) -> _Stock:
    """Kg received, sent back to the supplier, and written off or found, from the lot's ledger movements.
    Sales and their cancellations are read from the sales themselves; transfers stay inside the company."""
    received = returned = ZERO
    rows = []
    for movement in inventory.movements_of(organization, batch_id=batch_id).order_by("occurred_at", "id"):
        leaves = movement.from_location_id is not None and movement.to_location_id is None
        enters = movement.to_location_id is not None and movement.from_location_id is None
        if movement.kind in (RECEIPT, TRANSFORMATION_IN) and enters:
            received += movement.quantity
        elif movement.kind == RECEIPT_CORRECTION and (leaves or enters):
            received += -movement.quantity if leaves else movement.quantity
        elif movement.kind in (SUPPLIER_RETURN, TRANSFORMATION_OUT) and leaves:
            # Sent back to the supplier, or turned into another lot (D-304): no longer this lot's cost.
            returned += movement.quantity
        elif movement.kind in WRITE_OFF_KINDS and (leaves or enters):
            rows.append(
                engine.StockRow(
                    movement_id=movement.pk,
                    kind=movement.kind,
                    occurred_on=timezone.localtime(movement.occurred_at).date(),
                    quantity=movement.quantity if leaves else -movement.quantity,
                    unit_cost=movement.unit_cost,
                    reason=movement.reason,
                )
            )
    return _Stock(received=received, returned=returned, rows=tuple(rows))


def _expense_cost_row(line: Any) -> engine.CostRow:
    """One line of `expenses.lot_cost_lines`, whatever its kind: the lot's own expenses, its truck-day
    shares, and the cold-room and general costs that P5-T02/T05 add, without a change here."""
    expense_id = getattr(line, "expense_id", None) or None
    quantity, day_quantity = getattr(line, "quantity", None), getattr(line, "day_quantity", None)
    place = getattr(line, "truck_name", "") or getattr(line, "location_name", "")
    month = getattr(line, "month", None)
    parts = [place] if place else []
    if quantity is not None and day_quantity is not None:
        parts.append(f"{quantity} / {day_quantity} kg")
    if month is not None:
        parts.append(month.strftime("%m/%Y"))
    if getattr(line, "estimated", False):
        parts.append(_("estimation"))
    detail = " · ".join(parts)
    return engine.CostRow(
        kind=str(line.kind),
        on=line.spent_on,
        title=getattr(line, "category_name", "") or str(line.kind),
        amount=line.amount,
        description=getattr(line, "description", ""),
        source_type="expense" if expense_id else "",
        source_id=expense_id,
        reference=getattr(line, "expense_number", ""),
        detail=detail,
        category_id=getattr(line, "category_id", None),
    )


def _cost_rows(organization: Organization, batch_id: int) -> tuple[engine.CostRow, ...]:
    """The lot's approved costs: `expenses.lot_cost_lines` (all its kinds) and its employees' days (hr)."""
    lines = [
        line
        for line in expenses.lot_cost_lines(organization, batch_id=batch_id)
        if line.status == "approved"  # lot_cost_lines gives approved lines only by default; kept explicit
    ]
    rows = [_expense_cost_row(line) for line in lines]
    rows += [
        engine.CostRow(
            kind="employee",
            on=day.work_date,
            title=day.employee.name,
            amount=day.cost,
            description=day.notes,
            source_type="employee",
            source_id=day.employee_id,
            detail=f"{day.days} × {day.monthly_salary} / 26",
        )
        for day in hr.lot_work_days_of(organization, batch_id=batch_id).order_by("work_date", "id")
    ]
    return tuple(rows)


def _write_off_rows(organization: Organization, batch_id: int) -> tuple[engine.CostRow, ...]:
    """The balance write-offs the owner charged to the lot (D-257): a customer's loss as a cost, a supplier's gain
    as a negative cost. Kept out of `cost_rows_for_batch`: they are not costs a partner shares by category."""
    rows = [
        engine.CostRow(
            kind="customer_write_off",
            on=share.write_off.written_on,
            title=share.write_off.customer.name,
            amount=share.amount,
            description=share.write_off.reason,
            source_type="customer",
            source_id=share.write_off.customer_id,
        )
        for share in sales.write_off_shares_of_batch(organization, batch_id=batch_id)
    ]
    rows += [
        engine.CostRow(
            kind="supplier_write_off",
            on=share.write_off.written_on,
            title=share.write_off.supplier.name,
            amount=-share.amount,
            description=share.write_off.reason,
            source_type="supplier",
            source_id=share.write_off.supplier_id,
        )
        for share in purchasing.write_off_shares_of_batch(organization, batch_id=batch_id)
    ]
    # A price cut the supplier gave on the lot's kilos (avoir fournisseur, D-300): the lot cost less. Returned kilos
    # are already out of its purchase cost (kg received − returned), and a weight gap was never in it.
    rows += [
        engine.CostRow(
            kind="supplier_credit",
            on=line.credit_note.credited_on,
            title=line.credit_note.supplier.name,
            amount=-line.amount,
            description=line.credit_note.reason,
            source_type="supplier_credit_note",
            source_id=line.credit_note_id,
            reference=line.credit_note.number,
        )
        for line in purchasing.price_credits_of_batch(organization, batch_id=batch_id)
    ]
    return tuple(rows)


def cost_rows_for_batch(
    organization: Organization, *, batch_id: int, date_from: dt.date, date_to: dt.date
) -> tuple[engine.CostRow, ...]:
    """A lot's approved cost lines dated within a period (the month-closing's partner participation,
    `partner_costs.month_partner_cost_shares`): the same rows `lot_snapshot` charges the lot with."""
    return tuple(row for row in _cost_rows(organization, batch_id) if date_from <= row.on <= date_to)


def terms_of(partnership: Any) -> engine.PartnershipTerms:
    """A partnership's terms as the engine uses them: its capital put in (contributions and corrections) and rates."""
    return engine.PartnershipTerms(
        partnership_id=partnership.pk,
        partner_id=partnership.partner_id,
        partner_name=partnership.partner.name,
        owner_capital=partnership.owner_capital,
        partner_capital=partnerships.capital_put_in(partnership),
        profit_rate=partnership.profit_rate,
        loss_rate=partnership.loss_rate,
    )


def _terms(organization: Organization, batch_id: int) -> engine.PartnershipTerms | None:
    """The terms a line's own result shows (D-324): those of its one partnership when that partnership shares this
    line alone, so the line's share is the partnership's to the millime. A line shared by several partnerships, or
    by one that shares other lines too, shows none: the share is the partnership's, on the sum of its lines."""
    live = partnerships.live_partnerships_of_line(organization, batch_id=batch_id)
    if len(live) != 1 or partnerships.line_ids_of(live[0]) != [batch_id]:
        return None
    return terms_of(live[0])


def lot_snapshot(organization: Organization, *, batch_id: int) -> engine.LotSnapshot:
    """Everything the result of one lot is computed from, read now. Raises Batch.DoesNotExist outside the
    organization."""
    batch = inventory.batch_of(organization, batch_id)
    stock = _stock(organization, batch_id)
    return engine.LotSnapshot(
        batch_id=batch.pk,
        batch_number=batch.number,
        product_name=batch.product.name,
        supplier_name=batch.supplier.name,
        received_on=batch.received_on,
        unit_cost=batch.unit_cost,
        received_quantity=stock.received,
        returned_quantity=stock.returned,
        on_hand_quantity=inventory.quantity_on_hand(organization, batch_id=batch_id),
        sales=_sale_rows(organization, batch_id),
        stock_rows=stock.rows,
        costs=_cost_rows(organization, batch_id) + _write_off_rows(organization, batch_id),
        partnership=_terms(organization, batch_id),
    )


def live_result(organization: Organization, *, batch_id: int) -> engine.ComputedResult:
    """The lot's result now: "so far" on an open lot, what a closing would freeze on a finished one."""
    return engine.lot_result(lot_snapshot(organization, batch_id=batch_id))


# ---- Closing checks ----


@dataclass(frozen=True)
class ClosingCheck:
    """One condition of closing a lot (Q19: sold out, costs in, customers paid)."""

    code: str
    ok: bool
    # A failed blocking check refuses the closing; a failed warning is kept with the result.
    blocking: bool
    quantity: Decimal | None = None
    count: int | None = None
    amount: Decimal | None = None


def customers_owing(organization: Organization, snapshot: engine.LotSnapshot) -> dict[int, Decimal]:
    """What customers still owe on the lot's sales, by sale id: the one place the "customers paid" check
    (Q19) reads receivables from.

    Since P2-T06 it is what each confirmed sale still owes after customer payments, credit notes and
    withholding (`sales.selectors.outstanding_by_sale`, D-062); a cancelled sale owes nothing.
    """
    return sales.outstanding_by_sale(organization, [sale.sale_id for sale in snapshot.sales])


def closing_checks(organization: Organization, result: engine.ComputedResult) -> list[ClosingCheck]:
    """What stands between the lot and its closing, with the figures the screen explains it with."""
    snapshot = result.snapshot
    waiting = [
        line
        for line in expenses.lot_cost_lines(organization, batch_id=snapshot.batch_id, approved_only=False)
        if line.status != "approved"
    ]
    owed = customers_owing(organization, snapshot)
    return [
        # Stock 0: everything sold, sent back or written off as a loss.
        ClosingCheck(
            code="stock_empty",
            ok=snapshot.on_hand_quantity == 0,
            blocking=True,
            quantity=snapshot.on_hand_quantity,
        ),
        # Costs typed on the lot but not approved yet would be left out of the frozen result.
        ClosingCheck(
            code="costs_approved",
            ok=not waiting,
            blocking=True,
            count=len(waiting),
            amount=sum((line.amount for line in waiting), ZERO),
        ),
        # Customers paid (Q19): every sale of the lot is paid, customer payments included (P2-T06).
        ClosingCheck(
            code="customers_paid",
            ok=not owed,
            blocking=CUSTOMER_PAYMENTS_BLOCK,
            count=len(owed),
            amount=sum(owed.values(), ZERO),
        ),
    ]


def checks_to_json(checks: list[ClosingCheck]) -> list[dict[str, Any]]:
    return [
        {
            "code": check.code,
            "ok": check.ok,
            "blocking": check.blocking,
            "quantity": None if check.quantity is None else str(check.quantity),
            "count": check.count,
            "amount": None if check.amount is None else str(check.amount),
        }
        for check in checks
    ]


# ---- Frozen results ----


def results_of(organization: Organization, *, batch_id: int | None = None) -> QuerySet[LotResult]:
    """Lot results, newest closing first, closed and reopened ones."""
    results = LotResult.objects.for_organization(organization).select_related(
        "batch__product", "partnership__partner", "closed_by", "reopened_by"
    )
    if batch_id is not None:
        results = results.filter(batch_id=batch_id)
    return results.order_by("-closed_at", "-id")


def closed_result_of(organization: Organization, *, batch_id: int) -> LotResult | None:
    """The frozen result of a closed lot; None while the lot is open (or was reopened)."""
    return results_of(organization, batch_id=batch_id).filter(status=LotResultStatus.CLOSED).first()


def closed_batch_ids(organization: Organization, *, batch_ids: list[int] | None = None) -> set[int]:
    """The lots that are closed now, among `batch_ids` (all when None)."""
    results = LotResult.objects.for_organization(organization).filter(status=LotResultStatus.CLOSED)
    if batch_ids is not None:
        results = results.filter(batch_id__in=batch_ids)
    return set(results.values_list("batch_id", flat=True))


# ---- Partnership results (D-320, D-324) ----


def partnership_results_of(
    organization: Organization, *, partnership_id: int | None = None
) -> QuerySet[PartnershipResult]:
    """Partnership results, newest closing first, closed and reopened ones."""
    results = PartnershipResult.objects.for_organization(organization).select_related(
        "partnership__partner", "closed_by", "reopened_by"
    )
    if partnership_id is not None:
        results = results.filter(partnership_id=partnership_id)
    return results.order_by("-closed_at", "-id")


def closed_partnership_result_of(organization: Organization, *, partnership_id: int) -> PartnershipResult | None:
    """The frozen result of a closed (or settled) partnership; None while one of its lines is open."""
    return (
        partnership_results_of(organization, partnership_id=partnership_id)
        .filter(status=LotResultStatus.CLOSED)
        .first()
    )


def closed_partnership_results_of_line(organization: Organization, *, batch_id: int) -> list[PartnershipResult]:
    """The frozen results of the partnerships that share this line, oldest partnership first."""
    ids = [partnership.pk for partnership in partnerships.live_partnerships_of_line(organization, batch_id=batch_id)]
    results = partnership_results_of(organization).filter(status=LotResultStatus.CLOSED, partnership_id__in=ids)
    return sorted(results, key=lambda result: result.partnership_id)


def shared_lines(organization: Organization, partnership: Any) -> tuple[engine.SharedLine, ...] | None:
    """The frozen lines of a partnership, in line order, once every line it shares is closed; None before."""
    lines = []
    for batch_id in partnerships.line_ids_of(partnership):
        result = closed_result_of(organization, batch_id=batch_id)
        if result is None:
            return None
        lines.append(
            engine.SharedLine(
                batch_id=batch_id,
                batch_number=result.batch.number,
                product_name=result.batch.product.name,
                net_result=result.net_result,
                lot_result_id=result.pk,
            )
        )
    return tuple(lines)


def live_partnership_result(organization: Organization, partnership: Any) -> engine.ComputedPartnershipResult:
    """A partnership's result now: the live nets of its lines (frozen or not), netted at its rates."""
    lines = []
    for batch_id in partnerships.line_ids_of(partnership):
        computed = live_result(organization, batch_id=batch_id)
        lines.append(
            engine.SharedLine(
                batch_id=batch_id,
                batch_number=computed.snapshot.batch_number,
                product_name=computed.snapshot.product_name,
                net_result=computed.net_result,
            )
        )
    return engine.partnership_result(terms_of(partnership), tuple(lines))


def partnership_result_for(
    organization: Organization, result: "LotResult | PartnershipResult"
) -> PartnershipResult | None:
    """The partnership result a screen asks about by its line's result: the closed result of the partnership that
    shares that line alone (`LotResult.partnership`), None for a line without one. A partnership result is itself."""
    if isinstance(result, PartnershipResult):
        return result
    if result.partnership_id is None:
        return None
    return closed_partnership_result_of(organization, partnership_id=result.partnership_id)


# ---- Late costs and settlement (P6-T03, D-066) ----


@dataclass(frozen=True)
class LateDrift:
    """How far a closed partnership's live net result (the sum of its lines) has moved from its frozen one, and
    what of it is already carried to the partner's settlements."""

    partnership_result_id: int
    frozen_net: Decimal
    live_net: Decimal
    # live − frozen: a cost recorded after the closing is negative.
    drift: Decimal
    # The part of the drift already booked on the partner's profit-share balance (sum of `basis`).
    booked: Decimal
    # The part still to book, and the partner's share of it (signed): the next settlement's adjustment.
    pending_basis: Decimal
    pending_share: Decimal


def late_drift(organization: Organization, result: "LotResult | PartnershipResult") -> LateDrift | None:
    """The late adjustment a closed partnership is waiting for, or None for a line without partner.

    Per partnership (D-324): drift = the sum of its lines' live nets − its frozen net. The share is computed on the
    whole drift and the booked part taken off, so what is booked adds up to `share(live net) − share(frozen net)`
    exactly, whatever the number of adjustments (no rounding drift). Given a line's result, it is the partnership's
    that shares this line alone."""
    frozen_result = partnership_result_for(organization, result)
    if frozen_result is None:
        return None
    partnership = partnerships.partnership_of(organization, frozen_result.partnership_id)
    terms = terms_of(partnership)
    live_net = _sum_nets(organization, frozen_result.batch_ids)
    frozen = frozen_result.net_result
    drift = live_net - frozen
    booked = partnerships.late_adjustments_booked(partnership, partnership_result_id=frozen_result.pk)
    share_now = engine.partner_share(terms, frozen + drift).share
    share_booked = engine.partner_share(terms, frozen + booked).share
    return LateDrift(
        partnership_result_id=frozen_result.pk,
        frozen_net=frozen,
        live_net=live_net,
        drift=drift,
        booked=booked,
        pending_basis=drift - booked,
        pending_share=share_now - share_booked,
    )


def _sum_nets(organization: Organization, batch_ids: list[int]) -> Decimal:
    return sum((live_result(organization, batch_id=batch_id).net_result for batch_id in batch_ids), ZERO)


@dataclass(frozen=True)
class SettlementPreview:
    """What settling a closed partnership would pay, step by step (mirrors `settle_partnership`)."""

    capital_to_return: Decimal
    lot_share: Decimal
    uncovered_loss: Decimal
    # Late adjustments still to book on this partner's partnerships (this one and the others) before settling.
    pending_adjustments: Decimal
    # The partner's profit-share balance after those adjustments, before this partnership's share.
    carried_in: Decimal
    share_paid: Decimal
    total: Decimal
    carried_out: Decimal


def partner_closed_results(organization: Organization, *, partner_id: int) -> list[PartnershipResult]:
    """The frozen results of every closed or settled partnership of one partner, oldest first."""
    results = []
    for partnership in partnerships.partnerships_of(organization, partner_id=partner_id):
        if partnership.status == "open":
            continue
        result = closed_partnership_result_of(organization, partnership_id=partnership.pk)
        if result is not None:
            results.append(result)
    return sorted(results, key=lambda result: (min(result.batch_ids, default=0), result.partnership_id))


def settlement_preview(organization: Organization, result: "LotResult | PartnershipResult") -> SettlementPreview:
    frozen = partnership_result_for(organization, result)
    if frozen is None:
        raise ValueError("No partnership result to settle")
    partnership = partnerships.partnership_of(organization, frozen.partnership_id)
    pending = ZERO
    for other in partner_closed_results(organization, partner_id=partnership.partner_id):
        drift = late_drift(organization, other)
        if drift is not None:
            pending += drift.pending_share
    carried_in = partnerships.profit_share_balance_of_partner(organization, partner_id=partnership.partner_id) + pending
    lot_entry = frozen.partner_share if frozen.partner_share > 0 else -frozen.uncovered_loss
    balance = carried_in + lot_entry
    share_paid = balance if balance > 0 else ZERO
    capital = partnerships.capital_balance(partnership)
    return SettlementPreview(
        capital_to_return=capital,
        lot_share=frozen.partner_share,
        uncovered_loss=frozen.uncovered_loss,
        pending_adjustments=pending,
        carried_in=carried_in,
        share_paid=share_paid,
        total=capital + share_paid,
        carried_out=balance - share_paid,
    )


def month_result(organization: Organization, *, month: "dt.date") -> Any:
    """The month's result as the monthly closing computes it (`closing.monthly.MonthReport`): sales, cost of goods,
    spoilage, expenses by category, personnel and net result. Reports read it here instead of recomputing."""
    from . import monthly

    return monthly.month_report(organization, month=month)
