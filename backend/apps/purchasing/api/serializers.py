import itertools
from decimal import Decimal
from typing import Any

from django.urls import reverse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.money import line_total
from apps.purchasing import selectors, services
from apps.purchasing.models import (
    LINE_METHOD_CHOICES,
    FieldPurchase,
    FieldPurchaseLine,
    FieldPurchasePayment,
    FieldPurchaseRevision,
    FieldPurchaseStatus,
    GoodsReceipt,
    GoodsReceiptLine,
    PaymentMethod,
    PaymentTerms,
    PlanLineStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    SupplierInvoice,
    SupplierInvoiceStatus,
    SupplierPayment,
    SupplierPaymentLine,
)
from apps.treasury import selectors as treasury

AMOUNT = serializers.DecimalField(max_digits=14, decimal_places=3)
ZERO = Decimal("0.000")


@extend_schema_field(OpenApiTypes.BINARY)
class UploadedPaperField(serializers.FileField):
    """A file sent in a multipart form: a Blob in the generated client, not a URL."""


class RefSerializer(serializers.Serializer[Any]):
    """A supplier or a product, as shown on a receipt."""

    id = serializers.IntegerField(read_only=True)
    reference = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class ReceiptLocationSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class ReceiptBatchSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    use_by = serializers.DateField(read_only=True, allow_null=True)


class ReceiptLineSerializer(serializers.ModelSerializer[GoodsReceiptLine]):
    product = RefSerializer(read_only=True)
    batch = ReceiptBatchSerializer(read_only=True)
    # Invoiced weight × cost: what the supplier charges for the line.
    invoiced_amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Accepted weight × cost: the value that entered stock.
    accepted_amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    has_difference = serializers.BooleanField(read_only=True)

    class Meta:
        model = GoodsReceiptLine
        fields: tuple[str, ...] = (
            "id",
            "product",
            "batch",
            "ordered_quantity",
            "invoiced_quantity",
            "accepted_quantity",
            "unit_cost",
            "invoiced_amount",
            "accepted_amount",
            "has_difference",
        )
        read_only_fields: tuple[str, ...] = fields


class InvoiceRefSerializer(serializers.Serializer[Any]):
    """The supplier invoice a receipt is charged on."""

    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    status = serializers.ChoiceField(choices=SupplierInvoiceStatus.choices, read_only=True)


class OrderRefSerializer(serializers.Serializer[Any]):
    """The purchase order a receipt delivers against."""

    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    status = serializers.ChoiceField(choices=PurchaseOrderStatus.choices, read_only=True)


class ReceiptSerializer(serializers.ModelSerializer[GoodsReceipt]):
    supplier = RefSerializer(read_only=True)
    # The commande d'achat this delivery is against, or null for goods that came without one.
    purchase_order = OrderRefSerializer(read_only=True, allow_null=True)
    location = ReceiptLocationSerializer(read_only=True)
    lines = ReceiptLineSerializer(many=True, read_only=True)
    has_differences = serializers.BooleanField(read_only=True)
    invoiced_total = serializers.SerializerMethodField()
    accepted_total = serializers.SerializerMethodField()
    # The supplier invoice it is on (draft or posted), or null while not invoiced.
    invoice = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = GoodsReceipt
        fields = (
            "id",
            "number",
            "supplier",
            "location",
            "purchase_order",
            "received_on",
            "supplier_reference",
            "with_vat",
            "notes",
            "lines",
            "has_differences",
            "invoiced_total",
            "accepted_total",
            "invoice",
            "created_by",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(AMOUNT)
    def get_invoiced_total(self, receipt: GoodsReceipt) -> str:
        return str(selectors.receipt_totals(receipt)[0])

    @extend_schema_field(AMOUNT)
    def get_accepted_total(self, receipt: GoodsReceipt) -> str:
        return str(selectors.receipt_totals(receipt)[1])

    @extend_schema_field(InvoiceRefSerializer(allow_null=True))
    def get_invoice(self, receipt: GoodsReceipt) -> dict[str, Any] | None:
        link = getattr(receipt, "invoice_link", None)
        return None if link is None else dict(InvoiceRefSerializer(link.invoice).data)

    def get_created_by(self, receipt: GoodsReceipt) -> str:
        user = receipt.created_by
        if user is None:
            return ""
        return f"{user.first_name} {user.last_name}".strip() or user.username


class ReceiptLineWriteSerializer(serializers.Serializer[Any]):
    product = serializers.IntegerField(min_value=1)
    # Weights and cost travel as strings ("62.000") and are checked by the service, which reports each
    # problem on `lines.<index>.<field>`.
    ordered_quantity = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    invoiced_quantity = serializers.CharField(allow_blank=True)
    accepted_quantity = serializers.CharField(allow_blank=True)
    unit_cost = serializers.CharField(allow_blank=True)
    use_by = serializers.DateField(required=False, allow_null=True, default=None)
    # Buy this lot together with a partner supplier (D-100): the owner's choice, the receipt's own supplier
    # allowed. Capital and percentages are filled in later, on the lot.
    partner = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)


