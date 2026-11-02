from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.reverse import reverse

from apps.sales import selectors
from apps.sales.models import (
    CreditNote,
    CreditNoteKind,
    CreditNoteLine,
    CreditNoteStock,
    CreditPolicy,
    CreditStatus,
    DeliveryStatus,
    EInvoiceStatus,
    FinanceSettings,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    InvoiceVatLine,
    PriceSource,
    Quote,
    QuoteLine,
    QuoteStatus,
    Sale,
    SaleLine,
    SaleLineBatch,
    SalePaymentMethod,
    SaleRevision,
    SaleRevisionKind,
    SaleStatus,
    WithholdingCertificate,
)

# ---- Quotes (P2-T03) ----


def person_name(user: Any) -> str:
    if user is None:
        return ""
    return f"{user.first_name} {user.last_name}".strip() or user.username


class SaleRefSerializer(serializers.Serializer[Any]):
    """A sale named from another document (the quote it came from, a lot's sales)."""

    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    status = serializers.ChoiceField(choices=SaleStatus.choices, read_only=True)


class QuoteCustomerSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    reference = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    address = serializers.CharField(read_only=True)
    city = serializers.CharField(read_only=True)
    tax_id = serializers.CharField(read_only=True)
    # Printed in the client block of every document's header (D-131).
    phone = serializers.CharField(read_only=True)
    # The "Client de passage": pays every sale on the spot (D-047).
    is_walk_in = serializers.BooleanField(read_only=True)


class QuoteLocationSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class QuoteProductSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    reference = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class QuoteLineSerializer(serializers.ModelSerializer[QuoteLine]):
    product = QuoteProductSerializer(read_only=True)
    # Kg already on a BL of this quote (drafts included, cancelled ones not) and kg left to deliver (D-115).
    delivered_quantity = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()

    class Meta:
        model = QuoteLine
        fields: tuple[str, ...] = (
            "id",
            "product",
            "quantity",
            "unit_price",
            "discount_rate",
            "gross_amount",
            "discount_amount",
            "amount",
            "requested_batch",
            "delivered_quantity",
            "remaining_quantity",
        )
        read_only_fields: tuple[str, ...] = fields

    def _delivery(self, line: QuoteLine) -> selectors.LineDelivery:
        delivery: dict[int, selectors.LineDelivery] = self.context["delivery"]
        return delivery[line.pk]

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=3))
    def get_delivered_quantity(self, line: QuoteLine) -> str:
        return str(self._delivery(line).delivered)

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=3))
    def get_remaining_quantity(self, line: QuoteLine) -> str:
        return str(self._delivery(line).remaining)


class QuoteSerializer(serializers.ModelSerializer[Quote]):
    # The status shown today: a sent quote past its validity date is already "expired".
    status = serializers.ChoiceField(choices=QuoteStatus.choices, source="current_status", read_only=True)
    customer = QuoteCustomerSerializer(read_only=True)
    location = QuoteLocationSerializer(read_only=True, allow_null=True)
    line_count = serializers.IntegerField(read_only=True)
    created_by = serializers.SerializerMethodField()
    sent_by = serializers.SerializerMethodField()
    answered_by = serializers.SerializerMethodField()
    # The last sale (BL) made from this accepted quote, cancelled ones left out; `sales` has them all, oldest
    # first, since a quote may be delivered in several BL (D-115).
    sale = serializers.SerializerMethodField()
    sales = serializers.SerializerMethodField()
    # Kg not on any BL yet; 0.000 once the quote is delivered in full.
    remaining_quantity = serializers.SerializerMethodField()

    class Meta:
        model = Quote
        fields: tuple[str, ...] = (
            "id",
            "number",
            "status",
            "customer",
            "location",
            "quoted_on",
            "valid_until",
            "notes",
            "line_count",
            "subtotal",
            "discount_total",
            "total_excl_tax",
            "tax_amount",
            "total",
            "created_by",
            "created_at",
            "sent_by",
            "sent_at",
            "answered_by",
            "answered_at",
            "refusal_reason",
            "expired_at",
            "sale",
            "sales",
            "remaining_quantity",
        )
        read_only_fields: tuple[str, ...] = fields

    @extend_schema_field(SaleRefSerializer(allow_null=True))
    def get_sale(self, quote: Quote) -> dict[str, Any] | None:
        sale = selectors.live_sale_of(quote)
        return SaleRefSerializer(sale).data if sale is not None else None

    @extend_schema_field(SaleRefSerializer(many=True))
    def get_sales(self, quote: Quote) -> Any:
        return SaleRefSerializer(selectors.live_sales_of(quote), many=True).data

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=3))
    def get_remaining_quantity(self, quote: Quote) -> str:
        return str(selectors.quote_remaining(quote))

    def get_created_by(self, quote: Quote) -> str:
        return person_name(quote.created_by)

    def get_sent_by(self, quote: Quote) -> str:
        return person_name(quote.sent_by)

    def get_answered_by(self, quote: Quote) -> str:
        return person_name(quote.answered_by)


