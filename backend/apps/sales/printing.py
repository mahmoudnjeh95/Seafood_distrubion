"""What the PDFs of sales documents show (P2-T08, D-071): the template, its data and the document's version.

Registered with the documents app when sales starts (`SalesConfig.ready`). Each provider reads through the
selectors and raises `ObjectDoesNotExist` outside the organization.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.boxes import services as box_services
from apps.core.models import Organization
from apps.documents import services as documents

from . import selectors
from .models import (
    CreditNoteKind,
    CreditNoteStock,
    CustomerPaymentMethod,
    DeliveryStatus,
    InvoiceStatus,
    QuoteStatus,
    Sale,
    SaleRevisionKind,
    SaleStatus,
)
from .payment_selectors import customer_payment_of


def _file_name(prefix: str, number: str) -> str:
    return f"{prefix}-{slugify(number) or 'document'}.pdf"


def _seller_of(organization: Organization) -> dict[str, str]:
    """Who sells, from the finance settings in force (quotes and receipts: nothing is frozen on them)."""
    version = selectors.finance_settings_on(organization)
    if version is None:
        return {"name": organization.name, "address": "", "phone": "", "tax_id": "", "trade_register": ""}
    return {
        "name": version.legal_name or organization.name,
        "address": version.address,
        "phone": version.phone,
        "tax_id": version.tax_id,
        "trade_register": version.trade_register,
    }


# The lines area of the invoice is drawn down to this height (mm) like the paper form; more lines just flow on.
INVOICE_LINES_HEIGHT_MM = 72
INVOICE_LINE_HEIGHT_MM = 7

# The category letter of a Tunisian tax id ("1796419/D/N/M/000"): M for companies, P for individuals.
_TAX_ID_CATEGORIES = {"M": "Personne morale", "P": "Personne physique"}


def _tax_id_parts(tax_id: str) -> list[str]:
    return [part.strip().upper() for part in tax_id.replace(" ", "").split("/")]


# The "Identifiant unique" is read from a tax id by the documents app (the header of every document prints it).
unique_identifier = documents.unique_identifier


def customer_type(tax_id: str, kind: str) -> str:
    """Personne morale / physique, read from the tax id's category letter, else from the customer kind."""
    parts = _tax_id_parts(tax_id)
    if len(parts) >= 4 and parts[3] in _TAX_ID_CATEGORIES:
        return _TAX_ID_CATEGORIES[parts[3]]
    if kind == "individual":  # partners.CustomerKind.INDIVIDUAL
        return _TAX_ID_CATEGORIES["P"]
    return ""


def _address(address: str, city: str) -> str:
    return f"{address}, {city}" if address and city else address or city


def _customer_party(customer: Any) -> dict[str, str]:
    """The client block of the shared document header (D-131), read live from the customer."""
    return {
        "label": "Client",
        "name": customer.name,
        "reference": customer.reference,
        "type": customer_type(customer.tax_id, customer.kind),
        "address": _address(customer.address, customer.city),
        "phone": customer.phone,
        "tax_id": customer.tax_id,
    }


def _invoiced_party(invoice: Any) -> dict[str, str]:
    """The client as frozen on an invoice; its code and phone are not frozen, they are read from the customer."""
    customer = invoice.customer
    return {
        "label": "Client",
        "name": invoice.customer_name,
        "reference": customer.reference,
        "type": customer_type(invoice.customer_tax_id, customer.kind),
        "address": _address(invoice.customer_address, invoice.customer_city),
        "phone": customer.phone,
        "tax_id": invoice.customer_tax_id,
    }


def quote_printable(organization: Organization, quote_id: int) -> documents.Printable:
    quote = selectors.quote_of(organization, quote_id)
    context: dict[str, Any] = {
        "number": quote.number,
        "seller": _seller_of(organization),
        "quote": quote,
        "doc_date": quote.quoted_on,
        "party": _customer_party(quote.customer),
        "lines": [
            {
                "product_name": line.product.name,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "discount_rate": line.discount_rate,
                "amount": line.amount,
            }
            for line in quote.lines.all()
        ],
        # A draft, refused or expired quote says so on the page; a sent or accepted one is clean.
        "status_label": ""
        if quote.current_status in {QuoteStatus.SENT, QuoteStatus.ACCEPTED}  # type: ignore[attr-defined]
        else str(QuoteStatus(quote.current_status).label),  # type: ignore[attr-defined]
    }
    return documents.Printable(
        template="sales/pdf/quote.html",
        context=context,
        version=quote.updated_at.isoformat(),
        filename=_file_name("devis", quote.number),
        title=f"Devis {quote.number}".strip(),
        email_to=quote.customer.email,
    )


