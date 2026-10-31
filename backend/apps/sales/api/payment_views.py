"""Customer payments (règlements with several lines, D-197), balances, ageing and withholding certificates
(P2-T06, D-062, D-063).

Office data: the owner and the manager write, the accountant reads, drivers get 403 (collecting money on the
phone is a later task).
"""

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import QuerySet
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api.pagination import PagedList
from apps.core.xlsx import XLSX_TYPE, workbook_bytes, xlsx_response
from apps.partners import selectors as partners
from apps.sales import payment_selectors, receivables, selectors, services
from apps.sales.models import CustomerPayment, Invoice, WithholdingCertificate
from apps.treasury import selectors as treasury

from .payment_serializers import (
    AllocateWriteSerializer,
    CustomerBalanceSerializer,
    CustomerPaymentDetailSerializer,
    CustomerPaymentFilterSerializer,
    CustomerPaymentSerializer,
    CustomerPaymentTotalsSerializer,
    CustomerPaymentWriteSerializer,
    ReceivablesAgeingSerializer,
    UnpaidWriteSerializer,
    VoidWriteSerializer,
    WithholdingCertificateSerializer,
    WithholdingCertificateWriteSerializer,
    WithholdingFileSerializer,
    WithholdingFilterSerializer,
    WithholdingSummarySerializer,
)
from .views import OfficeView

ZERO = Decimal("0.000")
HISTORY_LIMIT = 200


def _allocations(organization: Any, data: Any) -> Any:
    """The sales or invoices named in a payment's allocations, as rows of the organization; unknown ones are
    field errors. None stays None (allocate the oldest open sales first)."""
    if data is None:
        return None
    errors: dict[str, str] = {}
    rows = []
    for index, item in enumerate(data):
        if item.get("invoice") is not None:
            try:
                invoice = selectors.invoice_of(organization, item["invoice"])
            except ObjectDoesNotExist:
                errors[f"allocations.{index}.amount"] = _("Facture inconnue.")
                continue
            rows.append({"invoice": invoice, "amount": item["amount"]})
            continue
        try:
            sale = selectors.sale_of(organization, item["sale"])
        except ObjectDoesNotExist:
            errors[f"allocations.{index}.amount"] = _("Vente inconnue.")
            continue
        rows.append({"sale": sale, "amount": item["amount"]})
    if errors:
        raise ValidationError(errors)
    return rows


def _lines(organization: Any, data: Any) -> Any:
    """The règlement's lines with their bank and account as rows of the organization; an unknown one is an error on
    `lines.<index>.bank` or `.account`. None stays None (the single `amount` and `method` make the line)."""
    if data is None:
        return None
    errors: dict[str, str] = {}
    rows = []
    for index, item in enumerate(data):
        bank = account = None
        if item["bank"] is not None:
            try:
                bank = treasury.bank_of(organization, item["bank"])
            except ObjectDoesNotExist:
                errors[f"lines.{index}.bank"] = _("Banque inconnue.")
        if item.get("account") is not None:
            try:
                account = treasury.account_of(organization, item["account"])
            except ObjectDoesNotExist:
                errors[f"lines.{index}.account"] = _("Compte inconnu.")
        rows.append({**item, "bank": bank, "account": account})
    if errors:
        raise ValidationError(errors)
    return rows


def _buckets(values: dict[str, Decimal]) -> dict[str, Decimal]:
    return {key: values.get(key, ZERO) for key in ("d0_30", "d31_60", "d60_plus")}


class CustomerPaymentView(OfficeView):
    def payment(self, payment_id: int) -> CustomerPayment:
        try:
            return payment_selectors.customer_payment_of(self.organization, payment_id)
        except CustomerPayment.DoesNotExist:
            raise Http404 from None

    def answer(self, payment_id: int, *, status_code: int = status.HTTP_200_OK) -> Response:
        return Response(CustomerPaymentDetailSerializer(self.payment(payment_id)).data, status=status_code)


