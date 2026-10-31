import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import selectors, services
from apps.purchasing.models import SupplierInvoice, SupplierInvoiceStatus, SupplierPayment

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year

TODAY = timezone.localdate


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


@pytest.fixture
def supplier(organization):
    return SupplierFactory.create(organization=organization, name="Mareyeur Port de Sfax")


@pytest.fixture
def receive(organization, supplier):
    """Record a receipt of one product: `invoiced` kg at `cost` DT/kg (60 kg accepted, like the demo)."""
    room = StockLocationFactory.create(organization=organization)
    product = ProductFactory.create(organization=organization)

    def make(invoiced="62", cost="20.250", *, of=None, received_on=None):
        return services.create_receipt(
            organization=organization,
            actor=None,
            supplier=of or supplier,
            location=room,
            received_on=received_on or TODAY(),
            lines=[{"product": product, "invoiced_quantity": invoiced, "accepted_quantity": "60", "unit_cost": cost}],
        )

    return make


def invoice_for(organization, actor, supplier, receipts, **fields):
    values: dict[str, Any] = {
        "invoice_date": TODAY(),
        "due_date": TODAY() + dt.timedelta(days=30),
        "supplier_reference": "FA-2026-118",
    }
    values.update(fields)
    return services.create_invoice(
        organization=organization, actor=actor, supplier=supplier, receipts=receipts, **values
    )


def pay(organization, actor, supplier, amount, allocations=(), **fields):
    values: dict[str, Any] = {"paid_on": TODAY(), "method": "cheque", "reference": "CH-0042"}
    values.update(fields)
    return services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        amount=amount,
        allocations=[{"invoice": invoice, "amount": value} for invoice, value in allocations],
        **values,
    )


def refreshed(invoice: SupplierInvoice) -> SupplierInvoice:
    return SupplierInvoice.objects.get(pk=invoice.pk)


# ---- invoices ----


def test_an_invoice_charges_the_invoiced_amount_of_its_receipts(organization, actor, supplier, receive):
    first = receive()  # 62 kg × 20.250 = 1255.500 invoiced (60 kg accepted: not what is charged)
    second = receive("10.5", "12.345")  # 10.5 × 12.345 = 129.6225 → 129.623

    invoice = invoice_for(organization, actor, supplier, [first, second])

    assert (invoice.number, invoice.status, invoice.total) == ("FF-0001", "draft", Decimal("1385.123"))
    assert [(link.receipt, link.amount) for link in invoice.receipt_links.order_by("receipt_id")] == [
        (first, Decimal("1255.500")),
        (second, Decimal("129.623")),
    ]
    log = AuditLog.objects.get(action="supplier_invoice.created")
    assert log.after is not None
    assert log.after["receipts"] == {"BR-0001": "1255.500", "BR-0002": "129.623"}
    assert selectors.receipts_of(organization, uninvoiced=True).count() == 0


def test_every_invoice_problem_is_reported_at_once(organization, actor, supplier, receive):
    other_supplier = SupplierFactory.create(organization=organization)
    theirs = receive(of=other_supplier)

    with pytest.raises(ValidationError) as caught:
        invoice_for(
            organization,
            actor,
            supplier,
            [theirs],
            invoice_date=TODAY() + dt.timedelta(days=1),
            due_date=TODAY(),
        )

    assert set(caught.value.message_dict) == {"receipts", "invoice_date", "due_date"}
    assert "BR-0001 est d'un autre fournisseur" in caught.value.message_dict["receipts"][0]
    with pytest.raises(ValidationError) as empty:
        invoice_for(organization, actor, supplier, [])
    assert set(empty.value.message_dict) == {"receipts"}
    assert not SupplierInvoice.objects.exists()


def test_a_receipt_goes_on_one_invoice_only(organization, actor, supplier, receive):
    receipt = receive()
    first = invoice_for(organization, actor, supplier, [receipt])

    with pytest.raises(ValidationError) as caught:
        invoice_for(organization, actor, supplier, [receipt])

    assert caught.value.message_dict["receipts"] == ["La réception BR-0001 est déjà sur la facture FF-0001."]
    # Deleting the draft frees the receipt.
    services.delete_invoice(invoice=first, actor=actor)
    assert invoice_for(organization, actor, supplier, [receipt]).number == "FF-0002"
    assert AuditLog.objects.filter(action="supplier_invoice.deleted").count() == 1