class QuoteDetailSerializer(QuoteSerializer):
    lines = serializers.SerializerMethodField()

    class Meta(QuoteSerializer.Meta):
        fields = (*QuoteSerializer.Meta.fields, "lines")
        read_only_fields = fields

    @extend_schema_field(QuoteLineSerializer(many=True))
    def get_lines(self, quote: Quote) -> Any:
        context = {**self.context, "delivery": selectors.quote_delivery(quote)}
        return QuoteLineSerializer(quote.lines.all(), many=True, context=context).data


class QuoteLineWriteSerializer(serializers.Serializer[Any]):
    product = serializers.IntegerField(min_value=1)
    # Weights, prices and rates travel as strings ("12.500") and are checked by the service, which reports
    # each problem on `lines.<index>.<field>`.
    quantity = serializers.CharField(allow_blank=True)
    # DT per kg. Empty takes the sale price in force on the quote's day.
    unit_price = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # Percent, 2 decimals at most ("5", "2.50"). Empty means none.
    discount_rate = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # A lot picked by hand instead of FIFO (D-121, D-201). Empty: the oldest lot first, as always.
    batch = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1)


class SaleLinePickSerializer(serializers.Serializer[Any]):
    # A lot of the line's product at the place the goods leave from (`location_batches`).
    batch = serializers.IntegerField(min_value=1)
    # Kilos to take from this lot first; text, checked by the service like the line's weight.
    quantity = serializers.CharField(allow_blank=True)


class SaleLineWriteSerializer(QuoteLineWriteSerializer):
    """A sale line as typed: the same fields as a quote line, the lot included."""

    # Several lots picked by hand, each with the kilos to take from it first (D-208). They take precedence over
    # `batch`; empty takes the lot in `batch`, or the oldest lot first.
    picks = SaleLinePickSerializer(many=True, required=False, default=list)


class QuoteWriteSerializer(serializers.Serializer[Any]):
    customer = serializers.IntegerField(min_value=1)
    # Where the goods would leave from; information only (its stock is shown while typing).
    location = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    quoted_on = serializers.DateField()
    # Empty: the quote's day + 3 days.
    valid_until = serializers.DateField(required=False, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = QuoteLineWriteSerializer(many=True, allow_empty=True)
    # Mark it sent at once; otherwise it stays a draft.
    send_now = serializers.BooleanField(required=False, default=False)
    # Owner or manager only: why a price after the discount may go under a product's minimum (D-193). Others'
    # lines under the minimum are refused.
    below_minimum_reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class QuoteRefuseSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class QuoteFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=QuoteStatus.choices, required=False)
    customer = serializers.IntegerField(required=False, min_value=1)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)


# ---- Sales (P2-T04) ----


class QuoteRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)


class SaleCustomerSerializer(QuoteCustomerSerializer):
    pass


class SaleLocationSerializer(QuoteLocationSerializer):
    kind = serializers.CharField(read_only=True)


class SaleBatchSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)


class SaleLineBatchSerializer(serializers.ModelSerializer[SaleLineBatch]):
    """The kilos of a line taken from one lot, with their cost (office only)."""

    batch = SaleBatchSerializer(read_only=True)

    class Meta:
        model = SaleLineBatch
        fields: tuple[str, ...] = ("id", "batch", "quantity", "unit_cost", "cost_amount", "revenue_amount")
        read_only_fields: tuple[str, ...] = fields


# Costs and margins are office data: a driver sees prices and amounts, never what the goods cost (D-045).
COST_FIELDS = ("cost_total", "cost_amount", "margin", "batches")


def _without_costs(data: dict[str, Any]) -> dict[str, Any]:
    return {key: (None if key in COST_FIELDS else value) for key, value in data.items()}


class SaleLineSerializer(serializers.ModelSerializer[SaleLine]):
    product = QuoteProductSerializer(read_only=True)
    price_source = serializers.ChoiceField(choices=PriceSource.choices, read_only=True)
    # Null for drivers.
    batches = SaleLineBatchSerializer(many=True, read_only=True, allow_null=True)

    class Meta:
        model = SaleLine
        fields: tuple[str, ...] = (
            "id",
            "product",
            "quantity",
            "unit_price",
            "price_source",
            "below_minimum",
            "discount_rate",
            "gross_amount",
            "discount_amount",
            "amount",
            # VAT of the line (D-224): its rate when sold with VAT (empty otherwise), its amounts without and with it.
            "vat_rate",
            "amount_excl_tax",
            "vat_amount",
            "amount_incl_tax",
            "cost_amount",
            "requested_batch",
            "batches",
            # On the BL of a truck load: the kg written on the printed BL; `quantity` is what was delivered (D-178).
            "ordered_quantity",
        )
        read_only_fields: tuple[str, ...] = fields

    def to_representation(self, instance: SaleLine) -> dict[str, Any]:
        data = super().to_representation(instance)
        return data if self.context.get("show_costs", True) else _without_costs(data)