class CustomerPaymentListView(CustomerPaymentView, ListAPIView[CustomerPayment]):
    serializer_class = CustomerPaymentSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[CustomerPayment]:
        return _filtered_payments(self.organization, self.request)

    @extend_schema(operation_id="listCustomerPayments", parameters=[CustomerPaymentFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Customer payments, newest first, paginated, voided ones included. Filter by customer, days
        received (inclusive), means (`mixed`: several), state (`active`, `voided`, `unallocated`) or `search`
        (number, reference, cheque or traite number, customer)."""
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="createCustomerPayment",
        request=CustomerPaymentWriteSerializer,
        responses={201: CustomerPaymentDetailSerializer},
    )
    def post(self, request: Request) -> Response:
        """Register a règlement received from a customer (owner or manager). `lines` gives its means (cash,
        cheques, traites with number, bank and échéance, transfer, card); without it, `amount` and `method` make
        its one line. `allocations` empty or absent settles their oldest open sales first; a list names the sales
        or invoices and amounts (an empty list keeps everything as credit). Errors of a row come back on
        `lines.<index>.<field>` and `allocations.<index>.amount`."""
        serializer = CustomerPaymentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            customer = partners.customer_of(self.organization, data["customer"])
        except ObjectDoesNotExist:
            raise ValidationError({"customer": _("Client inconnu.")}) from None
        payment = services.record_customer_payment(
            organization=self.organization,
            actor=self.membership.user,
            customer=customer,
            amount=data["amount"],
            method=data.get("method", ""),
            lines=_lines(self.organization, data["lines"]),
            received_on=data["received_on"],
            reference=data["reference"],
            notes=data["notes"],
            allocations=_allocations(self.organization, data["allocations"]),
        )
        return self.answer(payment.pk, status_code=status.HTTP_201_CREATED)


def _filtered_payments(organization: Any, request: Request) -> QuerySet[CustomerPayment]:
    filters = CustomerPaymentFilterSerializer(data=request.query_params)
    filters.is_valid(raise_exception=True)
    data = filters.validated_data
    return payment_selectors.customer_payments_of(
        organization,
        customer_id=data.get("customer"),
        date_from=data.get("date_from"),
        date_to=data.get("date_to"),
        search=data["search"],
        method=data.get("method"),
        state=data.get("state"),
    )


class CustomerPaymentTotalsView(OfficeView):
    @extend_schema(
        operation_id="getCustomerPaymentTotals",
        parameters=[CustomerPaymentFilterSerializer],
        responses=CustomerPaymentTotalsSerializer,
    )
    def get(self, request: Request) -> Response:
        """What the règlements of the same filters as the list add up to (voided ones left out): their count,
        total, allocated, credit left, and what each means brought."""
        totals = payment_selectors.customer_payment_totals(_filtered_payments(self.organization, request))
        return Response(CustomerPaymentTotalsSerializer(totals).data)


class CustomerPaymentExportView(OfficeView):
    @extend_schema(
        operation_id="exportCustomerPayments",
        parameters=[CustomerPaymentFilterSerializer],
        responses={(200, XLSX_TYPE): OpenApiTypes.BINARY},
    )
    def get(self, request: Request) -> HttpResponse:
        """The règlements of the same filters as the list, as an Excel file (one row each, voided ones marked)."""
        payments = list(_filtered_payments(self.organization, request)[:5000])
        zero = Decimal("0.000")

        def allocated(payment: CustomerPayment) -> Decimal:
            return zero if payment.voided_at else getattr(payment, "allocated_total")  # noqa: B009

        rows = [
            [
                payment.number,
                payment.received_on,
                payment.customer.name,
                payment.get_method_display(),
                ", ".join(_line_label(line) for line in payment.lines.all()),
                payment.amount,
                allocated(payment),
                zero if payment.voided_at else payment.amount - allocated(payment),
                _("Annulé") if payment.voided_at else "",
            ]
            for payment in payments
        ]
        live = [payment for payment in payments if payment.voided_at is None]
        content = workbook_bytes(
            title=_("Règlements clients"),
            headers=[
                _("N°"),
                _("Date"),
                _("Client"),
                _("Mode"),
                _("Moyens"),
                _("Montant"),
                _("Affecté"),
                _("Crédit"),
                _("État"),
            ],
            rows=rows,
            totals=[
                _("Total"),
                "",
                "",
                "",
                "",
                sum((payment.amount for payment in live), zero),
                sum((allocated(payment) for payment in live), zero),
                sum((payment.amount - allocated(payment) for payment in live), zero),
                "",
            ],
        )
        return xlsx_response("reglements-clients", content)


def _line_label(line: Any) -> str:
    label = str(line.get_method_display())
    if line.instrument is not None:
        label += f" {line.instrument.number}"
    elif line.reference:
        label += f" {line.reference}"
    return f"{label} ({line.amount})"


class CustomerEffetUnpaidView(CustomerPaymentView):
    @extend_schema(
        operation_id="recordUnpaidEffet", request=UnpaidWriteSerializer, responses=CustomerPaymentDetailSerializer
    )
    def post(self, request: Request, instrument_id: int) -> Response:
        """The bank refused this customer cheque or traite (owner or manager): it becomes "Impayé", the customer
        owes its amount again (the sales its règlement settled owe again beyond its credit), the bank's charges
        become an expense "Frais financiers" and the office is told (D-217). Answers with the règlement."""
        serializer = UnpaidWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        unpaid = services.record_unpaid_effet(
            organization=self.organization,
            actor=self.membership.user,
            instrument_id=instrument_id,
            unpaid_on=data["unpaid_on"],
            reason=data["reason"],
            bank_charges=data["bank_charges"],
        )
        return self.answer(unpaid.payment_id)


class CustomerPaymentDetailView(CustomerPaymentView):
    @extend_schema(operation_id="getCustomerPayment", responses=CustomerPaymentDetailSerializer)
    def get(self, request: Request, payment_id: int) -> Response:
        """One payment with its means (each effet with its history) and the sales it settled."""
        return self.answer(payment_id)


class CustomerPaymentAllocateView(CustomerPaymentView):
    @extend_schema(
        operation_id="allocateCustomerPayment",
        request=AllocateWriteSerializer,
        responses=CustomerPaymentDetailSerializer,
    )
    def post(self, request: Request, payment_id: int) -> Response:
        """Settle sales with what is left of a payment: the named sales and amounts, or (without
        `allocations`) the customer's oldest open sales first."""
        serializer = AllocateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.allocate_customer_payment(
            payment=self.payment(payment_id),
            actor=self.membership.user,
            allocations=_allocations(self.organization, serializer.validated_data["allocations"]),
        )
        return self.answer(payment_id)


class CustomerPaymentVoidView(CustomerPaymentView):
    @extend_schema(
        operation_id="voidCustomerPayment", request=VoidWriteSerializer, responses=CustomerPaymentDetailSerializer
    )
    def post(self, request: Request, payment_id: int) -> Response:
        """Cancel a payment typed by mistake (a reason is required): it stays, marked voided, and the sales
        it settled owe again."""
        serializer = VoidWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.void_customer_payment(
            payment=self.payment(payment_id),
            actor=self.membership.user,
            reason=serializer.validated_data["reason"],
        )
        return self.answer(payment_id)


# ---- Balance and ageing ----


def _balance_row(customer: Any, balance: receivables.CustomerBalance) -> dict[str, Any]:
    return {
        "customer": customer,
        "credit_limit": customer.credit_limit,
        "balance": balance.balance,
        "overdue": balance.overdue,
        "credit": balance.credit,
        "ageing": _buckets(balance.buckets),
    }


class CustomerBalanceView(OfficeView):
    @extend_schema(operation_id="getCustomerBalance", responses=CustomerBalanceSerializer)
    def get(self, request: Request, customer_id: int) -> Response:
        """What one customer owes: balance (negative = their credit), the part overdue, the ageing in 0-30,
        31-60 and 61+ days, the open sales (oldest first) and their account history with a running balance."""
        try:
            customer = partners.customer_of(self.organization, customer_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        today = timezone.localdate()
        balance = receivables.customer_balance(self.organization, customer.pk, today=today)
        history = receivables.customer_history(self.organization, customer.pk)
        data = {
            **_balance_row(customer, balance),
            "open_total": balance.open_total,
            "available_credit": max(customer.credit_limit - balance.balance, ZERO),
            "open_sales": [
                {
                    "sale_id": row.sale_id,
                    "number": row.number,
                    "invoice_id": row.invoice_id,
                    "invoice_number": row.invoice_number,
                    "sold_at": row.sold_at,
                    "document_date": row.document_date,
                    "due_on": row.due_on,
                    "age_days": row.age_days(today),
                    "is_overdue": row.is_overdue(today),
                    "owed": row.owed,
                    "on_spot": row.on_spot,
                    "allocated": row.allocated,
                    "outstanding": row.outstanding,
                }
                for row in balance.open_sales
            ],
            "history": list(reversed(history))[:HISTORY_LIMIT],
        }
        return Response(CustomerBalanceSerializer(data).data)


class ReceivablesAgeingView(OfficeView):
    @extend_schema(operation_id="getReceivablesAgeing", responses=ReceivablesAgeingSerializer)
    def get(self, request: Request) -> Response:
        """Every customer who owes, or whose credit is held, biggest balance first: balance, part overdue,
        credit and the ageing buckets (0-30, 31-60, 61+ days), with the totals."""
        balances = receivables.customer_balances(self.organization)
        customers = {customer.pk: customer for customer in partners.customers_of(self.organization, status="all")}
        rows = [
            _balance_row(customers[key], value)
            for key, value in balances.items()
            if key in customers and (value.balance != 0 or value.open_total != 0 or value.credit != 0)
        ]
        rows.sort(key=lambda row: (-row["balance"], row["customer"].name))
        totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for row in rows:
            for key, amount in row["ageing"].items():
                totals[key] += amount
        data = {
            "rows": rows,
            "total_balance": sum((row["balance"] for row in rows if row["balance"] > 0), ZERO),
            "total_overdue": sum((row["overdue"] for row in rows), ZERO),
            "total_credit": sum((row["credit"] for row in rows), ZERO),
            "totals": _buckets(totals),
        }
        return Response(ReceivablesAgeingSerializer(data).data)


# ---- Withholding certificates ----


class InvoiceCertificateView(OfficeView):
    @extend_schema(
        operation_id="recordWithholdingCertificate",
        request=WithholdingCertificateWriteSerializer,
        responses={201: WithholdingCertificateSerializer},
    )
    def post(self, request: Request, invoice_id: int) -> Response:
        """Record what the customer withheld on an issued invoice with its certificate's number, date and
        amount (owner or manager). The amount replaces the planned withholding in the receivable. The file
        is joined with `addWithholdingCertificateFile`."""
        serializer = WithholdingCertificateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            invoice = selectors.invoice_of(self.organization, invoice_id)
        except Invoice.DoesNotExist:
            raise Http404 from None
        data = serializer.validated_data
        certificate = services.record_withholding_certificate(
            invoice=invoice,
            actor=self.membership.user,
            number=data["number"],
            issued_on=data["issued_on"],
            amount=data["amount"],
        )
        row = payment_selectors.withholding_certificate_of(self.organization, certificate.pk)
        return Response(WithholdingCertificateSerializer(row).data, status=status.HTTP_201_CREATED)


class CertificateBaseView(OfficeView):
    def certificate(self, certificate_id: int) -> WithholdingCertificate:
        try:
            return payment_selectors.withholding_certificate_of(self.organization, certificate_id)
        except WithholdingCertificate.DoesNotExist:
            raise Http404 from None


class WithholdingCertificateView(CertificateBaseView):
    parser_classes = (MultiPartParser,)

    # Read by an <img> tag or a link, not by the generated client: kept out of the API contract.
    @extend_schema(exclude=True)
    def get(self, request: Request, certificate_id: int) -> FileResponse:
        certificate = self.certificate(certificate_id)
        if not certificate.file:
            raise Http404
        is_pdf = (certificate.file.name or "").endswith(".pdf")
        response = FileResponse(certificate.file.open("rb"), content_type="application/pdf" if is_pdf else "image/webp")
        response["Cache-Control"] = "private, max-age=3600"
        return response

    @extend_schema(
        operation_id="addWithholdingCertificateFile",
        request={"multipart/form-data": WithholdingFileSerializer},
        responses={200: WithholdingCertificateSerializer, 400: OpenApiResponse(description="Not a photo or a PDF")},
    )
    def put(self, request: Request, certificate_id: int) -> Response:
        """Join the certificate's file: a photo (turned upright, shrunk, stored as WebP) or a PDF. Replaces
        an earlier file of a live certificate."""
        serializer = WithholdingFileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_certificate_file(
            certificate=self.certificate(certificate_id),
            actor=self.membership.user,
            upload=serializer.validated_data["file"],
        )
        return Response(WithholdingCertificateSerializer(self.certificate(certificate_id)).data)


class WithholdingCertificateVoidView(CertificateBaseView):
    @extend_schema(
        operation_id="voidWithholdingCertificate",
        request=VoidWriteSerializer,
        responses=WithholdingCertificateSerializer,
    )
    def post(self, request: Request, certificate_id: int) -> Response:
        """Cancel a certificate typed by mistake (a reason is required): the invoice's planned withholding
        counts again."""
        serializer = VoidWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.void_withholding_certificate(
            certificate=self.certificate(certificate_id),
            actor=self.membership.user,
            reason=serializer.validated_data["reason"],
        )
        return Response(WithholdingCertificateSerializer(self.certificate(certificate_id)).data)


class WithholdingSummaryView(OfficeView):
    @extend_schema(
        operation_id="getWithholdingSummary",
        parameters=[WithholdingFilterSerializer],
        responses=WithholdingSummarySerializer,
    )
    def get(self, request: Request) -> Response:
        """For the accountant: what customers withheld over a period (certificate dates, both ends
        included): total, per month, per customer, each certificate, and the issued invoices that planned a
        withholding but have no certificate yet."""
        filters = WithholdingFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        date_from: dt.date | None = filters.validated_data.get("date_from")
        date_to: dt.date | None = filters.validated_data.get("date_to")
        customer_id = filters.validated_data.get("customer")
        certificates = list(
            payment_selectors.withholding_certificates_of(
                self.organization, customer_id=customer_id, date_from=date_from, date_to=date_to
            )
        )
        by_month: dict[str, list[Decimal]] = defaultdict(list)
        by_customer: dict[int, tuple[Any, list[Decimal]]] = {}
        for certificate in certificates:
            by_month[certificate.issued_on.strftime("%Y-%m")].append(certificate.amount)
            customer = certificate.invoice.customer
            by_customer.setdefault(customer.pk, (customer, []))[1].append(certificate.amount)
        awaiting_query = payment_selectors.invoices_awaiting_certificate(
            self.organization, date_from=date_from, date_to=date_to
        )
        if customer_id is not None:
            awaiting_query = awaiting_query.filter(customer_id=customer_id)
        awaiting = list(awaiting_query)
        data = {
            "count": len(certificates),
            "total": sum((certificate.amount for certificate in certificates), ZERO),
            "by_month": [
                {"month": month, "count": len(amounts), "amount": sum(amounts, ZERO)}
                for month, amounts in sorted(by_month.items())
            ],
            "by_customer": sorted(
                (
                    {"customer": customer, "count": len(amounts), "amount": sum(amounts, ZERO)}
                    for customer, amounts in by_customer.values()
                ),
                key=lambda row: row["customer"].name,
            ),
            "certificates": certificates,
            "awaiting": awaiting,
            "awaiting_total": sum((invoice.withholding_amount for invoice in awaiting), ZERO),
        }
        return Response(WithholdingSummarySerializer(data).data)