def invoice_printable(organization: Organization, invoice_id: int) -> documents.Printable:
    invoice = selectors.invoice_of(organization, invoice_id)
    if invoice.status == InvoiceStatus.DRAFT:
        # A draft has no number and may still change: only an issued invoice is a document.
        raise ValidationError(_("Une facture brouillon n'a pas de PDF : émettez-la d'abord."))
    lines = list(invoice.lines.select_related("product__base_unit", "sale_line__sale"))
    several = invoice.sales.count() > 1
    # "Total H.T avant remise" and "Total remise" without VAT, like the line amounts. With prices including
    # VAT, each line's discount is brought down to its share without VAT.
    discount_excl_tax = sum(
        (
            (line.discount_amount * line.amount_excl_tax / line.amount).quantize(Decimal("0.001"), ROUND_HALF_UP)
            if line.amount
            else Decimal("0.000")
            for line in lines
        ),
        Decimal("0.000"),
    )
    context: dict[str, Any] = {
        "several_sales": several,
        "number": invoice.number,
        "seller": {
            "name": invoice.seller_name,
            "address": invoice.seller_address,
            "phone": invoice.seller_phone,
            "tax_id": invoice.seller_tax_id,
            "trade_register": invoice.seller_trade_register,
        },
        "invoice": invoice,
        "doc_date": invoice.issued_on,
        "party": _invoiced_party(invoice),
        "sale_numbers": ", ".join(sale.number for sale in invoice.sales.all()),
        "lines": lines,
        "total_before_discount": invoice.total_excl_tax + discount_excl_tax,
        "discount_excl_tax": discount_excl_tax,
        "filler_mm": max(0, INVOICE_LINES_HEIGHT_MM - INVOICE_LINE_HEIGHT_MM * len(lines)),
        "vat_lines": list(invoice.vat_lines.all()) if invoice.apply_vat else [],
        "cancelled": invoice.status == InvoiceStatus.CANCELLED,
    }
    return documents.Printable(
        template="sales/pdf/invoice.html",
        context=context,
        version=invoice.updated_at.isoformat(),
        filename=_file_name("facture", invoice.number),
        title=f"Facture {invoice.number}".strip(),
        email_to=invoice.customer.email,
    )


def credit_note_printable(organization: Organization, credit_note_id: int) -> documents.Printable:
    note = selectors.credit_notes_of(organization).get(pk=credit_note_id)
    invoice = note.invoice
    context: dict[str, Any] = {
        "number": note.number,
        "seller": {
            "name": invoice.seller_name,
            "address": invoice.seller_address,
            "phone": invoice.seller_phone,
            "tax_id": invoice.seller_tax_id,
            "trade_register": invoice.seller_trade_register,
        },
        "note": note,
        "invoice": invoice,
        "doc_date": note.issued_on,
        "party": _invoiced_party(invoice),
        "lines": list(note.lines.all()),
        "kind_label": str(CreditNoteKind(note.kind).label),
        "stock_label": "" if note.stock == CreditNoteStock.NONE else str(CreditNoteStock(note.stock).label),
    }
    return documents.Printable(
        template="sales/pdf/credit_note.html",
        context=context,
        version=note.updated_at.isoformat(),
        filename=_file_name("avoir", note.number),
        title=f"Avoir {note.number}".strip(),
        email_to=note.invoice.customer.email,
    )