class SaleInvoiceRefSerializer(serializers.Serializer[Any]):
    """An invoice named from another document (its sale). `number` is empty while a draft."""

    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    status = serializers.ChoiceField(choices=InvoiceStatus.choices, read_only=True)


class SaleSerializer(serializers.ModelSerializer[Sale]):
    status = serializers.ChoiceField(choices=SaleStatus.choices, read_only=True)
    payment_method = serializers.ChoiceField(choices=SalePaymentMethod.choices, read_only=True, allow_blank=True)
    customer = SaleCustomerSerializer(read_only=True)
    location = SaleLocationSerializer(read_only=True)
    quote = QuoteRefSerializer(read_only=True, allow_null=True)
    line_count = serializers.IntegerField(read_only=True)
    # The truck load this BL was prepared with (D-160), if any.
    transfer = QuoteRefSerializer(read_only=True, allow_null=True)
    # The total without VAT (a property of the sale: total with VAT less the VAT, D-224).
    amount_excl_tax = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # total without VAT − cost of goods, once confirmed; null for drivers.
    margin = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    confirmed_by = serializers.SerializerMethodField()
    cancelled_by = serializers.SerializerMethodField()
    # Its invoice, draft or issued, unless cancelled by a credit note (P2-T05).
    invoice = serializers.SerializerMethodField()
    # Against the customer's credit limit (P2-T06): empty, pending (a draft waiting for the owner or a
    # manager), approved or warned.
    credit_status = serializers.ChoiceField(choices=CreditStatus.choices, read_only=True, allow_blank=True)
    credit_decided_by = serializers.SerializerMethodField()
    # The BL of a truck load (D-178): to deliver, delivered, delivered in part, or not delivered. Empty otherwise.
    delivery_status = serializers.ChoiceField(choices=DeliveryStatus.choices, read_only=True, allow_blank=True)
    delivered_by = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields: tuple[str, ...] = (
            "id",
            "number",
            "status",
            "customer",
            "location",
            "sold_at",
            "quote",
            "transfer",
            "delivery_address",
            "notes",
            "line_count",
            "subtotal",
            "discount_total",
            "total_excl_tax",
            "tax_amount",
            "total",
            # The VAT of the BL (D-224): without VAT, the VAT of its lines, and the total with VAT.
            "amount_excl_tax",
            "vat_total",
            "total_incl_tax",
            "cost_total",
            "margin",
            "amount_paid",
            "payment_method",
            "payment_reference",
            "amount_due",
            "created_by",
            "created_at",
            "confirmed_by",
            "confirmed_at",
            "cancelled_by",
            "cancelled_at",
            "cancel_reason",
            "invoice",
            "credit_status",
            "credit_over_by",
            "credit_decided_by",
            "credit_decided_at",
            "delivery_status",
            "issued_at",
            "version",
            "delivered_at",
            "delivered_by",
            "delivery_note",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_delivered_by(self, sale: Sale) -> str:
        return person_name(sale.delivered_by)

    def get_credit_decided_by(self, sale: Sale) -> str:
        return person_name(sale.credit_decided_by)

    @extend_schema_field(SaleInvoiceRefSerializer(allow_null=True))
    def get_invoice(self, sale: Sale) -> dict[str, Any] | None:
        invoice = selectors.live_invoice_of(sale)
        return SaleInvoiceRefSerializer(invoice).data if invoice is not None else None

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=3, allow_null=True))
    def get_margin(self, sale: Sale) -> str | None:
        # A string like every amount of the API ("110.000"), never a JSON number.
        if sale.cost_total is None:
            return None
        return str(sale.total_excl_tax - sale.cost_total)

    def get_created_by(self, sale: Sale) -> str:
        return person_name(sale.created_by)

    def get_confirmed_by(self, sale: Sale) -> str:
        return person_name(sale.confirmed_by)

    def get_cancelled_by(self, sale: Sale) -> str:
        return person_name(sale.cancelled_by)

    def to_representation(self, instance: Sale) -> dict[str, Any]:
        data = super().to_representation(instance)
        return data if self.context.get("show_costs", True) else _without_costs(data)


