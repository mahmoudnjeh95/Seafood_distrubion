"""Customer payments (règlements with several lines, D-197), balances, ageing and withholding certificates
(P2-T06, D-062, D-063)."""

from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.sales.models import CustomerPayment, CustomerPaymentLine, CustomerPaymentMethod
from apps.treasury import selectors as treasury

from .serializers import InvoiceCertificateSerializer, QuoteCustomerSerializer, SaleRefSerializer, person_name


@extend_schema_field(OpenApiTypes.BINARY)
class UploadedFileField(serializers.FileField):
    """A file sent in a multipart form: a Blob in the generated client, not a URL."""


class CustomerPaymentAllocationSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    sale = SaleRefSerializer(read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class InstrumentRefSerializer(serializers.Serializer[Any]):
    """The cheque or traite of a payment line, as the treasury follows it (D-197)."""

    id = serializers.IntegerField(read_only=True)
    kind = serializers.ChoiceField(choices=treasury.INSTRUMENT_KIND_CHOICES, read_only=True)
    number = serializers.CharField(read_only=True)
    bank_code = serializers.CharField(source="bank.code", read_only=True, default="")
    bank_name = serializers.CharField(source="bank.name", read_only=True, default="")
    drawer = serializers.CharField(read_only=True)
    due_on = serializers.DateField(read_only=True)
    status = serializers.ChoiceField(choices=treasury.INSTRUMENT_STATUS_CHOICES, read_only=True)


class CustomerPaymentLineSerializer(serializers.ModelSerializer[CustomerPaymentLine]):
    method = serializers.ChoiceField(choices=CustomerPaymentMethod.choices, read_only=True)
    # The cheque or traite of the line, with its state in the treasury; null for cash, transfer, card.
    instrument = InstrumentRefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = CustomerPaymentLine
        fields: tuple[str, ...] = ("id", "method", "amount", "reference", "instrument")
        read_only_fields: tuple[str, ...] = fields


class CustomerPaymentSerializer(serializers.ModelSerializer[CustomerPayment]):
    customer = QuoteCustomerSerializer(read_only=True)
    # `mixed` when the lines use several methods.
    method = serializers.ChoiceField(choices=CustomerPaymentMethod.choices, read_only=True)
    lines = CustomerPaymentLineSerializer(many=True, read_only=True)
    # The part settling sales, and what is left as the customer's credit (0 when voided).
    allocated_total = serializers.SerializerMethodField()
    unallocated = serializers.SerializerMethodField()
    # What is still left to pay on the sales this payment was allocated to.
    remaining = serializers.SerializerMethodField()
    is_voided = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    voided_by = serializers.SerializerMethodField()

    class Meta:
        model = CustomerPayment
        fields: tuple[str, ...] = (
            "id",
            "number",
            "customer",
            "amount",
            "method",
            "lines",
            "received_on",
            "reference",
            "notes",
            "allocated_total",
            "unallocated",
            "remaining",
            "is_voided",
            "voided_at",
            "voided_by",
            "void_reason",
            "created_by",
            "created_at",
        )
        read_only_fields: tuple[str, ...] = fields

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=3))
    def get_allocated_total(self, payment: CustomerPayment) -> str:
        if payment.voided_at is not None:
            return "0.000"
        return str(getattr(payment, "allocated_total", None) or "0.000")

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=3))
    def get_unallocated(self, payment: CustomerPayment) -> str:
        if payment.voided_at is not None:
            return "0.000"
        free = payment.amount - (getattr(payment, "unpaid_total", None) or 0)
        return str(free - (getattr(payment, "allocated_total", None) or 0))

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=3))
    def get_remaining(self, payment: CustomerPayment) -> str:
        """What customers still owe on the sales this payment settled (0 when voided or nothing is left)."""
        from apps.sales import selectors

        if payment.voided_at is not None:
            return "0.000"
        sale_ids = [allocation.sale_id for allocation in payment.allocations.all()]
        if not sale_ids:
            return "0.000"
        left = selectors.outstanding_by_sale(payment.organization, sale_ids)
        return str(sum(left.values(), Decimal("0.000")).quantize(Decimal("0.001")))

    def get_is_voided(self, payment: CustomerPayment) -> bool:
        return payment.voided_at is not None

    def get_created_by(self, payment: CustomerPayment) -> str:
        return person_name(payment.created_by)

    def get_voided_by(self, payment: CustomerPayment) -> str:
        return person_name(payment.voided_by)


class ReceivedEffetEventSerializer(serializers.Serializer[Any]):
    """One step in the life of a received effet: in portfolio, at the bank, cashed, unpaid, cancelled..."""

    from_status = serializers.CharField(read_only=True)
    to_status = serializers.ChoiceField(choices=treasury.INSTRUMENT_STATUS_CHOICES, read_only=True)
    happened_on = serializers.DateField(read_only=True)
    note = serializers.CharField(read_only=True)
    actor = serializers.SerializerMethodField()

    def get_actor(self, event: Any) -> str:
        return person_name(event.actor)


