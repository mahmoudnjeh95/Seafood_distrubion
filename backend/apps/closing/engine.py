"""The lot result engine (P6-T02, D-061): pure functions, no database.

A `LotSnapshot` holds everything the result needs (the lot's sales, its stock written off, its costs and
the partnership terms); `lot_result` turns it into a `ComputedResult` with every step shown:

    revenue − purchase cost of the kg sold − kg written off − each kind of cost = net result
    net result > 0: the partner gets profit % of it; the owner keeps the rest
    net result < 0: the partner carries loss % of it, taken from their capital; what the capital cannot
                    cover is carried as an amount the partner owes (D-031, provisional)
    capital to return = capital − loss share taken from it

Amounts are Decimal in DT, rounded half up to the millime once per share (ARCHITECTURE §4.1). The
partner's share and the owner's share always add up to the net result exactly.
"""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from apps.core.money import money

ZERO = Decimal("0.000")
HUNDRED = Decimal("100")

type Outcome = Literal["profit", "zero", "loss"]

# The cost kinds in the order the result lists them. Kinds not listed (new ones, P5-T02/T05) come after,
# by name: the engine takes any kind `expenses.lot_cost_lines` gives without being changed.
COST_KIND_ORDER: tuple[str, ...] = ("lot", "truck_day", "employee", "cold_room", "cold_room_adjustment", "general")


# ---- What goes in ----


@dataclass(frozen=True)
class SaleRow:
    """The part of one sale line taken from this lot (one `SaleLineBatch`)."""

    sale_id: int
    sale_number: str
    sold_on: dt.date
    customer: str
    quantity: Decimal
    # The line's price per kg (after its discount, the revenue of these kg / kg).
    unit_price: Decimal
    revenue: Decimal
    # Purchase cost of these kg: kg × the lot's cost per kg, as kept on the sale (D-051).
    cost: Decimal
    # What the customer still owes on the whole sale (closing checks, P2-T06 hook).
    amount_due: Decimal = ZERO


@dataclass(frozen=True)
class StockRow:
    """Kilos of this lot written off (a loss, a count shortage) or found again (a count surplus)."""

    movement_id: int
    kind: str
    occurred_on: dt.date
    # Signed: + kg gone, − kg found.
    quantity: Decimal
    unit_cost: Decimal
    reason: str = ""

    @property
    def value(self) -> Decimal:
        """The purchase cost of these kg, rounded once (signed like the kg)."""
        return money(self.quantity * self.unit_cost)


@dataclass(frozen=True)
class CostRow:
    """One cost charged to the lot (an expense, a truck-day share, employee days, cold room...)."""

    kind: str
    on: dt.date
    title: str
    amount: Decimal
    description: str = ""
    # What the screens link to: ("expense", 12), ("employee", 3)...
    source_type: str = ""
    source_id: int | None = None
    reference: str = ""
    # How the amount was found: "30 kg sur 120 kg", "0.5 j × 1 300 / 26"...
    detail: str = ""
    # The expense category this line belongs to (None for an employee's day): what the month closing's
    # partner cost participation links to in the expenses list.
    category_id: int | None = None


@dataclass(frozen=True)
class PartnershipTerms:
    """The partnership of the lot as the result uses it (D-031, D-060)."""

    partnership_id: int
    partner_id: int
    partner_name: str
    owner_capital: Decimal
    # The partner's capital in this lot before the result (the ledger's balance).
    partner_capital: Decimal
    profit_rate: Decimal
    loss_rate: Decimal


@dataclass(frozen=True)
class LotSnapshot:
    batch_id: int
    batch_number: str
    product_name: str
    supplier_name: str
    received_on: dt.date
    unit_cost: Decimal
    received_quantity: Decimal
    # Sent back to the supplier: not the lot's cost (the supplier takes it back).
    returned_quantity: Decimal
    on_hand_quantity: Decimal
    sales: tuple[SaleRow, ...] = ()
    stock_rows: tuple[StockRow, ...] = ()
    costs: tuple[CostRow, ...] = ()
    partnership: PartnershipTerms | None = None


# ---- What comes out ----


@dataclass(frozen=True)
class CostGroup:
    kind: str
    total: Decimal
    lines: tuple[CostRow, ...]


@dataclass(frozen=True)
class PartnerShare:
    partnership_id: int
    partner_id: int
    partner_name: str
    owner_capital: Decimal
    partner_capital: Decimal
    profit_rate: Decimal
    loss_rate: Decimal
    # The rate applied: profit % on a profit, loss % on a loss, none on zero.
    rate: Decimal | None
    # Signed: + the partner's part of a profit, − their part of a loss.
    share: Decimal
    # Their loss share taken from their capital, and what the capital could not cover (D-031).
    capital_deducted: Decimal
    uncovered_loss: Decimal
    capital_to_return: Decimal
    # What the partner gets when the lot is settled: capital back + a profit share (P6-T03 pays it).
    payable_to_partner: Decimal