class SaleRevisionLineSerializer(serializers.Serializer[Any]):
    product = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    # The kg written on the BL of this version, and, for the delivery, the kg delivered (null before).
    ordered = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    delivered = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True, allow_null=True)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class SaleRevisionSerializer(serializers.ModelSerializer[SaleRevision]):
    """One version of the BL of a truck load, as it was then (D-178)."""

    kind = serializers.ChoiceField(choices=SaleRevisionKind.choices, read_only=True)
    lines = SaleRevisionLineSerializer(many=True, read_only=True)
    boxes = serializers.DictField(child=serializers.IntegerField(), read_only=True)
    actor = serializers.SerializerMethodField()

    class Meta:
        model = SaleRevision
        fields = ("id", "version", "kind", "lines", "boxes", "total", "note", "actor", "created_at")
        read_only_fields = fields

    def get_actor(self, revision: SaleRevision) -> str:
        return person_name(revision.actor)


class SaleDetailSerializer(SaleSerializer):
    lines = SaleLineSerializer(many=True, read_only=True)
    # The returnable boxes left with the client, per box type ("small", "big").
    boxes = serializers.SerializerMethodField()
    # Every version of the BL of a truck load, oldest first (D-178); empty for any other sale.
    revisions = SaleRevisionSerializer(many=True, read_only=True)

    class Meta(SaleSerializer.Meta):
        fields = (*SaleSerializer.Meta.fields, "lines", "boxes", "revisions")
        read_only_fields = fields

    @extend_schema_field(serializers.DictField(child=serializers.IntegerField()))
    def get_boxes(self, sale: Sale) -> dict[str, int]:
        return {line.box_type: line.count for line in sale.box_lines.all()}


class SalePaymentWriteSerializer(serializers.Serializer[Any]):
    # Paid on the spot, in DT as a string ("100.000"); empty means nothing.
    amount_paid = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # The whole total is paid on the spot (a counter sale): `amount_paid` is ignored.
    paid_in_full = serializers.BooleanField(required=False, default=False)
    payment_method = serializers.ChoiceField(
        choices=SalePaymentMethod.choices, required=False, allow_blank=True, default=""
    )
    payment_reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=50)


class SaleWriteSerializer(SalePaymentWriteSerializer):
    # Empty: the walk-in customer ("Client de passage"), for counter sales.
    customer = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    # The cold room (open to counter sales) or the truck the goods leave from.
    location = serializers.IntegerField(min_value=1)
    # Empty: now. A driver's phone sends when the sale was made; the server checks it before using it (D-133).
    sold_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = SaleLineWriteSerializer(many=True, allow_empty=True)
    # Confirm at once (the stock leaves); otherwise it stays a draft.
    confirm_now = serializers.BooleanField(required=False, default=False)
    # Owner or manager only: why a price after the discount may go under a product's minimum (D-193).
    below_minimum_reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    # Accept going above the customer's credit limit (owner or manager only, when the company asks for
    # approval).
    approve_credit = serializers.BooleanField(required=False, default=False)
    # Sent by an app that may retry: the same value never makes two sales.
    client_uuid = serializers.UUIDField(required=False, allow_null=True, default=None)
    # Returnable boxes left with the client, per box type ("small", "big"): a count, never kg. Zero means none;
    # they move when the sale is confirmed (D-122). Left out: none on a new sale, unchanged on a draft.
    boxes = serializers.DictField(
        child=serializers.IntegerField(min_value=0), required=False, allow_null=True, default=None
    )
    # Where this delivery goes when it is not the customer's address, for this BL only (D-160). Left out: unchanged.
    delivery_address = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None, max_length=255
    )


class QuoteDeliveryLineSerializer(serializers.Serializer[Any]):
    quote_line = serializers.IntegerField(min_value=1)
    quantity = serializers.CharField(max_length=20)


class QuoteConvertSerializer(SalePaymentWriteSerializer):
    # Empty: the quote's own place.
    location = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    sold_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    confirm_now = serializers.BooleanField(required=False, default=False)
    # The kg this BL takes on each quote line, at most what is left on it (D-115). Left out: everything left.
    lines = QuoteDeliveryLineSerializer(many=True, required=False, allow_null=True, default=None)


class DeliveredLineSerializer(serializers.Serializer[Any]):
    line = serializers.IntegerField(min_value=1)
    # The kg delivered, as a string ("9.800"): zero takes the product off the BL.
    quantity = serializers.CharField(max_length=20)


