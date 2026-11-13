"""The PDF receipt of a supplier règlement (P9-T03c, D-215): what was paid, by which means, for which invoices."""

from decimal import Decimal
from typing import Any

from django.utils.text import slugify

from apps.core.models import Organization
from apps.documents import services as documents
from apps.sales import selectors as sales

from .models import GoodsReceipt, PaymentMethod, PurchaseOrder, SupplierInvoice
from .selectors import payment_of


def _seller_of(organization: Organization) -> dict[str, str]:
    version = sales.finance_settings_on(organization)
    if version is None:
        return {"name": organization.name, "address": "", "phone": "", "tax_id": "", "trade_register": ""}
    return {
        "name": version.legal_name or organization.name,
        "address": version.address,
        "phone": version.phone,
        "tax_id": version.tax_id,
        "trade_register": version.trade_register,
    }


def _supplier_party(supplier: Any) -> dict[str, str]:
    address = supplier.address
    if supplier.city:
        address = f"{address}, {supplier.city}" if address else supplier.city
    return {
        "label": "Fournisseur",
        "name": supplier.name,
        "reference": supplier.reference,
        "address": address,
        "phone": supplier.phone,
        "tax_id": supplier.tax_id,
    }


def _withholding_certificate(organization: Organization, payment: Any) -> documents.Printable:
    """The certificate of the tax withheld from one supplier invoice (D-327): the règlement "Retenue à la source"
    prints as it."""
    invoice = SupplierInvoice.objects.for_organization(organization).get(withholding_payment=payment)
    base = invoice.total_excl_tax + invoice.vat_total
    return documents.Printable(
        template="purchasing/pdf/withholding_certificate.html",
        context={
            "number": payment.number,
            "seller": _seller_of(organization),
            "doc_date": payment.paid_on,
            "party": _supplier_party(payment.supplier),
            "invoice": invoice,
            "base": base,
            "net": base - invoice.withholding_amount,
        },
        version=payment.updated_at.isoformat(),
        filename=f"certificat-retenue-{slugify(payment.number) or 'document'}.pdf",
        title=f"Certificat de retenue {payment.number}",
        email_to=payment.supplier.email_addresses(),
    )


def supplier_receipt_printable(organization: Organization, payment_id: int) -> documents.Printable:
    payment = payment_of(organization, payment_id)
    if payment.method == PaymentMethod.WITHHOLDING:
        return _withholding_certificate(organization, payment)
    allocations = list(payment.allocations.all())
    allocated = Decimal("0.000") if payment.voided_at else sum((row.amount for row in allocations), Decimal("0.000"))
    context: dict[str, Any] = {
        "number": payment.number,
        "seller": _seller_of(organization),
        "payment": payment,
        "doc_date": payment.paid_on,
        "party": _supplier_party(payment.supplier),
        "method_label": str(PaymentMethod(payment.method).label),
        "lines": [
            {
                "method_label": str(PaymentMethod(line.method).label),
                "number": line.instrument.number if line.instrument else line.reference,
                "bank": line.instrument.bank.code if line.instrument and line.instrument.bank else "",
                "due_on": line.instrument.due_on if line.instrument else None,
                "amount": line.amount,
            }
            for line in payment.lines.all()
        ],
        "allocations": [
            {
                "number": row.invoice.number,
                "supplier_reference": row.invoice.supplier_reference,
                "invoice_date": row.invoice.invoice_date,
                "amount": row.amount,
            }
            for row in allocations
        ],
        "unallocated": Decimal("0.000") if payment.voided_at else payment.amount - allocated,
    }
    return documents.Printable(
        template="purchasing/pdf/supplier_receipt.html",
        context=context,
        # Allocating an advance later does not touch the payment row itself.
        version=f"{payment.updated_at.isoformat()}|{allocated}",
        filename=f"paiement-{slugify(payment.number) or 'document'}.pdf",
        title=f"Paiement {payment.number}",
        email_to=payment.supplier.email_addresses(),
    )


def register_printables() -> None:
    documents.register(documents.DocumentKind.SUPPLIER_RECEIPT, supplier_receipt_printable)


def _exists(model: Any) -> Any:
    def exists(organization: Organization, object_id: int) -> bool:
        return bool(model.objects.for_organization(organization).filter(pk=object_id).exists())

    return exists


def register_attachables() -> None:
    """The purchase documents files can be attached to (D-288)."""
    documents.register_attachable("purchase_order", _exists(PurchaseOrder))
    documents.register_attachable("goods_receipt", _exists(GoodsReceipt))
    documents.register_attachable("supplier_invoice", _exists(SupplierInvoice))