@dataclass(frozen=True)
class Step:
    """One line of the explanation: `sign` is "+", "-" or "=" (a total)."""

    code: str
    sign: str
    amount: Decimal
    kind: str = ""
    rate: Decimal | None = None


@dataclass(frozen=True)
class ComputedResult:
    snapshot: LotSnapshot
    quantity_sold: Decimal
    # Net kg written off (losses and count shortages less surpluses).
    quantity_written_off: Decimal
    revenue: Decimal
    cogs: Decimal
    spoilage: Decimal
    cost_groups: tuple[CostGroup, ...]
    costs_total: Decimal
    net_result: Decimal
    outcome: Outcome
    owner_share: Decimal
    partner: PartnerShare | None
    # For reading only: the lot's whole purchase cost and the part still in stock (not a cost yet).
    purchase_cost: Decimal
    stock_value: Decimal
    steps: tuple[Step, ...] = field(default=())


# ---- The computation ----


def _sum(values: Any) -> Decimal:
    return sum(values, ZERO)


def outcome_of(net_result: Decimal) -> Outcome:
    if net_result > 0:
        return "profit"
    if net_result < 0:
        return "loss"
    return "zero"


def _kind_key(kind: str) -> tuple[int, str]:
    return (COST_KIND_ORDER.index(kind), "") if kind in COST_KIND_ORDER else (len(COST_KIND_ORDER), kind)


def cost_groups(costs: tuple[CostRow, ...]) -> tuple[CostGroup, ...]:
    """The lot's costs by kind, known kinds first, each with its lines by day."""
    kinds = sorted({cost.kind for cost in costs}, key=_kind_key)
    groups = []
    for kind in kinds:
        lines = tuple(sorted((cost for cost in costs if cost.kind == kind), key=lambda cost: cost.on))
        groups.append(CostGroup(kind=kind, total=_sum(line.amount for line in lines), lines=lines))
    return tuple(groups)


def partner_share(terms: PartnershipTerms, net_result: Decimal) -> PartnerShare:
    """The partner's part of a net result (Q3, D-031, client meeting §5).

    Profit: profit % of it, rounded once; the capital comes back whole. Loss: loss % of the loss, rounded
    once, taken from the capital; the part the capital cannot cover is carried as an amount the partner
    owes (provisional, D-031), so the capital never goes below zero. Zero: nothing to share.
    """
    capital = terms.partner_capital
    if net_result > 0:
        share = money(net_result * terms.profit_rate / HUNDRED)
        return PartnerShare(
            partnership_id=terms.partnership_id,
            partner_id=terms.partner_id,
            partner_name=terms.partner_name,
            owner_capital=terms.owner_capital,
            partner_capital=capital,
            profit_rate=terms.profit_rate,
            loss_rate=terms.loss_rate,
            rate=terms.profit_rate,
            share=share,
            capital_deducted=ZERO,
            uncovered_loss=ZERO,
            capital_to_return=capital,
            payable_to_partner=capital + share,
        )
    if net_result < 0:
        loss_share = money(-net_result * terms.loss_rate / HUNDRED)
        deducted = min(loss_share, capital)
        return PartnerShare(
            partnership_id=terms.partnership_id,
            partner_id=terms.partner_id,
            partner_name=terms.partner_name,
            owner_capital=terms.owner_capital,
            partner_capital=capital,
            profit_rate=terms.profit_rate,
            loss_rate=terms.loss_rate,
            rate=terms.loss_rate,
            share=-loss_share,
            capital_deducted=deducted,
            uncovered_loss=loss_share - deducted,
            capital_to_return=capital - deducted,
            payable_to_partner=capital - deducted,
        )
    return PartnerShare(
        partnership_id=terms.partnership_id,
        partner_id=terms.partner_id,
        partner_name=terms.partner_name,
        owner_capital=terms.owner_capital,
        partner_capital=capital,
        profit_rate=terms.profit_rate,
        loss_rate=terms.loss_rate,
        rate=None,
        share=ZERO,
        capital_deducted=ZERO,
        uncovered_loss=ZERO,
        capital_to_return=capital,
        payable_to_partner=capital,
    )