class DeliverSerializer(SalePaymentWriteSerializer):
    """The delivery of the BL of a truck load, from the driver's phone (D-178)."""

    # Only the lines that changed; a line left out is delivered as written.
    lines = DeliveredLineSerializer(many=True, required=False, default=list)
    # The boxes left with the client, per box type. Left out: as written on the BL.
    boxes = serializers.DictField(
        child=serializers.IntegerField(min_value=0), required=False, allow_null=True, default=None
    )
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    # Sent by the phone, which may send again: the same value records one delivery.
    client_uuid = serializers.UUIDField(required=False, allow_null=True, default=None)


class NotDeliveredSerializer(serializers.Serializer[Any]):
    # Why, if the driver says (optional).
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    client_uuid = serializers.UUIDField(required=False, allow_null=True, default=None)


class SaleConfirmSerializer(serializers.Serializer[Any]):
    # Accept going above the customer's credit limit (owner or manager only, when the company asks for
    # approval).
    approve_credit = serializers.BooleanField(required=False, default=False)


class SaleCancelSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class SaleFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=SaleStatus.choices, required=False)
    # The BL of the truck loads by where their delivery stands (D-178).
    delivery_status = serializers.ChoiceField(choices=DeliveryStatus.choices, required=False)
    customer = serializers.IntegerField(required=False, min_value=1)
    location = serializers.IntegerField(required=False, min_value=1)
    # True: only the BL still to invoice (confirmed, named customer, on no live invoice).
    uninvoiced = serializers.BooleanField(required=False, default=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)


class BatchSaleRowSerializer(serializers.Serializer[Any]):
    """The kilos of one lot sold by one sale line."""

    id = serializers.IntegerField(read_only=True)
    sale = SaleRefSerializer(source="line.sale", read_only=True)
    sold_at = serializers.DateTimeField(source="line.sale.sold_at", read_only=True)
    customer = serializers.CharField(source="line.sale.customer.name", read_only=True)
    location = serializers.CharField(source="line.sale.location.name", read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    # The line's price per kg and discount.
    unit_price = serializers.DecimalField(source="line.unit_price", max_digits=14, decimal_places=3, read_only=True)
    discount_rate = serializers.DecimalField(
        source="line.discount_rate", max_digits=5, decimal_places=2, read_only=True
    )
    revenue_amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    cost_amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # What credit notes took back of this row (customer returns, D-070).
    returned_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    credited_revenue = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    returned_cost = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class BatchSalesSerializer(serializers.Serializer[Any]):
    """What one lot sold over its confirmed sales, net of credit notes: the sales side of its result (D-040)."""

    batch_id = serializers.IntegerField(read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    revenue = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    cost = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    margin = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    rows = BatchSaleRowSerializer(many=True, read_only=True)


# ---- Finance settings (P2-T05, D-056) ----


class FinanceSettingsSerializer(serializers.ModelSerializer[FinanceSettings]):
    """One version of the finance settings."""

    credit_policy = serializers.ChoiceField(choices=CreditPolicy.choices, read_only=True)
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = FinanceSettings
        fields: tuple[str, ...] = (
            "id",
            "valid_from",
            "vat_rate",
            "fiscal_stamp",
            "prices_include_vat",
            "withholding_rate",
            "credit_policy",
            "legal_name",
            "address",
            "phone",
            "tax_id",
            "trade_register",
            "created_by",
            "created_at",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_created_by(self, version: FinanceSettings) -> str:
        return person_name(version.created_by)


class FinanceSettingsOverviewSerializer(serializers.Serializer[Any]):
    """The version in force today, every version (planned ones first), and whether the user may change them."""

    in_force = FinanceSettingsSerializer(read_only=True)
    history = FinanceSettingsSerializer(many=True, read_only=True)
    may_edit = serializers.BooleanField(read_only=True)


class FinanceSettingsWriteSerializer(serializers.Serializer[Any]):
    # Empty: today. A later day plans the version; the past is refused.
    valid_from = serializers.DateField(required=False, allow_null=True, default=None)
    # Rates in percent and the stamp in DT travel as strings ("19", "1.000"), checked by the service.
    vat_rate = serializers.CharField(allow_blank=True)
    fiscal_stamp = serializers.CharField(allow_blank=True)
    prices_include_vat = serializers.BooleanField()
    withholding_rate = serializers.CharField(allow_blank=True)
    # What happens above a customer's credit limit: block, ask the owner or a manager, or warn and log.
    # Empty keeps the version in force.
    credit_policy = serializers.ChoiceField(choices=CreditPolicy.choices, required=False)
    legal_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    address = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    phone = serializers.CharField(required=False, allow_blank=True, default="", max_length=50)
    tax_id = serializers.CharField(required=False, allow_blank=True, default="", max_length=30)
    trade_register = serializers.CharField(required=False, allow_blank=True, default="", max_length=50)


# ---- Invoices and credit notes (P2-T05, D-057) ----


class PartySerializer(serializers.Serializer[Any]):
    """A seller or a customer as an invoice prints them."""

    name = serializers.CharField(read_only=True)
    address = serializers.CharField(read_only=True)
    city = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    tax_id = serializers.CharField(read_only=True)
    trade_register = serializers.CharField(read_only=True)


class InvoiceLineSerializer(serializers.ModelSerializer[InvoiceLine]):
    product = QuoteProductSerializer(read_only=True)
    # The BL the line comes from.
    sale_number = serializers.CharField(source="sale_line.sale.number", read_only=True)
    # The rate the line takes when none is typed: the product's own, else the settings'.
    default_vat_rate = serializers.SerializerMethodField()
    # What credit notes already gave back on this line.
    credited_quantity = serializers.SerializerMethodField()
    credited_amount_excl_tax = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceLine
        fields: tuple[str, ...] = (
            "id",
            "product",
            "product_reference",
            "product_name",
            "sale_number",
            "lots",
            "quantity",
            "unit_price",
            "discount_rate",
            "gross_amount",
            "discount_amount",
            "amount",
            "vat_rate",
            "vat_rate_overridden",
            "default_vat_rate",
            "unit_price_excl_tax",
            "amount_excl_tax",
            "vat_amount",
            "amount_incl_tax",
            "credited_quantity",
            "credited_amount_excl_tax",
        )
        read_only_fields: tuple[str, ...] = fields

    @extend_schema_field(serializers.DecimalField(max_digits=5, decimal_places=2))
    def get_default_vat_rate(self, line: InvoiceLine) -> str:
        own = line.product.vat_rate
        if own is not None:
            return str(own)
        version = line.invoice.settings_version
        return str(version.vat_rate) if version is not None else str(line.vat_rate)

    def _credited(self, line: InvoiceLine) -> selectors.CreditedLine | None:
        credited: dict[int, selectors.CreditedLine] = self.context.get("credited", {})
        return credited.get(line.pk)

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=3))
    def get_credited_quantity(self, line: InvoiceLine) -> str:
        done = self._credited(line)
        return str(done.quantity if done else "0.000")

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=3))
    def get_credited_amount_excl_tax(self, line: InvoiceLine) -> str:
        done = self._credited(line)
        return str(done.amount_excl_tax if done else "0.000")


