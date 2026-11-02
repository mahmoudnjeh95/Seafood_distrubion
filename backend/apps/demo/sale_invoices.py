"""Demo invoices (P2-T05): the seller printed on invoices (the sample invoice's invented identity), the truck
sale to Restaurant Le Corail invoiced and issued (FA-<year>-0001), and Café-Resto Sidi Mansour's sale with a
draft invoice waiting to be issued.

Running the seed again creates nothing: the settings are saved only while the seller has no tax ID, and a sale
that already has an invoice is left alone. A sale that cannot be invoiced (cancelled by hand on staging) is
skipped rather than failing the deploy.
"""

from django.core.exceptions import ValidationError

from apps.core.models import Organization, User
from apps.sales import selectors, services

# Invented, from docs/spec/sample/sample-invoice.md.
SELLER: services.FinanceSettingsFields = {
    "legal_name": "Frutti Del Mare",
    "address": "Sakiet Ezzit, Sfax, Tunisie",
    "phone": "+216 74 000 100",
    "tax_id": "0000000A/A/M/000",
    "trade_register": "0000000A",
}
# customer reference → issue at once
INVOICED: list[tuple[str, bool]] = [("C-001", True), ("C-004", False)]


def seed_invoices(*, organization: Organization, actor: User | None) -> int:
    """Fill in the seller and create the demo invoices that do not exist yet. Returns how many were created."""
    in_force = selectors.finance_settings_on(organization)
    if in_force is None or not in_force.tax_id:
        services.save_finance_settings(organization=organization, actor=actor, **SELLER)
    created = 0
    for reference, issue in INVOICED:
        sale = (
            selectors.sales_of(organization, status="confirmed")
            .filter(customer__reference=reference)
            .order_by("id")
            .first()
        )
        if sale is None or selectors.live_invoice_of(sale) is not None:
            continue
        try:
            services.create_invoice(apply_vat=True, sale=sale, actor=actor, issue=issue)
        except ValidationError:
            continue
        created += 1
    return created
