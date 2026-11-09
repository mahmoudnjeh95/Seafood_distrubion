"""Supplier credit notes (avoirs fournisseurs, D-300): goods sent back, kilos invoiced not accepted, price cuts."""

from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import QuerySet
from django.http import Http404
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api.pagination import PagedList
from apps.partners import selectors as partners
from apps.purchasing import selectors, services
from apps.purchasing.models import (
    SupplierCreditAllocation,
    SupplierCreditKind,
    SupplierCreditNote,
    SupplierCreditNoteLine,
    SupplierInvoice,
)

from .serializers import RefSerializer
from .views import PurchasingView


class SupplierCreditNoteLineSerializer(serializers.ModelSerializer[SupplierCreditNoteLine]):
    kind = serializers.ChoiceField(choices=SupplierCreditKind.choices, read_only=True)
    receipt_id = serializers.IntegerField(source="receipt_line.receipt_id", read_only=True)
    receipt_number = serializers.CharField(source="receipt_line.receipt.number", read_only=True)
    product_name = serializers.CharField(source="receipt_line.product.name", read_only=True)
    batch_number = serializers.CharField(source="batch.number", read_only=True)
    from_location_name = serializers.CharField(source="from_location.name", read_only=True, allow_null=True)

    class Meta:
        model = SupplierCreditNoteLine
        fields = (
            "id",
            "receipt_line",
            "receipt_id",
            "receipt_number",
            "product_name",
            "batch",
            "batch_number",
            "kind",
            "quantity",
            "unit_amount",
            "amount",
            "vat_rate",
            "vat_amount",
            "from_location",
            "from_location_name",
        )
        read_only_fields = fields


class SupplierCreditAllocationSerializer(serializers.ModelSerializer[SupplierCreditAllocation]):
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)

    class Meta:
        model = SupplierCreditAllocation
        fields = ("invoice", "invoice_number", "amount")
        read_only_fields = fields


class SupplierCreditNoteSerializer(serializers.ModelSerializer[SupplierCreditNote]):
    supplier = RefSerializer(read_only=True)
    invoice_number = serializers.CharField(source="invoice.number", read_only=True, allow_null=True)
    lines = SupplierCreditNoteLineSerializer(many=True, read_only=True)
    allocations = SupplierCreditAllocationSerializer(many=True, read_only=True)
    # What settled invoices; the rest waits for the supplier's next invoice.
    applied_amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = SupplierCreditNote
        fields = (
            "id",
            "number",
            "supplier",
            "invoice",
            "invoice_number",
            "credited_on",
            "supplier_reference",
            "reason",
            "total_excl_tax",
            "vat_total",
            "total",
            "applied_amount",
            "lines",
            "allocations",
            "created_by",
            "created_at",
        )
        read_only_fields = fields

    def get_created_by(self, note: SupplierCreditNote) -> str:
        user = note.created_by
        if user is None:
            return ""
        return f"{user.first_name} {user.last_name}".strip() or str(user.username)


class SupplierCreditNoteLineWriteSerializer(serializers.Serializer[Any]):
    receipt_line = serializers.IntegerField(min_value=1)
    kind = serializers.ChoiceField(choices=SupplierCreditKind.choices)
    quantity = serializers.CharField(max_length=20)
    # A price cut only: DT per kg without VAT.
    unit_amount = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    # A return only: where the kilos leave from.
    from_location = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)


class SupplierCreditNoteWriteSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(min_value=1)
    invoice = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    credited_on = serializers.DateField()
    reason = serializers.CharField(allow_blank=True)
    supplier_reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=50)
    lines = SupplierCreditNoteLineWriteSerializer(many=True, allow_empty=True)


class SupplierCreditNoteFilterSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(min_value=1, required=False)
    invoice = serializers.IntegerField(min_value=1, required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)


class CreditableFilterSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(min_value=1)
    invoice = serializers.IntegerField(min_value=1, required=False)


