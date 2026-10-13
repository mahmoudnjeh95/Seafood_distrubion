"""The lot result as the API sends it. The same serializers read the live result and the frozen copy:
both are `engine.to_json` dicts (amounts as strings, dates ISO)."""

from typing import Any

from rest_framework import serializers

from apps.closing.models import (
    LotOutcome,
    LotResultStatus,
    LotState,
    MonthlyClosingStatus,
    MonthState,
    SettlementState,
)
from apps.partnerships.selectors import ProfitShareKind, SettlementPaymentMethod


def _money(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(read_only=True, max_digits=14, decimal_places=3, **kwargs)


def _quantity(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(read_only=True, max_digits=12, decimal_places=3, **kwargs)


def _rate(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(read_only=True, max_digits=5, decimal_places=2, **kwargs)


class ResultBatchSerializer(serializers.Serializer[Any]):
    batch_id = serializers.IntegerField(read_only=True)
    batch_number = serializers.CharField(read_only=True)
    product_name = serializers.CharField(read_only=True)
    supplier_name = serializers.CharField(read_only=True)
    received_on = serializers.DateField(read_only=True)
    unit_cost = _money()
    received_quantity = _quantity()
    returned_quantity = _quantity()
    on_hand_quantity = _quantity()


class ResultSaleSerializer(serializers.Serializer[Any]):
    sale_id = serializers.IntegerField(read_only=True)
    sale_number = serializers.CharField(read_only=True)
    sold_on = serializers.DateField(read_only=True)
    customer = serializers.CharField(read_only=True)
    quantity = _quantity()
    unit_price = _money()
    revenue = _money()
    cost = _money()
    amount_due = _money()


class ResultStockRowSerializer(serializers.Serializer[Any]):
    movement_id = serializers.IntegerField(read_only=True)
    # The ledger's movement kind: "loss", "count_correction" or "adjustment".
    kind = serializers.CharField(read_only=True)
    occurred_on = serializers.DateField(read_only=True)
    # Signed: + kg written off, − kg found again.
    quantity = _quantity()
    unit_cost = _money()
    reason = serializers.CharField(read_only=True)
    value = _money()


class ResultCostLineSerializer(serializers.Serializer[Any]):
    kind = serializers.CharField(read_only=True)
    on = serializers.DateField(read_only=True)
    title = serializers.CharField(read_only=True)
    amount = _money()
    description = serializers.CharField(read_only=True)
    # What the line links to: "expense" or "employee" (empty: nothing to open).
    source_type = serializers.CharField(read_only=True)
    source_id = serializers.IntegerField(read_only=True, allow_null=True)
    reference = serializers.CharField(read_only=True)
    detail = serializers.CharField(read_only=True)
    category_id = serializers.IntegerField(read_only=True, allow_null=True)


class ResultCostGroupSerializer(serializers.Serializer[Any]):
    # "lot" (typed on it), "truck_day", "employee", and the kinds later phases add ("cold_room"...).
    kind = serializers.CharField(read_only=True)
    total = _money()
    lines = ResultCostLineSerializer(many=True, read_only=True)


class ResultPartnerSerializer(serializers.Serializer[Any]):
    partnership_id = serializers.IntegerField(read_only=True)
    partner_id = serializers.IntegerField(read_only=True)
    partner_name = serializers.CharField(read_only=True)
    owner_capital = _money()
    partner_capital = _money()
    profit_rate = _rate()
    loss_rate = _rate()
    rate = _rate(allow_null=True)
    # Signed: + their part of a profit, − their part of a loss.
    share = _money()
    capital_deducted = _money()
    uncovered_loss = _money()
    capital_to_return = _money()
    payable_to_partner = _money()


class ResultStepSerializer(serializers.Serializer[Any]):
    code = serializers.CharField(read_only=True)
    sign = serializers.CharField(read_only=True)
    amount = _money()
    kind = serializers.CharField(read_only=True)
    rate = _rate(allow_null=True)


class ComputedResultSerializer(serializers.Serializer[Any]):
    batch = ResultBatchSerializer(read_only=True)
    quantity_sold = _quantity()
    quantity_written_off = _quantity()
    revenue = _money()
    cogs = _money()
    spoilage = _money()
    costs_total = _money()
    net_result = _money()
    outcome = serializers.ChoiceField(choices=LotOutcome.choices, read_only=True)
    owner_share = _money()
    purchase_cost = _money()
    stock_value = _money()
    sales = ResultSaleSerializer(many=True, read_only=True)
    stock_rows = ResultStockRowSerializer(many=True, read_only=True)
    cost_groups = ResultCostGroupSerializer(many=True, read_only=True)
    partner = ResultPartnerSerializer(read_only=True, allow_null=True)
    steps = ResultStepSerializer(many=True, read_only=True)


class ClosingCheckSerializer(serializers.Serializer[Any]):
    # "stock_empty", "costs_approved", "customers_paid".
    code = serializers.CharField(read_only=True)
    ok = serializers.BooleanField(read_only=True)
    blocking = serializers.BooleanField(read_only=True)
    quantity = _quantity(allow_null=True)
    count = serializers.IntegerField(read_only=True, allow_null=True)
    amount = _money(allow_null=True)


class LotClosingSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    status = serializers.ChoiceField(choices=LotResultStatus.choices, read_only=True)
    net_result = _money()
    closed_at = serializers.DateTimeField(read_only=True)
    closed_by_name = serializers.CharField(read_only=True)
    payments_unverified = serializers.BooleanField(read_only=True)
    reopened_at = serializers.DateTimeField(read_only=True, allow_null=True)
    reopened_by_name = serializers.CharField(read_only=True)
    reopen_reason = serializers.CharField(read_only=True)


class LotResultViewSerializer(serializers.Serializer[Any]):
    batch_id = serializers.IntegerField(read_only=True)
    # "open": the result so far, live. "closed": the frozen result of the closing.
    state = serializers.ChoiceField(choices=LotState.choices, read_only=True)
    result = ComputedResultSerializer(read_only=True)
    # Open lot: what a closing needs now. Closed lot: the checks as they were at the closing.
    checks = ClosingCheckSerializer(many=True, read_only=True)
    can_close = serializers.BooleanField(read_only=True)
    closing = LotClosingSerializer(read_only=True, allow_null=True)
    # Closed lot: the net result if it were computed now. A difference comes from a cost or a sale
    # recorded after the closing; it goes to the partner's next settlement (D-041, P6-T03).
    live_net_result = _money(allow_null=True)
    # Earlier closings of this lot that were reopened, newest first.
    history = LotClosingSerializer(many=True, read_only=True)


class CloseLotSerializer(serializers.Serializer[Any]):
    # The person closing confirms every cost of the lot is typed: the system cannot know it.
    costs_confirmed = serializers.BooleanField(required=False, default=False)


class ReopenLotSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=300, allow_blank=True)


# ---- Settlement with the partner (P6-T03, D-066) ----


class SettlementPreviewSerializer(serializers.Serializer[Any]):
    # Capital still in the lot after a loss share was taken: paid back whole.
    capital_to_return = _money()
    # The lot's share, signed (+ profit share, − loss share already taken from the capital).
    lot_share = _money()
    # The part of a loss their capital could not cover (they owe it).
    uncovered_loss = _money()
    # Late costs of this partner's closed lots still to carry to this settlement (signed).
    pending_adjustments = _money()
    # The partner's profit-share balance over all their lots, with those adjustments: + owed to them,
    # − owed by them.
    carried_in = _money()
    # Paid out of the profit share, and in total with the capital: what the payments must add up to.
    share_paid = _money()
    total = _money()
    # What they still owe after this settlement (0 or negative): recovered from their next share.
    carried_out = _money()


class SettlementPaymentSerializer(serializers.Serializer[Any]):
    paid_on = serializers.DateField(read_only=True)
    amount = _money()
    method = serializers.ChoiceField(choices=SettlementPaymentMethod.choices, read_only=True)
    reference = serializers.CharField(read_only=True)


class SettlementRecordSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    settled_on = serializers.DateField(read_only=True)
    capital_returned = _money()
    lot_share = _money()
    uncovered_loss = _money()
    carried_in = _money()
    share_paid = _money()
    amount_paid = _money()
    carried_out = _money()
    notes = serializers.CharField(read_only=True)
    created_by_name = serializers.CharField(read_only=True)
    payments = SettlementPaymentSerializer(many=True, read_only=True)


class ProfitShareEntrySerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    kind = serializers.ChoiceField(choices=ProfitShareKind.choices, read_only=True)
    # Signed: + the company owes the partner, − the partner owes the company.
    amount = _money()
    entry_date = serializers.DateField(read_only=True)
    note = serializers.CharField(read_only=True)


class LateAdjustmentSerializer(serializers.Serializer[Any]):
    # live net result − frozen net result: a cost recorded after the closing is negative.
    drift = _money()
    # The part of it already carried to the partner's balance, and the part still to carry.
    booked = _money()
    pending_basis = _money()
    # The partner's share of the part still to carry (signed): the next settlement's adjustment.
    pending_share = _money()


class LotFigureSerializer(serializers.Serializer[Any]):
    """The main figures of one closed lot, for the list of partnership lots."""

    batch_id = serializers.IntegerField(read_only=True)
    outcome = serializers.ChoiceField(choices=LotOutcome.choices, read_only=True)
    revenue = _money()
    costs_total = _money()
    net_result = _money()
    partner_share = _money()
    capital_to_return = _money()


class PartnerBalancesSerializer(serializers.Serializer[Any]):
    """The three balances of a partner, kept apart: never added together (D-031, D-040)."""

    partner_id = serializers.IntegerField(read_only=True)
    partner_name = serializers.CharField(read_only=True)
    # Owed for goods bought from them (supplier invoices less payments, D-043).
    trade_payable = _money()
    # Their money still in the company's lots.
    capital = _money()
    # + owed to them, − owed by them (an uncovered loss, a late cost).
    profit_share = _money()
    lots = serializers.IntegerField(read_only=True)


class LotSettlementViewSerializer(serializers.Serializer[Any]):
    batch_id = serializers.IntegerField(read_only=True)
    state = serializers.ChoiceField(choices=SettlementState.choices, read_only=True)
    partnership_id = serializers.IntegerField(read_only=True, allow_null=True)
    partner_id = serializers.IntegerField(read_only=True, allow_null=True)
    partner_name = serializers.CharField(read_only=True)
    # What settling would pay now (state "ready"); None otherwise.
    preview = SettlementPreviewSerializer(read_only=True, allow_null=True)
    # The recorded settlement (state "settled").
    settlement = SettlementRecordSerializer(read_only=True, allow_null=True)
    # A cost or a sale recorded after the lot closed (D-041); None without a closed partnership lot.
    late = LateAdjustmentSerializer(read_only=True, allow_null=True)
    # The partner's profit-share ledger in this lot, oldest first.
    entries = ProfitShareEntrySerializer(many=True, read_only=True)
    balances = PartnerBalancesSerializer(read_only=True, allow_null=True)


class SettlementPaymentWriteSerializer(serializers.Serializer[Any]):
    # Amount in DT as a string ("1286.000"), checked by the service.
    amount = serializers.CharField(allow_blank=True)
    method = serializers.ChoiceField(choices=SettlementPaymentMethod.choices)
    paid_on = serializers.DateField(required=False)
    reference = serializers.CharField(required=False, allow_blank=True, max_length=50, default="")


class SettleLotSerializer(serializers.Serializer[Any]):
    # The ways the partner is paid; they must add up to the amount to settle (none when it is 0).
    payments = SettlementPaymentWriteSerializer(many=True, required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


# ---- The monthly closing (P6-T05, P6-T06, D-073, D-074) ----


class MonthSalesSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField(read_only=True)
    quantity = _quantity()
    # Without VAT, net of the credit notes of the month.
    revenue = _money()


class MonthSpoilageSerializer(serializers.Serializer[Any]):
    quantity = _quantity()
    value = _money()


class MonthCategorySerializer(serializers.Serializer[Any]):
    category_id = serializers.IntegerField(read_only=True)
    code = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    count = serializers.IntegerField(read_only=True)
    total = _money()


class MonthExpensesSerializer(serializers.Serializer[Any]):
    categories = MonthCategorySerializer(many=True, read_only=True)
    total = _money()


class PartnerCostCategorySerializer(serializers.Serializer[Any]):
    # Stable within the month: the expense category name, or "employee" for day and monthly salaries.
    key = serializers.CharField(read_only=True)
    # Empty for "employee": the screen shows a fixed label instead of an employee's name.
    name = serializers.CharField(read_only=True)
    is_employee = serializers.BooleanField(read_only=True)
    # None for "employee": nothing to filter the expenses list by.
    category_id = serializers.IntegerField(read_only=True, allow_null=True)
    amount = _money()
    count = serializers.IntegerField(read_only=True)


class PartnerCostShareSerializer(serializers.Serializer[Any]):
    """One partner's part of the month's shared costs (rent, electricity, fuel, salaries...): the raw cost
    their lots carried, by category, not weighted by their profit or loss %."""

    partner_id = serializers.IntegerField(read_only=True)
    partner_name = serializers.CharField(read_only=True)
    total = _money()
    categories = PartnerCostCategorySerializer(many=True, read_only=True)


class MonthLedgerSerializer(serializers.Serializer[Any]):
    # The ledger's movement kind: "receipt", "sale", "loss"...
    kind = serializers.CharField(read_only=True)
    # Signed: + more stock, - less.
    quantity = _quantity()
    value = _money()


class MonthStockRowSerializer(serializers.Serializer[Any]):
    batch_id = serializers.IntegerField(read_only=True)
    batch_number = serializers.CharField(read_only=True)
    product_name = serializers.CharField(read_only=True)
    supplier_name = serializers.CharField(read_only=True)
    received_on = serializers.DateField(read_only=True)
    quantity = _quantity()
    unit_cost = _money()
    value = _money()


class MonthStockSerializer(serializers.Serializer[Any]):
    opening_value = _money()
    purchases = _money()
    closing_value = _money()
    # Rounding only (millimes): the lot-by-lot valuation against the ledger's roll-forward.
    rounding_difference = _money()
    ledger = MonthLedgerSerializer(many=True, read_only=True)
    rows = MonthStockRowSerializer(many=True, read_only=True)


class MonthReportSerializer(serializers.Serializer[Any]):
    month = serializers.DateField(read_only=True)
    sales = MonthSalesSerializer(read_only=True)
    # Cost of the goods sold, from the sale-line snapshots (never purchases).
    cogs = _money()
    gross_margin = _money()
    spoilage = MonthSpoilageSerializer(read_only=True)
    expenses = MonthExpensesSerializer(read_only=True)
    personnel = _money()
    operating_costs = _money()
    net_result = _money()
    # Only partners with a cost line this month; absent on an old frozen closing from before this field.
    partner_costs = PartnerCostShareSerializer(many=True, read_only=True, required=False)
    stock = MonthStockSerializer(read_only=True)
    checks = ClosingCheckSerializer(many=True, read_only=True)


class MonthClosingSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    status = serializers.ChoiceField(choices=MonthlyClosingStatus.choices, read_only=True)
    net_result = _money()
    reviewed_at = serializers.DateTimeField(read_only=True)
    reviewed_by_name = serializers.CharField(read_only=True)
    review_notes = serializers.CharField(read_only=True)
    approved_at = serializers.DateTimeField(read_only=True, allow_null=True)
    approved_by_name = serializers.CharField(read_only=True)
    reopened_at = serializers.DateTimeField(read_only=True, allow_null=True)
    reopened_by_name = serializers.CharField(read_only=True)
    reopen_reason = serializers.CharField(read_only=True)


class MonthViewSerializer(serializers.Serializer[Any]):
    month = serializers.DateField(read_only=True)
    state = serializers.ChoiceField(choices=MonthState.choices, read_only=True)
    # False for the current month: it cannot be closed before its last day.
    is_over = serializers.BooleanField(read_only=True)
    # Live figures while open or reviewed; the frozen ones once approved.
    report = MonthReportSerializer(read_only=True)
    can_review = serializers.BooleanField(read_only=True)
    can_approve = serializers.BooleanField(read_only=True)
    closing = MonthClosingSerializer(read_only=True, allow_null=True)
    # Approved month: the net result if computed now. A difference is an expense or a sale recorded after.
    live_net_result = _money(allow_null=True)
    history = MonthClosingSerializer(many=True, read_only=True)


class MonthRowSerializer(serializers.Serializer[Any]):
    month = serializers.DateField(read_only=True)
    state = serializers.ChoiceField(choices=MonthState.choices, read_only=True)
    is_over = serializers.BooleanField(read_only=True)
    # The reviewed or approved net result; empty while the month is open.
    net_result = _money(allow_null=True)


class ReviewMonthSerializer(serializers.Serializer[Any]):
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class ReopenMonthSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=300, allow_blank=True)


# ---- The owner's dashboard (P7-T01, D-104) ----


class OverdueCustomerSerializer(serializers.Serializer[Any]):
    customer_id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    overdue = _money()


class LowStockSerializer(serializers.Serializer[Any]):
    product_id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    min_stock = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class ExpiringBatchSerializer(serializers.Serializer[Any]):
    batch_id = serializers.IntegerField(read_only=True)
    batch_number = serializers.CharField(read_only=True)
    product_name = serializers.CharField(read_only=True)
    use_by = serializers.DateField(read_only=True)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class CashDifferenceSerializer(serializers.Serializer[Any]):
    closing_id = serializers.IntegerField(read_only=True)
    day = serializers.DateField(read_only=True)
    driver_name = serializers.CharField(read_only=True)
    # Counted minus expected: negative means less cash than the records say.
    difference = _money()


class PendingTermsSerializer(serializers.Serializer[Any]):
    partnership_id = serializers.IntegerField(read_only=True)
    batch_id = serializers.IntegerField(read_only=True)
    batch_number = serializers.CharField(read_only=True)
    partner_name = serializers.CharField(read_only=True)


class DashboardSerializer(serializers.Serializer[Any]):
    # The first day of the current month: every figure is this month up to today.
    month = serializers.DateField(read_only=True)
    # Profit: what the business earned.
    sales = _money()
    previous_sales = _money()
    gross_margin = _money()
    net_result = _money()
    # Cash: what came in. Receivables are sold and not yet paid.
    cash_collected = _money()
    receivables = _money()
    receivables_overdue = _money()
    # Stock held, at cost.
    stock_value = _money()
    # Alerts: the biggest overdue customers (at most five) and how many there are in all, the driver days
    # waiting for the office, and expenses waiting for approval.
    overdue_customers = OverdueCustomerSerializer(many=True, read_only=True)
    overdue_customer_count = serializers.IntegerField(read_only=True)
    days_waiting = serializers.IntegerField(read_only=True)
    expenses_waiting = serializers.IntegerField(read_only=True)
    # Products under their minimum stock, lots whose use-by date is within three days (or past) and still in
    # stock, and driver days with a cash difference nobody explained: at most five of each, and the full count.
    low_stock = LowStockSerializer(many=True, read_only=True)
    low_stock_count = serializers.IntegerField(read_only=True)
    expiring = ExpiringBatchSerializer(many=True, read_only=True)
    expiring_count = serializers.IntegerField(read_only=True)
    cash_differences = CashDifferenceSerializer(many=True, read_only=True)
    cash_difference_count = serializers.IntegerField(read_only=True)
    # Partner lots whose capital and rates are still to fill in (D-100): the lot cannot close before.
    pending_terms = PendingTermsSerializer(many=True, read_only=True)
    pending_terms_count = serializers.IntegerField(read_only=True)
