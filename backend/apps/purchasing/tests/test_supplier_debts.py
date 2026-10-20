"""Paying suppliers (P3-T12c, D-159): what is owed and when, cheques to be cashed, a delivery owed at once, and the
photo of the supplier's paper on a purchase at the port."""

import datetime as dt
import io
import shutil
import tempfile
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import selectors, services
from apps.purchasing.models import FieldPurchase, SupplierInvoice, SupplierInvoiceStatus

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate


@pytest.fixture(autouse=True)
def media_root():
    folder = tempfile.mkdtemp()
    with override_settings(MEDIA_ROOT=folder):
        yield folder
    shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def room(organization):
    return StockLocationFactory.create(organization=organization)


@pytest.fixture
def product(organization):
    return ProductFactory.create(organization=organization)


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def owed(organization, supplier, room, product, *, amount: str, received_on: dt.date, terms="days", days=30):
    """A delivery owed at once: `amount` DT (1 kg at that price)."""
    return services.receive_and_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        location=room,
        received_on=received_on,
        lines=[{"product": product, "invoiced_quantity": "1", "accepted_quantity": "1", "unit_cost": amount}],
        terms=terms,
        due_days=days,
    )


# ---- A delivery owed at once ----


def test_a_receipt_invoiced_at_once_is_owed_from_the_reception(organization, room, product):
    supplier = SupplierFactory.create(organization=organization)

    receipt = owed(organization, supplier, room, product, amount="500", received_on=TODAY(), terms="month_end", days=10)

    invoice = SupplierInvoice.objects.get()
    assert invoice.status == SupplierInvoiceStatus.POSTED
    assert invoice.total == Decimal("500.000")
    assert invoice.due_date == services.due_date_of(TODAY(), "month_end", 10)
    assert list(invoice.receipt_links.values_list("receipt", flat=True)) == [receipt.pk]
    assert selectors.supplier_balance(organization, supplier.pk).balance == Decimal("500.000")


def test_the_receipt_form_sends_the_deal(organization, room, product):
    supplier = SupplierFactory.create(organization=organization)
    manager = client_for(MembershipFactory.create(organization=organization, role=Role.MANAGER))
    payload: dict[str, Any] = {
        "supplier": supplier.pk,
        "location": room.pk,
        "received_on": TODAY().isoformat(),
        "lines": [{"product": product.pk, "invoiced_quantity": "10", "accepted_quantity": "10", "unit_cost": "12"}],
        "invoice_now": True,
        "terms": "cash",
    }

    created = manager.post(reverse("receipt-list"), payload, format="json")

    assert created.status_code == 201, created.json()
    assert created.json()["invoice"]["status"] == "posted"
    assert SupplierInvoice.objects.get().due_date == TODAY()
    # Without it, the receipt waits for the supplier's invoice as before.
    payload["invoice_now"] = False
    assert manager.post(reverse("receipt-list"), payload, format="json").json()["invoice"] is None


def test_a_deal_at_n_days_needs_the_days(organization, room, product):
    supplier = SupplierFactory.create(organization=organization)
    with pytest.raises(ValidationError) as caught:
        owed(organization, supplier, room, product, amount="10", received_on=TODAY(), terms="days", days=0)
    assert "due_days" in caught.value.message_dict


# ---- What is owed, and when ----


def test_debts_per_supplier_with_overdue_due_soon_and_advances(organization, room, product):
    port = SupplierFactory.create(organization=organization, name="Mareyeur Port de Sfax")
    fisher = SupplierFactory.create(organization=organization, name="Pêcheur Hamdi")
    owed(organization, port, room, product, amount="300", received_on=TODAY() - dt.timedelta(days=40))  # overdue
    owed(organization, port, room, product, amount="200", received_on=TODAY() - dt.timedelta(days=25))  # due soon
    owed(organization, port, room, product, amount="100", received_on=TODAY())  # later
    owed(organization, fisher, room, product, amount="50", received_on=TODAY(), terms="cash")
    services.record_payment(
        organization=organization,
        actor=None,
        supplier=fisher,
        paid_on=TODAY(),
        amount="80",
        method="cash",
        allocations=[{"invoice": SupplierInvoice.objects.get(supplier=fisher), "amount": "50"}],
    )

    debts = selectors.supplier_debts(organization)

    assert [row.name for row in debts.rows] == ["Mareyeur Port de Sfax", "Pêcheur Hamdi"]
    first, second = debts.rows
    assert (first.outstanding, first.overdue, first.due_soon, first.open_invoices) == (
        Decimal("600.000"),
        Decimal("300.000"),
        Decimal("200.000"),
        3,
    )
    assert first.next_due == TODAY() - dt.timedelta(days=10)
    assert (second.outstanding, second.advances) == (Decimal("0.000"), Decimal("30.000"))
    assert debts.total_outstanding == Decimal("600.000")
    assert debts.total_advances == Decimal("30.000")


def test_cheques_and_traites_to_cash_soonest_first(organization):
    supplier = SupplierFactory.create(organization=organization, name="Mareyeur Port de Sfax")
    for days, method, amount in ((20, "cheque", "400"), (3, "bill", "250"), (-30, "cheque", "99"), (5, "cash", "10")):
        services.record_payment(
            organization=organization,
            actor=None,
            supplier=supplier,
            paid_on=TODAY() - dt.timedelta(days=max(-days, 0)) if days < 0 else TODAY(),
            amount=amount,
            method=method,
            reference=f"N-{amount}",
            cash_on=TODAY() + dt.timedelta(days=days) if days >= 0 else TODAY() - dt.timedelta(days=30),
        )

    debts = selectors.supplier_debts(organization)

    assert [(c.reference, c.cash_on) for c in debts.cheques] == [
        ("N-250", TODAY() + dt.timedelta(days=3)),
        ("N-400", TODAY() + dt.timedelta(days=20)),
    ]
    assert debts.cheques_total == Decimal("650.000")


