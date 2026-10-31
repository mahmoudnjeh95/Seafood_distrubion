"""Reusable read queries of customer payments and withholding certificates (P2-T06, D-062, D-063)."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import DecimalField, Exists, F, OuterRef, Prefetch, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce

from apps.core.models import Organization

from .models import (
    CustomerPayment,
    CustomerPaymentLine,
    CustomerPaymentMethod,
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
    method: str | None = None,
    state: str | None = None,
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
    if method == CustomerPaymentMethod.MIXED:
        payments = payments.filter(method=CustomerPaymentMethod.MIXED)
    elif method:
        payments = payments.filter(Exists(CustomerPaymentLine.objects.filter(payment=OuterRef("pk"), method=method)))
    if state == "active":
        payments = payments.filter(voided_at__isnull=True)
    elif state == "voided":
        payments = payments.filter(voided_at__isnull=False)
    elif state == "unallocated":
        payments = payments.filter(voided_at__isnull=True, amount__gt=F("allocated_total"))
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
    """One payment with its allocations and each effet's history. Raises CustomerPayment.DoesNotExist outside the
    organization."""
    return customer_payments_of(organization).prefetch_related("lines__instrument__events__actor").get(pk=payment_id)


@dataclass(frozen=True)
class CustomerPaymentTotals:
    """What a filtered list of règlements adds up to, voided ones left out; `by_method` from their lines."""

    count: int
    voided: int
    total: Decimal
    allocated: Decimal
    unallocated: Decimal
    by_method: dict[str, Decimal]


def customer_payment_totals(payments: QuerySet[CustomerPayment]) -> CustomerPaymentTotals:
    """The totals of `payments` (a `customer_payments_of` queryset, its filters applied)."""
    ids = payments.filter(voided_at__isnull=True).values("pk")
    live = CustomerPayment.objects.filter(pk__in=ids)
    total = live.aggregate(total=Sum("amount"))["total"] or Decimal("0.000")
    allocated = PaymentAllocation.objects.filter(payment__in=ids).aggregate(total=Sum("amount"))["total"] or Decimal(
        "0.000"
    )
    by_method = {
        row["method"]: row["total"]
        for row in CustomerPaymentLine.objects.filter(payment__in=ids)
        .values("method")
        .annotate(total=Sum("amount"))
        .order_by("method")
    }
    return CustomerPaymentTotals(
        count=live.count(),
        voided=payments.filter(voided_at__isnull=False).count(),
        total=total,
        allocated=allocated,
        unallocated=total - allocated,
        by_method=by_method,
    )