class InvoiceVatLineSerializer(serializers.ModelSerializer[InvoiceVatLine]):
    class Meta:
        model = InvoiceVatLine
        fields: tuple[str, ...] = ("rate", "base", "computed_amount", "amount", "amount_overridden")
        read_only_fields: tuple[str, ...] = fields


class CreditNoteLineSerializer(serializers.ModelSerializer[CreditNoteLine]):
    product_reference = serializers.CharField(source="invoice_line.product_reference", read_only=True)
    product_name = serializers.CharField(source="invoice_line.product_name", read_only=True)

    class Meta:
        model = CreditNoteLine
        fields: tuple[str, ...] = (
            "id",
            "invoice_line",
            "product_reference",
            "product_name",
            "quantity",
            "vat_rate",
            "amount_excl_tax",
            "vat_amount",
            "amount_incl_tax",
        )
        read_only_fields: tuple[str, ...] = fields


class CreditNoteInvoiceSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    customer_name = serializers.CharField(read_only=True)
    issued_on = serializers.DateField(read_only=True)


class CreditNoteSerializer(serializers.ModelSerializer[CreditNote]):
    kind = serializers.ChoiceField(choices=CreditNoteKind.choices, read_only=True)
    stock = serializers.ChoiceField(choices=CreditNoteStock.choices, read_only=True)
    einvoice_status = serializers.ChoiceField(choices=EInvoiceStatus.choices, read_only=True)
    invoice = CreditNoteInvoiceSerializer(read_only=True)
    lines = CreditNoteLineSerializer(many=True, read_only=True)
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = CreditNote
        fields: tuple[str, ...] = (
            "id",
            "number",
            "kind",
            "invoice",
            "issued_on",
            "reason",
            "stock",
            "total_excl_tax",
            "vat_total",
            "fiscal_stamp",
            "fees",
            "total_incl_tax",
            "withholding_amount",
            "net_amount",
            "lines",
            "created_by",
            "created_at",
            "einvoice_status",
            "einvoice_reference",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_created_by(self, note: CreditNote) -> str:
        return person_name(note.created_by)


class InvoiceSerializer(serializers.ModelSerializer[Invoice]):
    status = serializers.ChoiceField(choices=InvoiceStatus.choices, read_only=True)
    einvoice_status = serializers.ChoiceField(choices=EInvoiceStatus.choices, read_only=True)
    # The delivery notes (BL) it bills, oldest first; `sale` is the first one.
    sales = SaleRefSerializer(many=True, read_only=True)
    sale = serializers.SerializerMethodField()
    customer = QuoteCustomerSerializer(read_only=True)
    line_count = serializers.IntegerField(read_only=True)
    # What its credit notes gave back (net), and what remains to collect.
    credited_total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    remaining_to_pay = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    issued_by = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields: tuple[str, ...] = (
            "id",
            "number",
            "status",
            "sale",
            "sales",
            "customer",
            "issued_on",
            "due_on",
            "line_count",
            "apply_vat",
            "prices_include_vat",
            "subtotal",
            "discount_total",
            "total_excl_tax",
            "vat_total",
            "fiscal_stamp",
            "fees",
            "total_incl_tax",
            "withholding_applied",
            "withholding_rate",
            "withholding_amount",
            "net_to_pay",
            "credited_total",
            "remaining_to_pay",
            "created_by",
            "created_at",
            "issued_by",
            "issued_at",
            "cancelled_at",
            "einvoice_status",
            "einvoice_reference",
        )
        read_only_fields: tuple[str, ...] = fields

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=3))
    def get_remaining_to_pay(self, invoice: Invoice) -> str:
        # An issued invoice: what its sale still owes (payments, credit notes, certificate taken off, D-062).
        if invoice.status == InvoiceStatus.ISSUED:
            return str(sum((sale.amount_due for sale in invoice.sales.all()), Decimal("0.000")))
        if invoice.status == InvoiceStatus.CANCELLED:
            return "0.000"
        return str(invoice.net_to_pay)

    @extend_schema_field(SaleRefSerializer)
    def get_sale(self, invoice: Invoice) -> dict[str, Any]:
        first = invoice.sales.all()[0]
        return {"id": first.pk, "number": first.number, "status": first.status}

    def get_created_by(self, invoice: Invoice) -> str:
        return person_name(invoice.created_by)

    def get_issued_by(self, invoice: Invoice) -> str:
        return person_name(invoice.issued_by)