def receipt_printable(organization: Organization, payment_id: int) -> documents.Printable:
    payment = customer_payment_of(organization, payment_id)
    allocations = list(payment.allocations.all())
    allocated = sum((row.amount for row in allocations), Decimal("0.000"))
    rows = []
    for row in allocations:
        invoice = selectors.live_invoice_of(row.sale)
        rows.append(
            {"sale_number": row.sale.number, "invoice_number": invoice.number if invoice else "", "amount": row.amount}
        )
    context: dict[str, Any] = {
        "number": payment.number,
        "seller": _seller_of(organization),
        "payment": payment,
        "doc_date": payment.received_on,
        "party": _customer_party(payment.customer),
        "method_label": str(CustomerPaymentMethod(payment.method).label),
        "lines": [
            {
                "method_label": str(CustomerPaymentMethod(line.method).label),
                "number": line.instrument.number if line.instrument else line.reference,
                "bank": line.instrument.bank.code if line.instrument and line.instrument.bank else "",
                "due_on": line.instrument.due_on if line.instrument else None,
                "amount": line.amount,
            }
            for line in payment.lines.all()
        ],
        "allocations": rows,
        "unallocated": Decimal("0.000") if payment.voided_at else payment.amount - allocated,
    }
    return documents.Printable(
        template="sales/pdf/receipt.html",
        context=context,
        # Allocating money to sales later does not touch the payment row itself.
        version=f"{payment.updated_at.isoformat()}|{allocated}",
        filename=_file_name("recu", payment.number),
        title=f"Reçu de règlement {payment.number}".strip(),
        email_to=payment.customer.email,
    )


def _removed_at_delivery(sale: Sale) -> list[dict[str, Any]]:
    """The products the BL of a load had and the driver did not deliver at all (D-178): from its delivery version."""
    revision = sale.revisions.filter(kind=SaleRevisionKind.DELIVERED).order_by("-id").first()
    if revision is None:
        return []
    kept = {line.product_id for line in sale.lines.all()}
    return [
        {"name": row["name"], "ordered": Decimal(row["ordered"]), "unit_price": Decimal(row["unit_price"])}
        for row in revision.lines
        if row["product"] not in kept
    ]


def delivery_note_printable(organization: Organization, sale_id: int) -> documents.Printable:
    """The BL of a validated sale (D-095): what left, at what price, and what the customer owes for it."""
    sale = selectors.sale_of(organization, sale_id)
    # The BL of a truck load is validated at the load, with its number (D-178): it prints as the real BL to take on
    # the road, with a column for the kg delivered. One made before that (D-160) still prints as provisional.
    issued = sale.issued_at is not None
    provisional = (
        not issued and sale.confirmed_at is None and sale.transfer_id is not None and sale.status == SaleStatus.DRAFT
    )
    if sale.confirmed_at is None and not provisional and not issued:
        # A draft (or a draft given up) has no BL number and moves nothing: validating the sale is what makes the BL.
        raise ValidationError(_("Une vente en brouillon n'a pas de bon de livraison : validez-la d'abord."))
    lines = list(sale.lines.all())
    sold_on = timezone.localtime(sale.sold_at).date()
    context: dict[str, Any] = {
        "number": sale.number,
        "seller": _seller_of(organization),
        "sale": sale,
        "sold_on": sold_on,
        "doc_date": sold_on,
        "party": _customer_party(sale.customer),
        "location": sale.location,
        "lines": lines,
        "has_discount": any(line.discount_rate for line in lines),
        "total_kg": sum((line.quantity for line in lines), Decimal("0.000")),
        "cancelled": sale.status == SaleStatus.CANCELLED,
        "provisional": provisional,
        "to_deliver": sale.delivery_status == DeliveryStatus.TO_DELIVER,
        "delivered": sale.delivery_status in (DeliveryStatus.DELIVERED, DeliveryStatus.PARTIAL),
        "not_delivered": sale.delivery_status == DeliveryStatus.CANCELLED,
        "version": sale.version if sale.delivery_status else None,
        "delivery_label": str(DeliveryStatus(sale.delivery_status).label) if sale.delivery_status else "",
        "removed": _removed_at_delivery(sale),
        "deliver_to": sale.delivery_address or _address(sale.customer.address, sale.customer.city),
        "boxes": [(str(box_services.BoxType(line.box_type).label), line.count) for line in sale.box_lines.all()],
    }
    return documents.Printable(
        template="sales/pdf/delivery_note.html",
        context=context,
        version=sale.updated_at.isoformat(),
        filename=_file_name("bl", sale.number),
        title=f"Bon de livraison {sale.number}".strip(),
        email_to=sale.customer.email,
    )


def register_printables() -> None:
    documents.register(documents.DocumentKind.DELIVERY_NOTE, delivery_note_printable)
    documents.register(documents.DocumentKind.QUOTE, quote_printable)
    documents.register(documents.DocumentKind.INVOICE, invoice_printable)
    documents.register(documents.DocumentKind.CREDIT_NOTE, credit_note_printable)
    documents.register(documents.DocumentKind.RECEIPT, receipt_printable)