class CreditableLineSerializer(serializers.Serializer[Any]):
    receipt_line_id = serializers.IntegerField(read_only=True)
    receipt_id = serializers.IntegerField(read_only=True)
    receipt_number = serializers.CharField(read_only=True)
    received_on = serializers.DateField(read_only=True)
    invoice_id = serializers.IntegerField(read_only=True, allow_null=True)
    invoice_number = serializers.CharField(read_only=True)
    batch_id = serializers.IntegerField(read_only=True)
    batch_number = serializers.CharField(read_only=True)
    product_id = serializers.IntegerField(read_only=True)
    product_name = serializers.CharField(read_only=True)
    invoiced_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    accepted_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    with_vat = serializers.BooleanField(read_only=True)
    weight_gap = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    returned = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    amount_left = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class WeightGapSerializer(serializers.Serializer[Any]):
    supplier_id = serializers.IntegerField(read_only=True)
    supplier_name = serializers.CharField(read_only=True)
    lines = serializers.IntegerField(read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class CreditNoteListView(PurchasingView, ListAPIView[SupplierCreditNote]):
    serializer_class = SupplierCreditNoteSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[SupplierCreditNote]:
        filters = SupplierCreditNoteFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        return selectors.credit_notes_of(
            self.organization, supplier_id=data.get("supplier"), invoice_id=data.get("invoice"), search=data["search"]
        )

    @extend_schema(operation_id="listSupplierCreditNotes", parameters=[SupplierCreditNoteFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Supplier credit notes (avoirs fournisseurs, D-300), newest first, paginated."""
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="createSupplierCreditNote",
        request=SupplierCreditNoteWriteSerializer,
        responses={201: SupplierCreditNoteSerializer},
    )
    def post(self, request: Request) -> Response:
        """Save an avoir fournisseur: per receipt line a return (kilos leave the stock from `from_location`), a
        weight gap (invoiced − accepted) or a price cut per kg (`unit_amount`). It settles its invoice, then the
        other open invoices; never edited. Errors on `supplier`, `invoice`, `reason`, `credited_on`, `lines`,
        `lines.<index>.<field>`. Owner or manager."""
        serializer = SupplierCreditNoteWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        organization = self.organization
        try:
            supplier = partners.supplier_of(organization, data["supplier"])
        except ObjectDoesNotExist:
            raise ValidationError({"supplier": _("Fournisseur inconnu.")}) from None
        invoice = None
        if data["invoice"] is not None:
            try:
                invoice = selectors.invoice_of(organization, data["invoice"])
            except SupplierInvoice.DoesNotExist:
                raise ValidationError({"invoice": _("Facture inconnue.")}) from None
        note = services.create_credit_note(
            organization=organization,
            actor=self.membership.user,
            supplier=supplier,
            invoice=invoice,
            credited_on=data["credited_on"],
            reason=data["reason"],
            supplier_reference=data["supplier_reference"],
            lines=data["lines"],
        )
        body = SupplierCreditNoteSerializer(selectors.credit_note_of(organization, note.pk)).data
        return Response(body, status=status.HTTP_201_CREATED)


class CreditNoteDetailView(PurchasingView):
    @extend_schema(operation_id="getSupplierCreditNote", responses=SupplierCreditNoteSerializer)
    def get(self, request: Request, credit_note_id: int) -> Response:
        try:
            note = selectors.credit_note_of(self.organization, credit_note_id)
        except SupplierCreditNote.DoesNotExist:
            raise Http404 from None
        return Response(SupplierCreditNoteSerializer(note).data)


class CreditableLinesView(PurchasingView):
    @extend_schema(
        operation_id="listCreditableReceiptLines",
        parameters=[CreditableFilterSerializer],
        responses=CreditableLineSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """The supplier's receipt lines an avoir may still credit, newest first; with `invoice`, only its own."""
        filters = CreditableFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        rows = selectors.creditable_lines(
            self.organization,
            supplier_id=filters.validated_data["supplier"],
            invoice_id=filters.validated_data.get("invoice"),
        )
        return Response(CreditableLineSerializer(rows, many=True).data)


class WeightGapsView(PurchasingView):
    @extend_schema(operation_id="listSupplierWeightGaps", responses=WeightGapSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Per supplier, kilos invoiced above what was accepted and not claimed yet, the biggest amount first."""
        return Response(WeightGapSerializer(selectors.weight_gaps(self.organization), many=True).data)