class InvoiceCertificateSerializer(serializers.ModelSerializer[WithholdingCertificate]):
    """The withholding certificate of an invoice (P2-T06, D-063)."""

    file_url = serializers.SerializerMethodField()
    # "application/pdf" or "image/webp"; empty without a file.
    file_type = serializers.SerializerMethodField()
    is_voided = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = WithholdingCertificate
        fields: tuple[str, ...] = (
            "id",
            "number",
            "issued_on",
            "amount",
            "file_url",
            "file_type",
            "is_voided",
            "voided_at",
            "void_reason",
            "created_by",
            "created_at",
        )
        read_only_fields: tuple[str, ...] = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_file_url(self, certificate: WithholdingCertificate) -> str | None:
        if not certificate.file.name:
            return None
        return reverse("withholding-certificate-file", args=[certificate.pk])

    def get_file_type(self, certificate: WithholdingCertificate) -> str:
        if not certificate.file.name:
            return ""
        return "application/pdf" if certificate.file.name.endswith(".pdf") else "image/webp"

    def get_is_voided(self, certificate: WithholdingCertificate) -> bool:
        return certificate.voided_at is not None

    def get_created_by(self, certificate: WithholdingCertificate) -> str:
        return person_name(certificate.created_by)


class InvoiceDetailSerializer(InvoiceSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    vat_lines = InvoiceVatLineSerializer(many=True, read_only=True)
    credit_notes = CreditNoteSerializer(many=True, read_only=True)
    # As printed: copied when issued; a draft shows today's settings and customer.
    seller = serializers.SerializerMethodField()
    bill_to = serializers.SerializerMethodField()
    # What the settings propose, to show beside the typed values of a draft.
    settings_valid_from = serializers.DateField(source="settings_version.valid_from", read_only=True, allow_null=True)
    settings_vat_rate = serializers.DecimalField(
        source="settings_version.vat_rate", max_digits=5, decimal_places=2, read_only=True, allow_null=True
    )
    settings_fiscal_stamp = serializers.DecimalField(
        source="settings_version.fiscal_stamp", max_digits=14, decimal_places=3, read_only=True, allow_null=True
    )
    settings_withholding_rate = serializers.DecimalField(
        source="settings_version.withholding_rate", max_digits=5, decimal_places=2, read_only=True, allow_null=True
    )

    # The live withholding certificate (P2-T06), if one was recorded.
    certificate = serializers.SerializerMethodField()

    @extend_schema_field(InvoiceCertificateSerializer(allow_null=True))
    def get_certificate(self, invoice: Invoice) -> dict[str, Any] | None:
        live = next((row for row in invoice.certificates.all() if row.voided_at is None), None)
        return dict(InvoiceCertificateSerializer(live).data) if live is not None else None

    class Meta(InvoiceSerializer.Meta):
        fields = (
            *InvoiceSerializer.Meta.fields,
            "certificate",
            "notes",
            "fiscal_stamp_overridden",
            "withholding_rate_overridden",
            "seller",
            "bill_to",
            "settings_valid_from",
            "settings_vat_rate",
            "settings_fiscal_stamp",
            "settings_withholding_rate",
            "lines",
            "vat_lines",
            "credit_notes",
        )
        read_only_fields = fields

    @extend_schema_field(PartySerializer)
    def get_seller(self, invoice: Invoice) -> dict[str, Any]:
        if invoice.status != InvoiceStatus.DRAFT or invoice.settings_version is None:
            values = {
                "name": invoice.seller_name,
                "address": invoice.seller_address,
                "phone": invoice.seller_phone,
                "tax_id": invoice.seller_tax_id,
                "trade_register": invoice.seller_trade_register,
            }
        else:
            version = invoice.settings_version
            values = {
                "name": version.legal_name or invoice.organization.name,
                "address": version.address,
                "phone": version.phone,
                "tax_id": version.tax_id,
                "trade_register": version.trade_register,
            }
        return {**values, "city": ""}

    @extend_schema_field(PartySerializer)
    def get_bill_to(self, invoice: Invoice) -> dict[str, Any]:
        if invoice.status == InvoiceStatus.DRAFT:
            customer = invoice.customer
            values = {
                "name": customer.name,
                "address": customer.address,
                "city": customer.city,
                "tax_id": customer.tax_id,
            }
        else:
            values = {
                "name": invoice.customer_name,
                "address": invoice.customer_address,
                "city": invoice.customer_city,
                "tax_id": invoice.customer_tax_id,
            }
        return {**values, "phone": "", "trade_register": ""}


class InvoiceLineChoiceSerializer(serializers.Serializer[Any]):
    # Percent ("7", "19.00", "0" = exempt). Empty: the product's or the settings' rate.
    vat_rate = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class InvoiceVatAmountSerializer(serializers.Serializer[Any]):
    # The rate whose VAT amount is typed ("19.00").
    rate = serializers.CharField()
    # DT. Empty: the computed amount.
    amount = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class InvoiceChoicesSerializer(serializers.Serializer[Any]):
    """What may change on a draft invoice. Every empty value takes the finance settings (D-056)."""

    # False: an invoice without VAT; empty: with VAT only when a BL holds goods bought with VAT (D-246).
    apply_vat = serializers.BooleanField(required=False, allow_null=True, default=None)
    # One per line, in the order of the lines; empty list: every line takes its proposed rate.
    lines = InvoiceLineChoiceSerializer(many=True, required=False, default=list)
    # Typed VAT amounts per rate; errors come back on `vat_amounts.<rate>`.
    vat_amounts = InvoiceVatAmountSerializer(many=True, required=False, default=list)
    fiscal_stamp = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # "Frais" in DT, outside VAT; empty: none (D-126).
    fees = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # The withholding is not typed: the server takes it on invoices of 1 000 DT and more (the output says so).
    withholding_rate = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    # Issue it in the same request (numbered and frozen).
    issue_now = serializers.BooleanField(required=False, default=False)


class InvoiceCreateSerializer(InvoiceChoicesSerializer):
    # The confirmed sale (BL) to invoice, or several BLs of one customer for a grouped invoice (D-096).
    sale = serializers.IntegerField(min_value=1, required=False)
    sales = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=False)


class InvoiceFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=InvoiceStatus.choices, required=False)
    customer = serializers.IntegerField(required=False, min_value=1)
    sale = serializers.IntegerField(required=False, min_value=1)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)


class CreditNoteLineWriteSerializer(serializers.Serializer[Any]):
    invoice_line = serializers.IntegerField(min_value=1)
    # Kilos given back; empty or 0 for a price correction.
    quantity = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # DT without VAT; empty: the kilos' share of the line.
    amount = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class CreditNoteWriteSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=CreditNoteKind.choices)
    reason = serializers.CharField(allow_blank=True, max_length=255)
    # What happens to the kilos given back: nothing, back in stock, or written off (customer returns, D-070).
    stock = serializers.ChoiceField(choices=CreditNoteStock.choices, required=False, default=CreditNoteStock.NONE)
    # Partial notes only; a full note gives back everything left.
    lines = CreditNoteLineWriteSerializer(many=True, required=False, default=list)


class CreditNoteFilterSerializer(serializers.Serializer[Any]):
    customer = serializers.IntegerField(required=False, min_value=1)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)