def lot_result(snapshot: LotSnapshot) -> ComputedResult:
    """The result of one lot, so far (an open lot) or final (a lot being closed), with every step."""
    revenue = _sum(sale.revenue for sale in snapshot.sales)
    cogs = _sum(sale.cost for sale in snapshot.sales)
    spoilage = _sum(row.value for row in snapshot.stock_rows)
    groups = cost_groups(snapshot.costs)
    costs_total = _sum(group.total for group in groups)
    net_result = revenue - cogs - spoilage - costs_total
    share = partner_share(snapshot.partnership, net_result) if snapshot.partnership is not None else None
    owner_share = net_result - share.share if share is not None else net_result

    steps = [
        Step(code="revenue", sign="+", amount=revenue),
        Step(code="cogs", sign="-", amount=cogs),
        Step(code="spoilage", sign="-", amount=spoilage),
        *(Step(code="cost", sign="-", amount=group.total, kind=group.kind) for group in groups),
        Step(code="net_result", sign="=", amount=net_result),
    ]
    if share is not None:
        steps += [
            Step(code="partner_share", sign="=", amount=share.share, rate=share.rate),
            Step(code="owner_share", sign="=", amount=owner_share),
            Step(code="partner_capital", sign="+", amount=share.partner_capital),
        ]
        if share.capital_deducted:
            steps.append(Step(code="capital_deducted", sign="-", amount=share.capital_deducted))
        steps.append(Step(code="capital_to_return", sign="=", amount=share.capital_to_return))
        if share.share > 0:
            steps.append(Step(code="profit_share", sign="+", amount=share.share))
        steps.append(Step(code="payable_to_partner", sign="=", amount=share.payable_to_partner))
        if share.uncovered_loss:
            steps.append(Step(code="uncovered_loss", sign="=", amount=share.uncovered_loss))

    kept = snapshot.received_quantity - snapshot.returned_quantity
    return ComputedResult(
        snapshot=snapshot,
        quantity_sold=_sum(sale.quantity for sale in snapshot.sales),
        quantity_written_off=_sum(row.quantity for row in snapshot.stock_rows),
        revenue=revenue,
        cogs=cogs,
        spoilage=spoilage,
        cost_groups=groups,
        costs_total=costs_total,
        net_result=net_result,
        outcome=outcome_of(net_result),
        owner_share=owner_share,
        partner=share,
        purchase_cost=money(kept * snapshot.unit_cost),
        stock_value=money(snapshot.on_hand_quantity * snapshot.unit_cost),
        steps=tuple(steps),
    )


# ---- To JSON, for the frozen copy and the API ----


def plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    return value


def _fields(instance: Any, names: tuple[str, ...]) -> dict[str, Any]:
    return {name: plain(getattr(instance, name)) for name in names}


def to_json(result: ComputedResult) -> dict[str, Any]:
    """The result as plain JSON (amounts as strings, dates ISO): kept frozen when the lot closes and sent
    by the API as is, so the live and the frozen result read the same way."""
    snapshot = result.snapshot
    return {
        "batch": {
            **_fields(
                snapshot,
                (
                    "batch_id",
                    "batch_number",
                    "product_name",
                    "supplier_name",
                    "received_on",
                    "unit_cost",
                    "received_quantity",
                    "returned_quantity",
                    "on_hand_quantity",
                ),
            ),
        },
        "quantity_sold": plain(result.quantity_sold),
        "quantity_written_off": plain(result.quantity_written_off),
        "revenue": plain(result.revenue),
        "cogs": plain(result.cogs),
        "spoilage": plain(result.spoilage),
        "costs_total": plain(result.costs_total),
        "net_result": plain(result.net_result),
        "outcome": result.outcome,
        "owner_share": plain(result.owner_share),
        "purchase_cost": plain(result.purchase_cost),
        "stock_value": plain(result.stock_value),
        "sales": [
            _fields(
                sale,
                (
                    "sale_id",
                    "sale_number",
                    "sold_on",
                    "customer",
                    "quantity",
                    "unit_price",
                    "revenue",
                    "cost",
                    "amount_due",
                ),
            )
            for sale in snapshot.sales
        ],
        "stock_rows": [
            {
                **_fields(row, ("movement_id", "kind", "occurred_on", "quantity", "unit_cost", "reason")),
                "value": plain(row.value),
            }
            for row in snapshot.stock_rows
        ],
        "cost_groups": [
            {
                "kind": group.kind,
                "total": plain(group.total),
                "lines": [
                    _fields(
                        line,
                        (
                            "kind",
                            "on",
                            "title",
                            "amount",
                            "description",
                            "source_type",
                            "source_id",
                            "reference",
                            "detail",
                            "category_id",
                        ),
                    )
                    for line in group.lines
                ],
            }
            for group in result.cost_groups
        ],
        "partner": (
            _fields(
                result.partner,
                (
                    "partnership_id",
                    "partner_id",
                    "partner_name",
                    "owner_capital",
                    "partner_capital",
                    "profit_rate",
                    "loss_rate",
                    "rate",
                    "share",
                    "capital_deducted",
                    "uncovered_loss",
                    "capital_to_return",
                    "payable_to_partner",
                ),
            )
            if result.partner is not None
            else None
        ),
        "steps": [_fields(step, ("code", "sign", "amount", "kind", "rate")) for step in result.steps],
    }