class InstrumentDetailSerializer(InstrumentRefSerializer):
    # Oldest first.
    events = ReceivedEffetEventSerializer(many=True, read_only=True)


class UnpaidEffetSerializer(serializers.Serializer[Any]):
    """The impayé of a line (D-217): when, why, the bank's charges and their expense."""

    unpaid_on = serializers.DateField(read_only=True)
    reason = serializers.CharField(read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    bank_charges = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    expense_number = serializers.CharField(read_only=True)


class CustomerPaymentLineDetailSerializer(CustomerPaymentLineSerializer):
    instrument = InstrumentDetailSerializer(read_only=True, allow_null=True)
    # Set once the bank refused its cheque or traite.
    unpaid = serializers.SerializerMethodField()

    class Meta(CustomerPaymentLineSerializer.Meta):
        fields = (*CustomerPaymentLineSerializer.Meta.fields, "unpaid")
        read_only_fields = fields

    @extend_schema_field(UnpaidEffetSerializer(allow_null=True))
    def get_unpaid(self, line: CustomerPaymentLine) -> dict[str, Any] | None:
        unpaid = getattr(line, "unpaid", None)
        return UnpaidEffetSerializer(unpaid).data if unpaid is not None else None


class CustomerPaymentDetailSerializer(CustomerPaymentSerializer):
    """One règlement with the sales it settled and the history of each of its effets."""

    lines = CustomerPaymentLineDetailSerializer(many=True, read_only=True)
    allocations = CustomerPaymentAllocationSerializer(many=True, read_only=True)

    class Meta(CustomerPaymentSerializer.Meta):
        fields = (*CustomerPaymentSerializer.Meta.fields, "allocations")
        read_only_fields = fields


class CustomerAllocationWriteSerializer(serializers.Serializer[Any]):
    # One of the two: a sale (BL), or an invoice whose amount is spread over its BLs, oldest first.
    sale = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    invoice = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    # DT as a string ("100.000").
    amount = serializers.CharField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if (attrs["sale"] is None) == (attrs["invoice"] is None):
            raise serializers.ValidationError({"amount": _("Indiquez une vente ou une facture.")})
        return attrs


class CustomerPaymentLineWriteSerializer(serializers.Serializer[Any]):
    # `mixed` is refused by the service: it names a règlement, not a line.
    method = serializers.ChoiceField(choices=CustomerPaymentMethod.choices)
    # DT as a string ("500.000").
    amount = serializers.CharField()
    # A transfer or card reference.
    reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=50)
    # A cheque or a traite: its number, bank, drawer (empty: the customer) and échéance.
    number = serializers.CharField(required=False, allow_blank=True, default="", max_length=50)
    bank = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1)
    drawer = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)
    due_on = serializers.DateField(required=False, allow_null=True, default=None)


class AllocateWriteSerializer(serializers.Serializer[Any]):
    # Empty: the customer's oldest open sales first. A list names the sales and amounts; an empty list keeps
    # the whole amount as the customer's credit.
    allocations = CustomerAllocationWriteSerializer(many=True, required=False, allow_null=True, default=None)


class CustomerPaymentWriteSerializer(AllocateWriteSerializer):
    customer = serializers.IntegerField(min_value=1)
    # The means of payment (D-197). Without them, `amount` and `method` (and `reference`) make the one line.
    lines = CustomerPaymentLineWriteSerializer(many=True, required=False, allow_null=True, default=None)
    # With `lines`, optional: when sent it must equal their sum.
    amount = serializers.CharField(required=False, allow_null=True, default=None)
    method = serializers.ChoiceField(choices=CustomerPaymentMethod.choices, required=False)
    # Empty: today.
    received_on = serializers.DateField(required=False, allow_null=True, default=None)
    reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=50)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class UnpaidWriteSerializer(serializers.Serializer[Any]):
    unpaid_on = serializers.DateField(required=False, allow_null=True, default=None)
    reason = serializers.CharField(allow_blank=True, max_length=255)
    # The bank's charges (DT as a string); empty: none.
    bank_charges = serializers.CharField(required=False, allow_blank=True, default="0")


class VoidWriteSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(allow_blank=True, max_length=255)


class CustomerPaymentFilterSerializer(serializers.Serializer[Any]):
    customer = serializers.IntegerField(required=False, min_value=1)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)
    # Those with a line of this means; `mixed`: those with several means.
    method = serializers.ChoiceField(choices=CustomerPaymentMethod.choices, required=False)
    # `active` (not voided), `voided`, or `unallocated` (credit left).
    state = serializers.ChoiceField(choices=["active", "voided", "unallocated"], required=False)


