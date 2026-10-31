"""The PDF receipt of a supplier règlement (P9-T03c, D-215)."""

import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory
from apps.documents import services as documents
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import services
from apps.treasury import selectors as treasury

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate


def test_the_receipt_lists_the_means_the_invoices_and_the_advance():
    manager = MembershipFactory.create(role=Role.MANAGER)
    organization = manager.organization
    supplier = SupplierFactory.create(organization=organization, name="Mareyeur Port de Sfax", reference="F-0012")
    invoice = services.create_opening_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        amount="900",
        invoice_date=TODAY() - dt.timedelta(days=5),
        due_date=TODAY() + dt.timedelta(days=25),
    )
    payment = services.record_payment(
        organization=organization,
        actor=manager.user,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[
            {"method": "cash", "amount": "200"},
            {
                "method": "bill",
                "amount": "800",
                "number": "TR-41",
                "bank": treasury.banks_of(organization).get(code="BIAT"),
                "due_on": TODAY() + dt.timedelta(days=60),
            },
        ],
        allocations=[{"invoice": invoice, "amount": "900"}],
    )

    html = documents.render_html(documents.printable(organization, "supplier_receipt", payment.pk))

    assert f"Paiement fournisseur N° {payment.number}" in html
    assert "<th>Date</th><th>Fournisseur</th>" in html
    assert "Mareyeur Port de Sfax" in html
    assert "F-0012" in html
    assert "TR-41" in html
    assert "BIAT" in html
    assert invoice.number in html
    assert "Non affecté (avance chez le fournisseur)" in html

    services.void_payment(payment=payment, actor=manager.user, reason="erreur")
    voided = documents.render_html(documents.printable(organization, "supplier_receipt", payment.pk))
    assert "ANNULÉ" in voided
    assert "Non affecté" not in voided

    api = APIClient()
    api.force_authenticate(manager.user)
    draft = api.get(reverse("document-email", args=["supplier_receipt", payment.pk]))
    assert draft.status_code == 200, draft.json()
    assert draft.json()["subject"].startswith(f"Paiement {payment.number}")