class FieldPurchasePaymentWriteSerializer(serializers.Serializer[Any]):
    method = serializers.ChoiceField(choices=LINE_METHOD_CHOICES)
    amount = serializers.CharField(allow_blank=True)
    reference = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    cash_on = serializers.DateField(required=False, allow_null=True, default=None)


class ReceiptWriteSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(min_value=1)
    location = serializers.IntegerField(min_value=1)
    # Deliver against this commande d'achat: its products only, as much of each as arrived (D-076).
    purchase_order = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    received_on = serializers.DateField()
    supplier_reference = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    # Bought with VAT: what is sold from these lots must be invoiced with VAT (D-202).
    with_vat = serializers.BooleanField(required=False, default=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = ReceiptLineWriteSerializer(many=True, allow_empty=True)
    # Returnable boxes that came with the delivery, per box type ("small", "big"): a count, never kg (D-122).
    boxes = serializers.DictField(child=serializers.IntegerField(min_value=0), required=False, default=dict)
    # Owed at once (D-159): a posted supplier invoice for this receipt, due by the deal made for the delivery.
    invoice_now = serializers.BooleanField(required=False, default=False)
    terms = serializers.ChoiceField(choices=PaymentTerms.choices, required=False, default=PaymentTerms.DAYS)
    due_days = serializers.IntegerField(min_value=0, max_value=365, required=False, default=30)
    # Given now (D-192): only with `invoice_now`; recorded and allocated to the invoice of this receipt.
    payments = FieldPurchasePaymentWriteSerializer(many=True, required=False, default=list)


class ReceiptFilterSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(required=False, min_value=1)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)
    # Only receipts with a weight difference on at least one line.
    differences = serializers.BooleanField(required=False, default=False)
    # Only receipts not on any supplier invoice yet (draft or posted).
    uninvoiced = serializers.BooleanField(required=False, default=False)
    # Only the receipts against this purchase order.
    purchase_order = serializers.IntegerField(required=False, min_value=1)


class ReceiptRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    received_on = serializers.DateField(read_only=True)
    supplier = RefSerializer(read_only=True)


class DifferenceLineSerializer(ReceiptLineSerializer):
    receipt = ReceiptRefSerializer(read_only=True)

    class Meta(ReceiptLineSerializer.Meta):
        fields = ("receipt", *ReceiptLineSerializer.Meta.fields)
        read_only_fields = fields


class DifferenceFilterSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(required=False, min_value=1)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


class LastCostSerializer(serializers.Serializer[Any]):
    """What was last paid a supplier for one product: the cost of their latest batch of it."""

    product_id = serializers.IntegerField(read_only=True)
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    received_on = serializers.DateField(read_only=True)
    batch_number = serializers.CharField(source="number", read_only=True)


class LastCostFilterSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(min_value=1)


# ---- Purchase orders, the "commande d'achat" (D-076) ----


class OrderReceiptRefSerializer(serializers.Serializer[Any]):
    """A delivery against an order: its receipt."""

    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    received_on = serializers.DateField(read_only=True)


class OrderLineSerializer(serializers.ModelSerializer[PurchaseOrderLine]):
    product = RefSerializer(read_only=True)
    ordered_amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Accepted weight of the receipts against this line, and what is still to come.
    received_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    remaining_quantity = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderLine
        fields: tuple[str, ...] = (
            "id",
            "product",
            "ordered_quantity",
            "unit_cost",
            "ordered_amount",
            "received_quantity",
            "remaining_quantity",
        )
        read_only_fields: tuple[str, ...] = fields

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=3))
    def get_remaining_quantity(self, line: PurchaseOrderLine) -> str:
        return str(selectors.order_line_remaining(line))


class OrderSerializer(serializers.ModelSerializer[PurchaseOrder]):
    supplier = RefSerializer(read_only=True)
    lines = OrderLineSerializer(many=True, read_only=True)
    receipts = serializers.SerializerMethodField()
    ordered_total = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = (
            "id",
            "number",
            "supplier",
            "ordered_on",
            "expected_on",
            "status",
            "notes",
            "lines",
            "receipts",
            "ordered_total",
            "created_by",
            "created_at",
            "closed_at",
        )
        read_only_fields = fields

    @extend_schema_field(OrderReceiptRefSerializer(many=True))
    def get_receipts(self, order: PurchaseOrder) -> list[dict[str, Any]]:
        return [dict(OrderReceiptRefSerializer(receipt).data) for receipt in order.receipts.all()]

    @extend_schema_field(AMOUNT)
    def get_ordered_total(self, order: PurchaseOrder) -> str:
        return str(sum((line.ordered_amount for line in order.lines.all()), Decimal("0.000")))

    def get_created_by(self, order: PurchaseOrder) -> str:
        user = order.created_by
        if user is None:
            return ""
        return f"{user.first_name} {user.last_name}".strip() or user.username


