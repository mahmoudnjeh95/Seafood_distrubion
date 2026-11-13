"""One search box for the office (D-330): customers, suppliers, products, lots, BL and invoices at once.

Each kind reuses its own list's search (`search=`), so a hit here is a row the person finds on that list too. Only the
kinds whose section the person may read are searched (`apps.core.access`); the view passes them in.
"""

from dataclasses import dataclass

from apps.catalog import selectors as catalog
from apps.core.models import Organization
from apps.inventory import selectors as inventory
from apps.partners import selectors as partners
from apps.sales import selectors as sales

# At most this many hits of each kind: the box points to a record, the lists do the browsing.
PER_KIND = 5
# Shorter queries match almost everything and only cost queries.
MIN_LENGTH = 2

# The kind of a hit and the access section that must be readable to see it.
KIND_SECTIONS: dict[str, str] = {
    "customer": "customers",
    "supplier": "suppliers",
    "product": "products",
    "lot": "stock",
    "sale": "sales",
    "invoice": "invoices",
}


@dataclass(frozen=True)
class Hit:
    kind: str
    id: int
    # What the person reads first ("C-012 · Restaurant Le Golfe", "FA-2026-0042") and the line under it.
    label: str
    detail: str


def _joined(*parts: str) -> str:
    return " · ".join(part for part in parts if part)


def search(organization: Organization, query: str, *, kinds: set[str]) -> list[Hit]:
    """The hits for `query`, grouped by kind in a fixed order, at most `PER_KIND` of each; nothing below
    `MIN_LENGTH` characters."""
    query = query.strip()
    if len(query) < MIN_LENGTH:
        return []
    hits: list[Hit] = []
    if "customer" in kinds:
        for customer in partners.customers_of(organization, search=query, status="all")[:PER_KIND]:
            hits.append(Hit("customer", customer.pk, _joined(customer.reference, customer.name), customer.phone))
    if "supplier" in kinds:
        for supplier in partners.suppliers_of(organization, search=query, status="all")[:PER_KIND]:
            hits.append(Hit("supplier", supplier.pk, _joined(supplier.reference, supplier.name), supplier.phone))
    if "product" in kinds:
        for product in catalog.products_of(organization, search=query, status="all")[:PER_KIND]:
            hits.append(Hit("product", product.pk, _joined(product.reference, product.name), ""))
    if "lot" in kinds:
        for batch in inventory.batches_of(organization, search=query)[:PER_KIND]:
            hits.append(
                Hit(
                    "lot",
                    batch.pk,
                    _joined(batch.number, batch.product.name),
                    _joined(batch.supplier.name, batch.received_on.strftime("%d/%m/%Y")),
                )
            )
    if "sale" in kinds:
        for sale in sales.sales_of(organization, search=query)[:PER_KIND]:
            hits.append(Hit("sale", sale.pk, sale.number, _joined(sale.customer.name, str(sale.total))))
    if "invoice" in kinds:
        for invoice in sales.invoices_of(organization, search=query)[:PER_KIND]:
            hits.append(
                Hit("invoice", invoice.pk, invoice.number or invoice.draft_number, _joined(invoice.customer.name))
            )
    return hits
