import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.core.models import Organization
from apps.sales import selectors as sales

pytestmark = pytest.mark.django_db


@pytest.mark.blank_seller
def test_the_seed_gives_the_seller_an_issued_invoice_and_a_draft(settings):
    settings.DEBUG = True

    call_command("seed_dev")
    call_command("seed_dev")  # running it again creates nothing

    organization = Organization.objects.get()
    version = sales.finance_settings_on(organization)
    assert version is not None
    assert (version.legal_name, version.tax_id) == ("Frutti Del Mare", "0000000A/A/M/000")
    invoices = {invoice.customer.reference: invoice for invoice in sales.invoices_of(organization)}
    assert set(invoices) == {"C-001", "C-004"}
    issued = invoices["C-001"]
    assert issued.status == "issued"
    assert issued.number == f"FA-{timezone.localdate().year}-0001"
    assert issued.vat_total > 0
    assert issued.fiscal_stamp > 0
    assert invoices["C-004"].status == "draft"