class OrderLineWriteSerializer(serializers.Serializer[Any]):
    product = serializers.IntegerField(min_value=1)
    # Strings, checked by the service, which reports each problem on `lines.<index>.<field>`.
    ordered_quantity = serializers.CharField(allow_blank=True)
    unit_cost = serializers.CharField(allow_blank=True)


class OrderWriteSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(min_value=1)
    ordered_on = serializers.DateField()
    expected_on = serializers.DateField(required=False, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = OrderLineWriteSerializer(many=True, allow_empty=True)


class OrderFilterSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(required=False, min_value=1)
    # `pending` = open or partly received: still waiting for goods.
    status = serializers.ChoiceField(choices=[*PurchaseOrderStatus.choices, ("pending", "pending")], required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)


# ---- Supplier invoices and payments (P1-T08, D-043) ----


class InvoiceReceiptRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    received_on = serializers.DateField(read_only=True)
    supplier_reference = serializers.CharField(read_only=True)


class InvoiceReceiptSerializer(serializers.Serializer[Any]):
    """A receipt charged on the invoice, with its invoiced amount (invoiced kg × cost of its lines)."""

    receipt = InvoiceReceiptRefSerializer(read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class PaymentRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    paid_on = serializers.DateField(read_only=True)
    method = serializers.ChoiceField(choices=LINE_METHOD_CHOICES, read_only=True)
    reference = serializers.CharField(read_only=True)


class InvoicePaymentSerializer(serializers.Serializer[Any]):
    """The part of one payment that settled the invoice."""

    id = serializers.IntegerField(read_only=True)
    payment = PaymentRefSerializer(read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


def _name_of(user: Any) -> str:
    if user is None:
        return ""
    return f"{user.first_name} {user.last_name}".strip() or str(user.username)


class SupplierInvoiceSerializer(serializers.ModelSerializer[SupplierInvoice]):
    supplier = RefSerializer(read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Allocated by payments so far; `outstanding` = total − paid.
    paid_amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    outstanding = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    is_overdue = serializers.SerializerMethodField()
    receipts = InvoiceReceiptSerializer(source="receipt_links", many=True, read_only=True)
    payments = InvoicePaymentSerializer(source="allocations", many=True, read_only=True)
    created_by = serializers.SerializerMethodField()
    posted_by = serializers.SerializerMethodField()

    class Meta:
        model = SupplierInvoice
        fields = (
            "id",
            "number",
            "supplier",
            "supplier_reference",
            "invoice_date",
            "due_date",
            "status",
            "total",
            "paid_amount",
            "outstanding",
            "is_overdue",
            "receipts",
            "payments",
            "notes",
            "created_by",
            "created_at",
            "posted_by",
            "posted_at",
        )
        read_only_fields = fields

    def get_is_overdue(self, invoice: SupplierInvoice) -> bool:
        """Posted, not fully paid, and its due date has passed."""
        return invoice.status in selectors.OPEN_STATUSES and invoice.due_date < timezone.localdate()

    def get_created_by(self, invoice: SupplierInvoice) -> str:
        return _name_of(invoice.created_by)

    def get_posted_by(self, invoice: SupplierInvoice) -> str:
        return _name_of(invoice.posted_by)


class SupplierInvoiceUpdateSerializer(serializers.Serializer[Any]):
    receipts = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=True)
    invoice_date = serializers.DateField()
    due_date = serializers.DateField()
    supplier_reference = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    # Post it in the same step: it becomes owed and no longer changes.
    post = serializers.BooleanField(required=False, default=False)


class SupplierInvoiceWriteSerializer(SupplierInvoiceUpdateSerializer):
    supplier = serializers.IntegerField(min_value=1)
    # With `post`: the supplier's advances (money given and on no invoice yet) pay it, oldest first (D-200).
    apply_advances = serializers.BooleanField(required=False, default=False)


class SupplierInvoiceFilterSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(required=False, min_value=1)
    # `open`: posted and not fully paid.
    status = serializers.ChoiceField(choices=["draft", "posted", "partly_paid", "paid", "open"], required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)
    # Only invoices still to pay whose due date has passed.
    overdue = serializers.BooleanField(required=False, default=False)


class PaymentInvoiceRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    supplier_reference = serializers.CharField(read_only=True)
    invoice_date = serializers.DateField(read_only=True)


class PaymentAllocationSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    invoice = PaymentInvoiceRefSerializer(read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class IssuedInstrumentSerializer(serializers.Serializer[Any]):
    """Our cheque or traite of a payment line, as the treasury follows it until the bank debits it (D-208)."""

    id = serializers.IntegerField(read_only=True)
    kind = serializers.ChoiceField(choices=treasury.INSTRUMENT_KIND_CHOICES, read_only=True)
    number = serializers.CharField(read_only=True)
    bank_code = serializers.CharField(source="bank.code", read_only=True, default="")
    bank_name = serializers.CharField(source="bank.name", read_only=True, default="")
    due_on = serializers.DateField(read_only=True)
    status = serializers.ChoiceField(choices=treasury.INSTRUMENT_STATUS_CHOICES, read_only=True)


class SupplierPaymentLineSerializer(serializers.ModelSerializer[SupplierPaymentLine]):
    method = serializers.ChoiceField(choices=LINE_METHOD_CHOICES, read_only=True)
    # Our cheque or traite, with its state in the treasury; null for cash, transfer, other.
    instrument = IssuedInstrumentSerializer(read_only=True, allow_null=True)

    class Meta:
        model = SupplierPaymentLine
        fields: tuple[str, ...] = ("id", "method", "amount", "reference", "instrument")
        read_only_fields: tuple[str, ...] = fields


class EffetEventSerializer(serializers.Serializer[Any]):
    """One step in the life of an effet: issued, debited, rejected, cancelled..."""

    from_status = serializers.CharField(read_only=True)
    to_status = serializers.ChoiceField(choices=treasury.INSTRUMENT_STATUS_CHOICES, read_only=True)
    happened_on = serializers.DateField(read_only=True)
    note = serializers.CharField(read_only=True)
    actor = serializers.SerializerMethodField()

    def get_actor(self, event: Any) -> str:
        return _name_of(event.actor)


class IssuedInstrumentDetailSerializer(IssuedInstrumentSerializer):
    # Oldest first.
    events = EffetEventSerializer(many=True, read_only=True)


class SupplierPaymentLineDetailSerializer(SupplierPaymentLineSerializer):
    instrument = IssuedInstrumentDetailSerializer(read_only=True, allow_null=True)


class SupplierPaymentSerializer(serializers.ModelSerializer[SupplierPayment]):
    supplier = RefSerializer(read_only=True)
    # `mixed` when the lines use several methods.
    method = serializers.ChoiceField(choices=PaymentMethod.choices, read_only=True)
    lines = SupplierPaymentLineSerializer(many=True, read_only=True)
    allocated_amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Not allocated to an invoice yet: an advance, already deducted from the supplier balance.
    unallocated_amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    allocations = PaymentAllocationSerializer(many=True, read_only=True)
    created_by = serializers.SerializerMethodField()
    is_voided = serializers.SerializerMethodField()
    voided_by = serializers.SerializerMethodField()

    class Meta:
        model = SupplierPayment
        fields = (
            "id",
            "number",
            "supplier",
            "paid_on",
            "amount",
            "method",
            "reference",
            "cash_on",
            "notes",
            "lines",
            "allocated_amount",
            "unallocated_amount",
            "allocations",
            "created_by",
            "created_at",
            "is_voided",
            "voided_at",
            "voided_by",
            "void_reason",
        )
        read_only_fields = fields

    def get_created_by(self, payment: SupplierPayment) -> str:
        return _name_of(payment.created_by)

    def get_is_voided(self, payment: SupplierPayment) -> bool:
        return payment.voided_at is not None

    def get_voided_by(self, payment: SupplierPayment) -> str:
        return _name_of(payment.voided_by)


class SupplierPaymentDetailSerializer(SupplierPaymentSerializer):
    """One règlement with the history of each of its effets."""

    lines = SupplierPaymentLineDetailSerializer(many=True, read_only=True)


class AllocationWriteSerializer(serializers.Serializer[Any]):
    invoice = serializers.IntegerField(min_value=1)
    # Travels as a string ("500.000"), checked by the service, which reports it on `allocations.<i>.amount`.
    amount = serializers.CharField(allow_blank=True)


class SupplierPaymentLineWriteSerializer(serializers.Serializer[Any]):
    """One means of the règlement (D-208). Our cheque or traite gives its number, bank and échéance."""

    method = serializers.ChoiceField(choices=LINE_METHOD_CHOICES)
    # A string ("500.000"), checked by the service, which reports it on `lines.<i>.amount`.
    amount = serializers.CharField(allow_blank=True)
    # A transfer reference.
    reference = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    number = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    bank = serializers.IntegerField(required=False, allow_null=True, min_value=1, default=None)
    due_on = serializers.DateField(required=False, allow_null=True, default=None)


class SupplierPaymentWriteSerializer(serializers.Serializer[Any]):
    """A règlement: its means in `lines` (D-208), or one means in `amount`, `method`, `reference`, `cash_on`."""

    supplier = serializers.IntegerField(min_value=1)
    paid_on = serializers.DateField()
    # A string ("1255.500"), checked by the service: a typed "1255,5" is refused, not rounded. With `lines`, it
    # may be left out; given, it must equal their sum.
    amount = serializers.CharField(required=False, allow_blank=True)
    method = serializers.ChoiceField(choices=LINE_METHOD_CHOICES, required=False)
    reference = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    # The day a post-dated cheque or a traite may be cashed (D-176).
    cash_on = serializers.DateField(required=False, allow_null=True, default=None)
    lines = SupplierPaymentLineWriteSerializer(many=True, required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    allocations = AllocationWriteSerializer(many=True, required=False, default=list)
    # True: spread the amount over the invoices still to pay, the one due first first (`allocations` ignored).
    auto_allocate = serializers.BooleanField(required=False, default=False)
    # An open plan line (D-192) this payment settles; its invoice must be one of the allocations.
    plan_line = serializers.IntegerField(required=False, allow_null=True, min_value=1, default=None)
    # Several open plan lines paid by this one règlement (D-208).
    plan_lines = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, default=list)


class PaymentAllocateSerializer(serializers.Serializer[Any]):
    allocations = AllocationWriteSerializer(many=True, allow_empty=True)


class SupplierPaymentFilterSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(required=False, min_value=1)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)
    # Only payments with a part not allocated to an invoice yet.
    unallocated = serializers.BooleanField(required=False, default=False)
    # Days paid, inclusive.
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    # Those with a line of this means; `mixed`: those with several means.
    method = serializers.ChoiceField(choices=PaymentMethod.choices, required=False)
    # `active` (not voided), `voided`, or `unallocated` (an advance left).
    state = serializers.ChoiceField(choices=["active", "voided", "unallocated"], required=False)


class PaymentTotalsSerializer(serializers.Serializer[Any]):
    """The totals of the filtered règlements, voided ones left out (their number is in `voided`)."""

    count = serializers.IntegerField(read_only=True)
    voided = serializers.IntegerField(read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    allocated = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    unallocated = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Paid by each means, from the lines ({"cash": "500.000", "cheque": ...}).
    by_method = serializers.DictField(child=serializers.DecimalField(max_digits=14, decimal_places=3), read_only=True)


class PaymentVoidSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(allow_blank=True, max_length=255)


class SupplierBalanceSerializer(serializers.Serializer[Any]):
    """The trade balance with one supplier. A partner's capital and profit share are other balances (D-040)."""

    supplier_id = serializers.IntegerField(read_only=True)
    invoiced = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    paid = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Posted invoices − payments: what is owed; negative when the supplier holds an advance.
    balance = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    outstanding = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    unallocated = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    overdue = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    open_invoices = serializers.IntegerField(read_only=True)
    overdue_invoices = serializers.IntegerField(read_only=True)
    draft_invoices = serializers.IntegerField(read_only=True)
    draft_total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Received but on no invoice yet: not owed until the supplier's invoice is recorded.
    uninvoiced_receipts = serializers.IntegerField(read_only=True)
    uninvoiced_total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


# ---- Buying at the port, the "achat terrain" (P3-T12, D-176) ----


class NamedRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class NumberRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)


class FieldPurchaseLineSerializer(serializers.ModelSerializer[FieldPurchaseLine]):
    product = RefSerializer(read_only=True, allow_null=True)
    partner = NamedRefSerializer(read_only=True, allow_null=True)
    # The kg received once counted, else the kg typed at the port: what the supplier is paid for.
    owed_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)

    class Meta:
        model = FieldPurchaseLine
        fields: tuple[str, ...] = (
            "id",
            "product",
            "proposed_product",
            "declared_quantity",
            "received_quantity",
            "owed_quantity",
            "unit_cost",
            "amount",
            "partner",
        )
        read_only_fields: tuple[str, ...] = fields


class FieldPurchasePaymentSerializer(serializers.ModelSerializer[FieldPurchasePayment]):
    # The supplier payment it became at validation.
    supplier_payment = NumberRefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = FieldPurchasePayment
        fields: tuple[str, ...] = ("id", "method", "amount", "reference", "cash_on", "supplier_payment")
        read_only_fields: tuple[str, ...] = fields


class RevisionChangeSerializer(serializers.Serializer[Any]):
    # supplier, bought_on, boxes.small, lines.received_quantity, lines.added, payments.amount...
    field = serializers.CharField(read_only=True)
    # The position (from 0) of the line or payment, for their fields.
    line = serializers.IntegerField(read_only=True, allow_null=True)
    before = serializers.CharField(read_only=True, allow_null=True)
    after = serializers.CharField(read_only=True, allow_null=True)


class FieldPurchaseRevisionSerializer(serializers.ModelSerializer[FieldPurchaseRevision]):
    created_by = serializers.SerializerMethodField()
    # What this revision changed against the one before.
    changes = serializers.SerializerMethodField()

    class Meta:
        model = FieldPurchaseRevision
        fields = ("number", "action", "created_at", "created_by", "note", "changes")
        read_only_fields = fields

    def get_created_by(self, revision: FieldPurchaseRevision) -> str:
        return _name_of(revision.created_by)

    @extend_schema_field(RevisionChangeSerializer(many=True))
    def get_changes(self, revision: FieldPurchaseRevision) -> list[dict[str, Any]]:
        previous = self.context.get("previous", {}).get(revision.number)
        changes = selectors.revision_changes(previous, revision.snapshot)
        return [dict(RevisionChangeSerializer(change).data) for change in changes]


class FieldPurchaseSerializer(serializers.ModelSerializer[FieldPurchase]):
    supplier = RefSerializer(read_only=True, allow_null=True)
    buyer = serializers.SerializerMethodField()
    location = NamedRefSerializer(read_only=True, allow_null=True)
    due_date = serializers.SerializerMethodField()
    # Returnable boxes per box type ("small", "big").
    boxes = serializers.DictField(child=serializers.IntegerField(), read_only=True)
    lines = FieldPurchaseLineSerializer(many=True, read_only=True)
    payments = FieldPurchasePaymentSerializer(many=True, read_only=True)
    # Kg typed at the port x price, owed kg x price, given at the port, and what is left to pay on this purchase.
    declared_total = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    paid = serializers.SerializerMethodField()
    rest = serializers.SerializerMethodField()
    is_late = serializers.SerializerMethodField()
    receipt = NumberRefSerializer(read_only=True, allow_null=True)
    invoice = NumberRefSerializer(read_only=True, allow_null=True)
    decided_by = serializers.SerializerMethodField()
    revisions = serializers.SerializerMethodField()
    # The photo of the supplier's paper, for an <img> (office only); null when there is none (D-159).
    paper_url = serializers.SerializerMethodField()

    class Meta:
        model = FieldPurchase
        fields: tuple[str, ...] = (
            "id",
            "number",
            "status",
            "supplier",
            "proposed_supplier",
            "proposed_supplier_phone",
            "bought_on",
            "buyer",
            "terms",
            "due_days",
            "due_date",
            "supplier_reference",
            "paper_url",
            "notes",
            "office_note",
            "location",
            "boxes",
            "revision",
            "lines",
            "payments",
            "declared_total",
            "total",
            "paid",
            "rest",
            "is_late",
            "receipt",
            "invoice",
            "decided_by",
            "decided_at",
            "created_at",
            "revisions",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_buyer(self, purchase: FieldPurchase) -> str:
        return _name_of(purchase.buyer)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_paper_url(self, purchase: FieldPurchase) -> str | None:
        name = purchase.paper.name
        if not name:
            return None
        # The file name changes with each new photo, so the address does too (no stale cache).
        version = name.rsplit("/", 1)[-1].split(".", 1)[0]
        return f"{reverse('field-purchase-paper', args=[purchase.pk])}?v={version}"

    def get_decided_by(self, purchase: FieldPurchase) -> str:
        return _name_of(purchase.decided_by)

    @extend_schema_field(serializers.DateField())
    def get_due_date(self, purchase: FieldPurchase) -> str:
        return services.due_date_of(purchase.bought_on, purchase.terms, purchase.due_days).isoformat()

    @extend_schema_field(AMOUNT)
    def get_declared_total(self, purchase: FieldPurchase) -> str:
        return str(sum((line_total(line.declared_quantity, line.unit_cost) for line in purchase.lines.all()), ZERO))

    def _total(self, purchase: FieldPurchase) -> Decimal:
        return sum((line.amount for line in purchase.lines.all()), ZERO)

    def _paid(self, purchase: FieldPurchase) -> Decimal:
        return sum((payment.amount for payment in purchase.payments.all()), ZERO)

    @extend_schema_field(AMOUNT)
    def get_total(self, purchase: FieldPurchase) -> str:
        return str(self._total(purchase))

    @extend_schema_field(AMOUNT)
    def get_paid(self, purchase: FieldPurchase) -> str:
        return str(self._paid(purchase))

    @extend_schema_field(AMOUNT)
    def get_rest(self, purchase: FieldPurchase) -> str:
        """Owed minus given, never below zero (more given is an advance)."""
        return str(max(self._total(purchase) - self._paid(purchase), ZERO))

    def get_is_late(self, purchase: FieldPurchase) -> bool:
        return selectors.field_purchase_is_late(purchase)

    @extend_schema_field(FieldPurchaseRevisionSerializer(many=True))
    def get_revisions(self, purchase: FieldPurchase) -> list[dict[str, Any]]:
        revisions = list(purchase.revisions.all())
        previous = {after.number: before.snapshot for before, after in itertools.pairwise(revisions)}
        return list(FieldPurchaseRevisionSerializer(revisions, many=True, context={"previous": previous}).data)


class FieldPurchaseListSerializer(FieldPurchaseSerializer):
    """A purchase in a list: everything but its revisions."""

    class Meta(FieldPurchaseSerializer.Meta):
        fields = tuple(field for field in FieldPurchaseSerializer.Meta.fields if field != "revisions")
        read_only_fields = fields


class FieldPurchaseLineWriteSerializer(serializers.Serializer[Any]):
    # A product of the list, or the name of a new one.
    product = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    proposed_product = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    # Strings ("62.000"), checked by the service, which reports each problem on `lines.<index>.<field>`.
    declared_quantity = serializers.CharField(allow_blank=True)
    received_quantity = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    unit_cost = serializers.CharField(allow_blank=True)
    # A partner lot (D-100): the owner's choice.
    partner = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)


class FieldPurchaseCreateSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    proposed_supplier = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    proposed_supplier_phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    bought_on = serializers.DateField()
    terms = serializers.ChoiceField(choices=PaymentTerms.choices)
    due_days = serializers.IntegerField(min_value=0, max_value=365, required=False, default=0)
    supplier_reference = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    location = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    boxes = serializers.DictField(child=serializers.IntegerField(min_value=0), required=False, default=dict)
    lines = FieldPurchaseLineWriteSerializer(many=True, allow_empty=True)
    payments = FieldPurchasePaymentWriteSerializer(many=True, required=False, default=list)


class FieldPurchaseWriteSerializer(FieldPurchaseCreateSerializer):
    # The revision the person was looking at: a save on an older one is refused.
    revision = serializers.IntegerField(min_value=1)
    # The office's note to the driver; null keeps it.
    office_note = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # Validate it in the same step: stock, invoice and payments are recorded, and it no longer changes. Not named
    # `validate`, which is the serializer's own method.
    confirm = serializers.BooleanField(required=False, default=False)


class FieldPurchaseRefuseSerializer(serializers.Serializer[Any]):
    revision = serializers.IntegerField(min_value=1)
    # Why it is refused, for the driver.
    office_note = serializers.CharField(allow_blank=True)


class FieldPurchaseFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=FieldPurchaseStatus.choices, required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)


# ---- The driver's own purchases (P3-T12b, D-158) ----


class MyFieldPurchaseLineSerializer(FieldPurchaseLineSerializer):
    """A line as the driver sees it: no partner (the owner's business, D-060)."""

    class Meta(FieldPurchaseLineSerializer.Meta):
        fields = tuple(field for field in FieldPurchaseLineSerializer.Meta.fields if field != "partner")
        read_only_fields = fields


class MyFieldPurchasePaymentSerializer(FieldPurchasePaymentSerializer):
    class Meta(FieldPurchasePaymentSerializer.Meta):
        fields = ("id", "method", "amount", "reference", "cash_on")
        read_only_fields = fields


class MyFieldPurchaseSerializer(FieldPurchaseSerializer):
    """A purchase as its driver sees it: what they sent, what the office changed and decided, its note."""

    lines = MyFieldPurchaseLineSerializer(many=True, read_only=True)
    payments = MyFieldPurchasePaymentSerializer(many=True, read_only=True)
    # A photo of the supplier's paper is joined (D-159).
    has_paper = serializers.SerializerMethodField()

    class Meta(FieldPurchaseSerializer.Meta):
        fields = (
            "id",
            "number",
            "status",
            "supplier",
            "proposed_supplier",
            "proposed_supplier_phone",
            "bought_on",
            "terms",
            "due_days",
            "due_date",
            "supplier_reference",
            "has_paper",
            "notes",
            "office_note",
            "revision",
            "lines",
            "payments",
            "declared_total",
            "total",
            "paid",
            "rest",
            "decided_at",
            "created_at",
        )
        read_only_fields = fields

    def get_has_paper(self, purchase: FieldPurchase) -> bool:
        return bool(purchase.paper)


class MyFieldPurchaseLineWriteSerializer(serializers.Serializer[Any]):
    product = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    proposed_product = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    declared_quantity = serializers.CharField(allow_blank=True)
    unit_cost = serializers.CharField(allow_blank=True)


class MyFieldPurchaseUpdateSerializer(serializers.Serializer[Any]):
    # The revision the driver was looking at: a save on an older one is refused.
    revision = serializers.IntegerField(min_value=1)
    supplier = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    proposed_supplier = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    proposed_supplier_phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    terms = serializers.ChoiceField(choices=PaymentTerms.choices)
    due_days = serializers.IntegerField(min_value=0, max_value=365, required=False, default=0)
    supplier_reference = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = MyFieldPurchaseLineWriteSerializer(many=True, allow_empty=True)
    payments = FieldPurchasePaymentWriteSerializer(many=True, required=False, default=list)


class MyFieldPurchaseCreateSerializer(MyFieldPurchaseUpdateSerializer):
    revision = None  # type: ignore[assignment]
    # Sent by the phone, which may retry: the same value never makes two purchases.
    client_uuid = serializers.UUIDField(required=False, allow_null=True, default=None)
    # When the phone says it was bought (D-133); the server checks it.
    made_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class MySupplierSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    reference = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


# ---- Paying suppliers (P3-T12c, D-159) ----


class SupplierDebtSerializer(serializers.Serializer[Any]):
    supplier_id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    # Still to pay on posted invoices; of which past the due date, and due within 7 days.
    outstanding = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    overdue = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    due_soon = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Paid and not allocated yet: an advance the supplier holds.
    advances = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    open_invoices = serializers.IntegerField(read_only=True)
    next_due = serializers.DateField(read_only=True, allow_null=True)


class ChequeToCashSerializer(serializers.Serializer[Any]):
    payment_id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    supplier_id = serializers.IntegerField(read_only=True)
    supplier_name = serializers.CharField(read_only=True)
    method = serializers.ChoiceField(choices=LINE_METHOD_CHOICES, read_only=True)
    reference = serializers.CharField(read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    paid_on = serializers.DateField(read_only=True)
    cash_on = serializers.DateField(read_only=True)


class SupplierDebtsSerializer(serializers.Serializer[Any]):
    """What the company owes its suppliers for goods, and the cheques and traites to be cashed (D-159)."""

    rows = SupplierDebtSerializer(many=True, read_only=True)
    total_outstanding = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    total_overdue = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    total_due_soon = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    total_advances = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # From a week back on, the soonest first; `cheques_total` counts those still to be cashed (today or later).
    cheques = ChequeToCashSerializer(many=True, read_only=True)
    cheques_total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class FieldPurchasePaperSerializer(serializers.Serializer[Any]):
    # A photo of the supplier's paper (JPEG, PNG or WebP).
    paper = UploadedPaperField()


# ---- Paid, planned or undefined, per supplier invoice (P3-T16a, D-192) ----

SETTLEMENT_STATES = ("settled", "overdue", "planned", "undefined")
PURCHASE_TYPES = ("port", "office", "opening")


class PlanLineSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    method = serializers.ChoiceField(choices=LINE_METHOD_CHOICES, read_only=True)
    planned_on = serializers.DateField(read_only=True)
    reference = serializers.CharField(read_only=True)
    cash_on = serializers.DateField(read_only=True, allow_null=True)
    # open: planned, not paid yet; paid: settled by `payment`.
    status = serializers.ChoiceField(choices=PlanLineStatus.choices, read_only=True)
    payment_id = serializers.IntegerField(read_only=True, allow_null=True)


class PlanLineWriteSerializer(serializers.Serializer[Any]):
    # A string ("500.000"), checked by the service, which reports it on `lines.<i>.amount`.
    amount = serializers.CharField(allow_blank=True)
    method = serializers.ChoiceField(choices=LINE_METHOD_CHOICES)
    planned_on = serializers.DateField()
    reference = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    cash_on = serializers.DateField(required=False, allow_null=True, default=None)


class PlanWriteSerializer(serializers.Serializer[Any]):
    """The open plan lines of an invoice, replacing the ones there are (empty: clears the plan)."""

    lines = PlanLineWriteSerializer(many=True, allow_empty=True)


class SettlementSupplierSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class SettlementRowSerializer(serializers.Serializer[Any]):
    invoice_id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    supplier_reference = serializers.CharField(read_only=True)
    supplier = SettlementSupplierSerializer(read_only=True)
    purchase_type = serializers.ChoiceField(choices=PURCHASE_TYPES, read_only=True)
    # The achat terrain number (AT-...) for a port purchase.
    field_purchase_number = serializers.CharField(read_only=True, allow_null=True)
    invoice_date = serializers.DateField(read_only=True)
    due_date = serializers.DateField(read_only=True)
    posted_at = serializers.DateTimeField(read_only=True, allow_null=True)
    age_hours = serializers.IntegerField(read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    paid = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    planned = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    undefined = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    state = serializers.ChoiceField(choices=SETTLEMENT_STATES, read_only=True)
    plan_lines = PlanLineSerializer(many=True, read_only=True)


class SettlementCountsSerializer(serializers.Serializer[Any]):
    settled = serializers.IntegerField(read_only=True)
    overdue = serializers.IntegerField(read_only=True)
    planned = serializers.IntegerField(read_only=True)
    undefined = serializers.IntegerField(read_only=True)


class SettlementSummarySerializer(serializers.Serializer[Any]):
    """Over the invoices matching the type and supplier filters, whatever the state: total due = paid + planned
    + undefined (overdue is part of what is left, not a fourth amount)."""

    paid = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    planned = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    undefined = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    overdue = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    counts = SettlementCountsSerializer(read_only=True)


class SettlementsSerializer(serializers.Serializer[Any]):
    rows = SettlementRowSerializer(many=True, read_only=True)
    summary = SettlementSummarySerializer(read_only=True)


class SettlementFilterSerializer(serializers.Serializer[Any]):
    state = serializers.ChoiceField(choices=SETTLEMENT_STATES, required=False)
    type = serializers.ChoiceField(choices=PURCHASE_TYPES, required=False)
    supplier = serializers.IntegerField(required=False, min_value=1)