def test_the_office_reads_the_debts_and_a_driver_cannot(organization):
    accountant = client_for(MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT))
    assert accountant.get(reverse("supplier-debts")).status_code == 200
    driver = client_for(MembershipFactory.create(organization=organization, role=Role.DRIVER))
    assert driver.get(reverse("supplier-debts")).status_code == 403


def test_a_payment_keeps_its_cashing_day_through_the_api(organization):
    supplier = SupplierFactory.create(organization=organization)
    manager = client_for(MembershipFactory.create(organization=organization, role=Role.MANAGER))
    cash_on = TODAY() + dt.timedelta(days=15)
    paid = manager.post(
        reverse("supplier-payment-list"),
        {
            "supplier": supplier.pk,
            "paid_on": TODAY().isoformat(),
            "amount": "120",
            "method": "cheque",
            "reference": "CH-77",
            "cash_on": cash_on.isoformat(),
        },
        format="json",
    )
    assert paid.status_code == 201, paid.json()
    assert paid.json()["cash_on"] == cash_on.isoformat()


# ---- The photo of the supplier's paper ----


def a_photo() -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), "blue").save(buffer, format="JPEG")
    return SimpleUploadedFile("papier.jpg", buffer.getvalue(), content_type="image/jpeg")


def test_the_driver_joins_the_paper_and_the_office_sees_it(organization, product):
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER, can_buy=True)
    supplier = SupplierFactory.create(organization=organization)
    phone = client_for(driver)
    sent = phone.post(
        reverse("my-field-purchases"),
        {
            "supplier": supplier.pk,
            "terms": "cash",
            "lines": [{"product": product.pk, "declared_quantity": "5", "unit_cost": "10"}],
            "client_uuid": str(uuid4()),
        },
        format="json",
    ).json()
    assert sent["has_paper"] is False

    joined = phone.put(reverse("my-field-purchase-paper", args=[sent["id"]]), {"paper": a_photo()}, format="multipart")

    assert joined.status_code == 200, joined.json()
    assert joined.json()["has_paper"] is True
    office = client_for(MembershipFactory.create(organization=organization, role=Role.MANAGER))
    detail = office.get(reverse("field-purchase-detail", args=[sent["id"]])).json()
    assert detail["paper_url"] is not None
    image = office.get(detail["paper_url"])
    assert image.status_code == 200
    assert image["Content-Type"] == "image/webp"


def test_a_paper_that_is_not_a_photo_is_refused(organization, product):
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER, can_buy=True)
    purchase = services.submit_field_purchase(
        organization=organization,
        buyer=driver.user,
        fields={
            "supplier": SupplierFactory.create(organization=organization),
            "bought_on": TODAY(),
            "terms": "cash",
            "lines": [{"product": product, "declared_quantity": "5", "unit_cost": "10"}],
        },
    )
    text = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
    answer = client_for(driver).put(
        reverse("my-field-purchase-paper", args=[purchase.pk]), {"paper": text}, format="multipart"
    )
    assert answer.status_code == 400
    assert not FieldPurchase.objects.get().paper


# ---- Given now, at the reception (D-192) ----


def test_a_receipt_owed_at_once_records_what_is_given_now(organization, room, product):
    supplier = SupplierFactory.create(organization=organization)
    manager = client_for(MembershipFactory.create(organization=organization, role=Role.MANAGER))
    payload: dict[str, Any] = {
        "supplier": supplier.pk,
        "location": room.pk,
        "received_on": TODAY().isoformat(),
        "lines": [{"product": product.pk, "invoiced_quantity": "10", "accepted_quantity": "10", "unit_cost": "12"}],
        "invoice_now": True,
        "terms": "days",
        "due_days": 30,
        "payments": [
            {"method": "cash", "amount": "50"},
            {"method": "cheque", "amount": "20", "reference": "CH-1", "cash_on": TODAY().isoformat()},
        ],
    }

    created = manager.post(reverse("receipt-list"), payload, format="json")

    assert created.status_code == 201, created.json()
    assert SupplierInvoice.objects.get().total == Decimal("120.000")
    assert selectors.supplier_balance(organization, supplier.pk).balance == Decimal("50.000")


def test_more_given_than_the_receipt_is_refused_and_nothing_is_kept(organization, room, product):
    supplier = SupplierFactory.create(organization=organization)
    with pytest.raises(ValidationError) as caught:
        services.receive_and_invoice(
            organization=organization,
            actor=None,
            supplier=supplier,
            location=room,
            received_on=TODAY(),
            lines=[{"product": product, "invoiced_quantity": "1", "accepted_quantity": "1", "unit_cost": "100"}],
            terms="cash",
            payments=[{"method": "cash", "amount": "80"}, {"method": "cash", "amount": "30"}],
        )
    assert set(caught.value.message_dict) == {"payments.1.amount"}
    assert not SupplierInvoice.objects.exists()


def test_a_payment_without_the_invoice_is_refused(organization, room, product):
    supplier = SupplierFactory.create(organization=organization)
    manager = client_for(MembershipFactory.create(organization=organization, role=Role.MANAGER))
    payload: dict[str, Any] = {
        "supplier": supplier.pk,
        "location": room.pk,
        "received_on": TODAY().isoformat(),
        "lines": [{"product": product.pk, "invoiced_quantity": "10", "accepted_quantity": "10", "unit_cost": "12"}],
        "invoice_now": False,
        "payments": [{"method": "cash", "amount": "10"}],
    }

    refused = manager.post(reverse("receipt-list"), payload, format="json")

    assert refused.status_code == 400
    assert not SupplierInvoice.objects.exists()