def test_a_draft_changes_until_it_is_posted_then_never(organization, actor, supplier, receive):
    first, second = receive(), receive("10", "10")
    invoice = invoice_for(organization, actor, supplier, [first])

    invoice = services.update_invoice(
        invoice=invoice,
        actor=actor,
        receipts=[first, second],
        invoice_date=TODAY() - dt.timedelta(days=1),
        due_date=TODAY() + dt.timedelta(days=7),
        supplier_reference=" FA-119 ",
    )
    assert (invoice.total, invoice.supplier_reference) == (Decimal("1355.500"), "FA-119")

    services.post_invoice(invoice=invoice, actor=actor)
    posted = refreshed(invoice)
    assert (posted.status, posted.posted_by, posted.posted_at is not None) == ("posted", actor, True)
    assert AuditLog.objects.filter(action="supplier_invoice.posted").count() == 1

    with pytest.raises(ValidationError, match="ne se modifie plus"):
        services.update_invoice(invoice=posted, actor=actor, receipts=[first], invoice_date=TODAY(), due_date=TODAY())
    with pytest.raises(ValidationError):
        services.delete_invoice(invoice=posted, actor=actor)
    with pytest.raises(ValidationError):
        services.post_invoice(invoice=posted, actor=actor)


def test_an_invoice_can_be_posted_when_created_but_not_for_nothing(organization, actor, supplier, receive):
    assert invoice_for(organization, actor, supplier, [receive()], post=True).status == "posted"

    with pytest.raises(ValidationError, match="montant de la facture est nul"):
        invoice_for(organization, actor, supplier, [receive(cost="0")], post=True)
    # The refused posting rolled the whole invoice back.
    assert SupplierInvoice.objects.count() == 1


def test_invoices_are_numbered_per_organization(organization, actor, supplier, receive):
    invoice_for(organization, actor, supplier, [receive()])
    other = OrganizationFactory.create()
    other_supplier = SupplierFactory.create(organization=other)
    other_receipt = services.create_receipt(
        organization=other,
        actor=None,
        supplier=other_supplier,
        location=StockLocationFactory.create(organization=other),
        received_on=TODAY(),
        lines=[
            {
                "product": ProductFactory.create(organization=other),
                "invoiced_quantity": "1",
                "accepted_quantity": "1",
                "unit_cost": "1",
            }
        ],
    )

    assert invoice_for(other, actor, other_supplier, [other_receipt]).number == "FF-0001"


# ---- payments ----


def test_payments_settle_invoices_and_move_their_status(organization, actor, supplier, receive):
    invoice = invoice_for(organization, actor, supplier, [receive()], post=True)  # 1255.500

    first = pay(organization, actor, supplier, "500", [(invoice, "500")])
    assert (first.number, refreshed(invoice).status) == (f"RF-{YEAR}-0001", "partly_paid")

    pay(organization, actor, supplier, "755.500", [(invoice, "755.5")], method="cash", reference="")
    assert refreshed(invoice).status == "paid"
    listed = selectors.invoice_of(organization, invoice.pk)
    assert (getattr(listed, "paid_amount"), getattr(listed, "outstanding")) == (  # noqa: B009
        Decimal("1255.500"),
        Decimal("0.000"),
    )
    log = AuditLog.objects.filter(action="supplier_payment.recorded").latest("id")
    assert log.after is not None
    assert log.after["allocations"] == [{"invoice": "FF-0001", "amount": "755.500"}]


def test_every_payment_problem_is_reported_at_once(organization, actor, supplier, receive):
    posted = invoice_for(organization, actor, supplier, [receive()], post=True)  # 1255.500
    draft = invoice_for(organization, actor, supplier, [receive()])
    theirs_supplier = SupplierFactory.create(organization=organization)
    theirs = invoice_for(organization, actor, theirs_supplier, [receive(of=theirs_supplier)], post=True)

    with pytest.raises(ValidationError) as caught:
        pay(
            organization,
            actor,
            supplier,
            "1300",
            [(posted, "1300"), (draft, "10"), (theirs, "10"), (posted, "1")],
            paid_on=TODAY() + dt.timedelta(days=1),
            method="bitcoin",
        )

    assert set(caught.value.message_dict) == {
        "paid_on",
        "method",
        "allocations.0.amount",
        "allocations.1.invoice",
        "allocations.2.invoice",
        "allocations.3.invoice",
    }
    assert "1 255,500" in caught.value.message_dict["allocations.0.amount"][0]
    assert not SupplierPayment.objects.exists()