class CustomerPaymentTotalsSerializer(serializers.Serializer[Any]):
    """The totals of the filtered règlements, voided ones left out (their number is in `voided`)."""

    count = serializers.IntegerField(read_only=True)
    voided = serializers.IntegerField(read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    allocated = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    unallocated = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Received by each means, from the lines ({"cash": "500.000", "cheque": ...}).
    by_method = serializers.DictField(child=serializers.DecimalField(max_digits=14, decimal_places=3), read_only=True)


# ---- Balance, ageing ----


class AgeBucketsSerializer(serializers.Serializer[Any]):
    # Outstanding amounts by days since the invoice (or sale) date: 0-30, 31-60, 61 and more.
    d0_30 = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    d31_60 = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    d60_plus = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class OpenSaleSerializer(serializers.Serializer[Any]):
    """A confirmed sale with something left to collect."""

    sale_id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    invoice_id = serializers.IntegerField(read_only=True, allow_null=True)
    invoice_number = serializers.CharField(read_only=True)
    sold_at = serializers.DateTimeField(read_only=True)
    document_date = serializers.DateField(read_only=True)
    due_on = serializers.DateField(read_only=True)
    age_days = serializers.IntegerField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    owed = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    on_spot = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    allocated = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    outstanding = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class HistoryEntrySerializer(serializers.Serializer[Any]):
    # "sale" (what it owes now), "on_spot" (paid at the sale), "payment", or "unpaid" (an effet refused by the
    # bank: owed again, D-217).
    kind = serializers.ChoiceField(choices=["sale", "on_spot", "payment", "unpaid"], read_only=True)
    day = serializers.DateField(read_only=True)
    number = serializers.CharField(read_only=True)
    object_id = serializers.IntegerField(read_only=True)
    # Positive raises what is owed, negative lowers it.
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    method = serializers.CharField(read_only=True)
    voided = serializers.BooleanField(read_only=True)
    balance = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class CustomerBalanceSerializer(serializers.Serializer[Any]):
    customer = QuoteCustomerSerializer(read_only=True)
    credit_limit = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Positive: the customer owes it. Negative: the company holds their credit.
    balance = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # The part of the balance past its due date.
    overdue = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # What is left to collect over their open sales, and the credit held (payments not yet allocated...).
    open_total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    credit = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # The limit minus the balance, never below zero.
    available_credit = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    ageing = AgeBucketsSerializer(read_only=True)
    open_sales = OpenSaleSerializer(many=True, read_only=True)
    # Newest first, at most 200 entries; `balance` is the running balance after each entry.
    history = HistoryEntrySerializer(many=True, read_only=True)


class AgeingRowSerializer(serializers.Serializer[Any]):
    customer = QuoteCustomerSerializer(read_only=True)
    credit_limit = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    balance = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    overdue = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    credit = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    ageing = AgeBucketsSerializer(read_only=True)


class ReceivablesAgeingSerializer(serializers.Serializer[Any]):
    """Every customer who owes (or whose credit we hold), biggest balance first, and the totals."""

    rows = AgeingRowSerializer(many=True, read_only=True)
    total_balance = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    total_overdue = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    total_credit = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    totals = AgeBucketsSerializer(read_only=True)


# ---- Withholding certificates ----


class CertificateInvoiceSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    issued_on = serializers.DateField(read_only=True)
    total_incl_tax = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    withholding_amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    customer = QuoteCustomerSerializer(read_only=True)


class WithholdingCertificateSerializer(InvoiceCertificateSerializer):
    invoice = CertificateInvoiceSerializer(read_only=True)

    class Meta(InvoiceCertificateSerializer.Meta):
        fields = ("id", "invoice", *InvoiceCertificateSerializer.Meta.fields[1:])
        read_only_fields = fields


class WithholdingCertificateWriteSerializer(serializers.Serializer[Any]):
    number = serializers.CharField(allow_blank=True, max_length=50)
    issued_on = serializers.DateField()
    # DT as a string ("3.000").
    amount = serializers.CharField()


class WithholdingFileSerializer(serializers.Serializer[Any]):
    file = UploadedFileField()


class WithholdingFilterSerializer(serializers.Serializer[Any]):
    customer = serializers.IntegerField(required=False, min_value=1)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


class WithholdingMonthSerializer(serializers.Serializer[Any]):
    # "2026-10".
    month = serializers.CharField(read_only=True)
    count = serializers.IntegerField(read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class WithholdingCustomerTotalSerializer(serializers.Serializer[Any]):
    customer = QuoteCustomerSerializer(read_only=True)
    count = serializers.IntegerField(read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class AwaitingInvoiceSerializer(serializers.Serializer[Any]):
    """An issued invoice that planned a withholding and has no certificate yet."""

    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    issued_on = serializers.DateField(read_only=True)
    withholding_amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    customer = QuoteCustomerSerializer(read_only=True)


class WithholdingSummarySerializer(serializers.Serializer[Any]):
    """What customers withheld over a period, for the accountant: totals, per month, per customer, each
    certificate, and the invoices still waiting for theirs."""

    count = serializers.IntegerField(read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    by_month = WithholdingMonthSerializer(many=True, read_only=True)
    by_customer = WithholdingCustomerTotalSerializer(many=True, read_only=True)
    certificates = WithholdingCertificateSerializer(many=True, read_only=True)
    awaiting = AwaitingInvoiceSerializer(many=True, read_only=True)
    awaiting_total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
