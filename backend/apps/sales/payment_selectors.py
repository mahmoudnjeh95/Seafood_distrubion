"""Reusable read queries of customer payments and withholding certificates (P2-T06, D-062, D-063)."""

import datetime as dt
from decimal import Decimal

from django.db.models import DecimalField, Exists, OuterRef, Prefetch, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce

from apps.core.models import Organization

from .models import (
    CustomerPayment,
    CustomerPaymentLine,
    Invoice,
    InvoiceStatus,
    PaymentAllocation,
    WithholdingCertificate,
)


def withholding_certificates_of(
    organization: Organization,
    *,
    customer_id: int | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    include_voided: bool = False,
) -> QuerySet[WithholdingCertificate]:
    """Certificates, newest first, each with its invoice and customer. Days are the certificate's date."""
    certificates = (
        WithholdingCertificate.objects.for_organization(organization)
        .select_related("invoice", "invoice__customer", "created_by")
        .order_by("-issued_on", "-id")
    )
    if not include_voided:
        certificates = certificates.filter(voided_at__isnull=True)
    if customer_id is not None:
        certificates = certificates.filter(invoice__customer_id=customer_id)
    if date_from is not None:
        certificates = certificates.filter(issued_on__gte=date_from)
    if date_to is not None:
        certificates = certificates.filter(issued_on__lte=date_to)
    return certificates


def withholding_certificate_of(organization: Organization, certificate_id: int) -> WithholdingCertificate:
    """One certificate, voided or not. Raises WithholdingCertificate.DoesNotExist outside the organization."""
    return withholding_certificates_of(organization, include_voided=True).get(pk=certificate_id)


def invoices_awaiting_certificate(
    organization: Organization,
    *,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> QuerySet[Invoice]:
    """Issued invoices that planned a withholding and have no live certificate yet (issue dates in the
    period): what the accountant still has to chase."""
    live = WithholdingCertificate.objects.filter(voided_at__isnull=True).values("invoice_id")
    invoices = (
        Invoice.objects.for_organization(organization)
        .select_related("customer")
        .prefetch_related("sales")
        .filter(status=InvoiceStatus.ISSUED, withholding_amount__gt=0)
        .exclude(pk__in=live)
        .order_by("issued_on", "id")
    )
    if date_from is not None:
        invoices = invoices.filter(issued_on__gte=date_from)
    if date_to is not None:
        invoices = invoices.filter(issued_on__lte=date_to)
    return invoices


def customer_payments_of(
    organization: Organization,
    *,
    customer_id: int | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    search: str = "",
) -> QuerySet[CustomerPayment]:
    """Payments (voided ones too), newest first, each with its customer, lines (and their effets), allocations
    (and their sales) and `allocated_total`, the part of the payment settling sales (voided payments allocate
    nothing). `search` also finds the number or reference of one of its lines (a cheque, a traite)."""
    payments = (
        CustomerPayment.objects.for_organization(organization)
        .select_related("customer", "created_by", "voided_by")
        .prefetch_related(Prefetch("allocations", queryset=PaymentAllocation.objects.select_related("sale")))
        .prefetch_related(Prefetch("lines", queryset=CustomerPaymentLine.objects.select_related("instrument__bank")))
        .annotate(
            allocated_total=Coalesce(
                Sum("allocations__amount"),
                Value(Decimal("0.000")),
                output_field=DecimalField(max_digits=14, decimal_places=3),
            )
        )
        .order_by("-received_on", "-id")
    )
    if customer_id is not None:
        payments = payments.filter(customer_id=customer_id)
    if date_from is not None:
        payments = payments.filter(received_on__gte=date_from)
    if date_to is not None:
        payments = payments.filter(received_on__lte=date_to)
    if search := search.strip():
        payments = payments.filter(
            Q(number__icontains=search)
            | Q(reference__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(customer__reference__icontains=search)
            | Exists(
                CustomerPaymentLine.objects.filter(payment=OuterRef("pk")).filter(
                    Q(reference__icontains=search) | Q(instrument__number__icontains=search)
                )
            )
        )
    return payments


def customer_payment_of(organization: Organization, payment_id: int) -> CustomerPayment:
    """One payment with its allocations. Raises CustomerPayment.DoesNotExist outside the organization."""
    return customer_payments_of(organization).get(pk=payment_id)