def test_allocations_never_exceed_the_payment(organization, actor, supplier, receive):
    first = invoice_for(organization, actor, supplier, [receive()], post=True)
    second = invoice_for(organization, actor, supplier, [receive()], post=True)

    with pytest.raises(ValidationError) as caught:
        pay(organization, actor, supplier, "1000", [(first, "600"), (second, "600")])
    assert set(caught.value.message_dict) == {"allocations"}

    for amount in ("0", "12,5", "-3", "1.0001"):
        with pytest.raises(ValidationError) as refused:
            pay(organization, actor, supplier, amount)
        assert set(refused.value.message_dict) == {"amount"}


def test_an_advance_is_allocated_later(organization, actor, supplier, receive):
    advance = pay(organization, actor, supplier, "2000")  # before any invoice
    first = invoice_for(organization, actor, supplier, [receive()], post=True)  # 1255.500
    second = invoice_for(organization, actor, supplier, [receive()], post=True)  # 1255.500

    services.allocate_payment(payment=advance, actor=actor, allocations=[{"invoice": first, "amount": "1255.500"}])
    with pytest.raises(ValidationError) as caught:
        services.allocate_payment(payment=advance, actor=actor, allocations=[{"invoice": second, "amount": "800"}])
    assert "744,500" in caught.value.message_dict["allocations"][0]
    services.allocate_payment(payment=advance, actor=actor, allocations=[{"invoice": second, "amount": "744.5"}])

    assert (refreshed(first).status, refreshed(second).status) == ("paid", "partly_paid")
    listed = selectors.payment_of(organization, advance.pk)
    assert getattr(listed, "unallocated_amount") == Decimal("0.000")  # noqa: B009
    assert AuditLog.objects.filter(action="supplier_payment.allocated").count() == 2


def test_the_supplier_balance_is_invoices_minus_payments(organization, actor, supplier, receive):
    late = invoice_for(
        organization,
        actor,
        supplier,
        [receive(received_on=TODAY() - dt.timedelta(days=40))],
        invoice_date=TODAY() - dt.timedelta(days=40),
        due_date=TODAY() - dt.timedelta(days=10),
        post=True,
    )  # 1255.500, overdue
    invoice_for(organization, actor, supplier, [receive("10", "10")], post=True)  # 100.000
    invoice_for(organization, actor, supplier, [receive("2", "10")])  # draft, 20.000: not owed yet
    receive("3", "10")  # not invoiced yet: 30.000
    pay(organization, actor, supplier, "300", [(late, "255.5")])  # 44.500 left as an advance
    # Another supplier's documents never count.
    elsewhere = SupplierFactory.create(organization=organization)
    invoice_for(organization, actor, elsewhere, [receive(of=elsewhere)], post=True)

    balance = selectors.supplier_balance(organization, supplier.pk)

    assert (balance.invoiced, balance.paid, balance.balance) == (
        Decimal("1355.500"),
        Decimal("300.000"),
        Decimal("1055.500"),
    )
    assert (balance.outstanding, balance.unallocated) == (Decimal("1100.000"), Decimal("44.500"))
    assert (balance.overdue, balance.overdue_invoices, balance.open_invoices) == (Decimal("1000.000"), 1, 2)
    assert (balance.draft_invoices, balance.draft_total) == (1, Decimal("20.000"))
    assert (balance.uninvoiced_receipts, balance.uninvoiced_total) == (1, Decimal("30.000"))
    assert [invoice.pk for invoice in selectors.invoices_of(organization, overdue=True)] == [late.pk]
    assert [invoice.due_date for invoice in selectors.open_invoices_of(organization, supplier_id=supplier.pk)] == [
        TODAY() - dt.timedelta(days=10),
        TODAY() + dt.timedelta(days=30),
    ]


# ---- API ----


def client_for(role, organization=None):
    membership = MembershipFactory.create(role=role, organization=organization or OrganizationFactory.create())
    client = APIClient()
    client.force_authenticate(membership.user)
    return client, membership


def api_receipt(client, supplier, room, product, invoiced="62", cost="20.250") -> dict[str, Any]:
    payload = {
        "supplier": supplier.pk,
        "location": room.pk,
        "received_on": TODAY().isoformat(),
        "lines": [{"product": product.pk, "invoiced_quantity": invoiced, "accepted_quantity": "60", "unit_cost": cost}],
    }
    response = client.post(reverse("receipt-list"), payload, format="json")
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


def test_the_owner_invoices_a_receipt_pays_it_and_reads_the_balance():
    client, owner = client_for(Role.OWNER)
    organization = owner.organization
    supplier = SupplierFactory.create(organization=organization)
    room = StockLocationFactory.create(organization=organization)
    product = ProductFactory.create(organization=organization)
    receipt = api_receipt(client, supplier, room, product)
    assert receipt["invoice"] is None
    uninvoiced = client.get(reverse("receipt-list"), {"uninvoiced": "true", "supplier": supplier.pk}).json()
    assert [row["id"] for row in uninvoiced["results"]] == [receipt["id"]]

    created = client.post(
        reverse("supplier-invoice-list"),
        {
            "supplier": supplier.pk,
            "receipts": [receipt["id"]],
            "invoice_date": TODAY().isoformat(),
            "due_date": (TODAY() + dt.timedelta(days=30)).isoformat(),
            "supplier_reference": "FA-118",
        },
        format="json",
    )
    assert created.status_code == 201
    invoice = created.json()
    assert (invoice["number"], invoice["status"], invoice["total"], invoice["outstanding"]) == (
        "FF-0001",
        "draft",
        "1255.500",
        "1255.500",
    )
    assert invoice["receipts"] == [
        {
            "receipt": {
                "id": receipt["id"],
                "number": "BR-0001",
                "received_on": TODAY().isoformat(),
                "supplier_reference": "",
            },
            "amount": "1255.500",
        }
    ]
    on_receipt = client.get(reverse("receipt-detail", args=[receipt["id"]])).json()["invoice"]
    assert on_receipt == {"id": invoice["id"], "number": "FF-0001", "status": "draft"}

    posted = client.post(reverse("supplier-invoice-post", args=[invoice["id"]]))
    assert (posted.status_code, posted.json()["status"]) == (200, "posted")
    edit = client.put(
        reverse("supplier-invoice-detail", args=[invoice["id"]]),
        {"receipts": [receipt["id"]], "invoice_date": TODAY().isoformat(), "due_date": TODAY().isoformat()},
        format="json",
    )
    assert edit.status_code == 400
    assert client.delete(reverse("supplier-invoice-detail", args=[invoice["id"]])).status_code == 400

    paid = client.post(
        reverse("supplier-payment-list"),
        {
            "supplier": supplier.pk,
            "paid_on": TODAY().isoformat(),
            "amount": "1300.000",
            "method": "transfer",
            "reference": "VIR-77",
            "allocations": [{"invoice": invoice["id"], "amount": "1255.500"}],
        },
        format="json",
    )
    assert paid.status_code == 201
    payment = paid.json()
    assert (payment["number"], payment["allocated_amount"], payment["unallocated_amount"]) == (
        f"RF-{YEAR}-0001",
        "1255.500",
        "44.500",
    )
    assert payment["allocations"][0]["invoice"]["number"] == "FF-0001"
    detail = client.get(reverse("supplier-invoice-detail", args=[invoice["id"]])).json()
    assert (detail["status"], detail["paid_amount"], detail["payments"][0]["payment"]["number"]) == (
        "paid",
        "1255.500",
        f"RF-{YEAR}-0001",
    )

    balance = client.get(reverse("supplier-balance", args=[supplier.pk])).json()
    assert (balance["invoiced"], balance["paid"], balance["balance"], balance["unallocated"]) == (
        "1255.500",
        "1300.000",
        "-44.500",
        "44.500",
    )
    advances = client.get(reverse("supplier-payment-list"), {"unallocated": "true"}).json()
    assert advances["count"] == 1
    assert client.get(reverse("supplier-invoice-list"), {"status": "paid"}).json()["count"] == 1
    assert client.get(reverse("supplier-invoice-list"), {"status": "open"}).json()["count"] == 0


def test_a_draft_is_changed_and_deleted_through_the_api():
    client, manager = client_for(Role.MANAGER)
    organization = manager.organization
    supplier = SupplierFactory.create(organization=organization)
    room = StockLocationFactory.create(organization=organization)
    product = ProductFactory.create(organization=organization)
    first = api_receipt(client, supplier, room, product)
    second = api_receipt(client, supplier, room, product, invoiced="10", cost="10")
    body = {"invoice_date": TODAY().isoformat(), "due_date": TODAY().isoformat()}
    created = client.post(
        reverse("supplier-invoice-list"), {"supplier": supplier.pk, "receipts": [first["id"]], **body}, format="json"
    ).json()

    changed = client.put(
        reverse("supplier-invoice-detail", args=[created["id"]]),
        {"receipts": [first["id"], second["id"]], "post": True, **body},
        format="json",
    )

    assert changed.status_code == 200
    assert (changed.json()["total"], changed.json()["status"]) == ("1355.500", "posted")
    draft = client.post(
        reverse("supplier-invoice-list"), {"supplier": supplier.pk, "receipts": [], **body}, format="json"
    )
    assert list(draft.json()) == ["receipts"]


def test_payment_and_invoice_errors_come_back_on_their_own_keys():
    client, owner = client_for(Role.OWNER)
    organization = owner.organization
    supplier = SupplierFactory.create(organization=organization)
    elsewhere = OrganizationFactory.create()
    foreign_invoice_supplier = SupplierFactory.create(organization=elsewhere)

    unknown_receipt = client.post(
        reverse("supplier-invoice-list"),
        {
            "supplier": supplier.pk,
            "receipts": [999999],
            "invoice_date": TODAY().isoformat(),
            "due_date": TODAY().isoformat(),
        },
        format="json",
    )
    assert list(unknown_receipt.json()) == ["receipts"]

    refused = client.post(
        reverse("supplier-payment-list"),
        {
            "supplier": supplier.pk,
            "paid_on": TODAY().isoformat(),
            "amount": "100",
            "method": "cash",
            "allocations": [{"invoice": 999999, "amount": "10"}],
        },
        format="json",
    )
    assert list(refused.json()) == ["allocations.0.invoice"]
    comma = client.post(
        reverse("supplier-payment-list"),
        {"supplier": supplier.pk, "paid_on": TODAY().isoformat(), "amount": "100,5", "method": "cash"},
        format="json",
    )
    assert list(comma.json()) == ["amount"]
    foreign = client.post(
        reverse("supplier-payment-list"),
        {"supplier": foreign_invoice_supplier.pk, "paid_on": TODAY().isoformat(), "amount": "1", "method": "cash"},
        format="json",
    )
    assert list(foreign.json()) == ["supplier"]
    assert not SupplierPayment.objects.exists()


@pytest.mark.parametrize(
    ("role", "read_status", "write_status"), [(Role.ACCOUNTANT, 200, 403), (Role.DRIVER, 403, 403)]
)
def test_the_accountant_reads_invoices_and_payments_and_drivers_get_nothing(role, read_status, write_status):
    client, membership = client_for(role)
    supplier = SupplierFactory.create(organization=membership.organization)

    for name in ("supplier-invoice-list", "supplier-payment-list"):
        assert client.get(reverse(name)).status_code == read_status
        assert client.post(reverse(name), {}, format="json").status_code == write_status
    assert client.get(reverse("supplier-balance", args=[supplier.pk])).status_code == read_status
    assert client.post(reverse("supplier-invoice-post", args=[1])).status_code == write_status
    assert client.post(reverse("supplier-payment-allocate", args=[1]), {}, format="json").status_code == write_status


def test_another_organization_invoices_payments_and_balances_are_invisible(supplier, receive, organization):
    invoice = invoice_for(organization, None, supplier, [receive()], post=True)
    payment = pay(organization, None, supplier, "10", [(invoice, "10")])
    client, _ = client_for(Role.OWNER)

    assert client.get(reverse("supplier-invoice-list")).json()["count"] == 0
    assert client.get(reverse("supplier-payment-list")).json()["count"] == 0
    assert client.get(reverse("supplier-invoice-detail", args=[invoice.pk])).status_code == 404
    assert client.post(reverse("supplier-invoice-post", args=[invoice.pk])).status_code == 404
    assert client.get(reverse("supplier-payment-detail", args=[payment.pk])).status_code == 404
    assert client.get(reverse("supplier-balance", args=[supplier.pk])).status_code == 404
    assert SupplierInvoice.objects.get().status == SupplierInvoiceStatus.PARTLY_PAID
