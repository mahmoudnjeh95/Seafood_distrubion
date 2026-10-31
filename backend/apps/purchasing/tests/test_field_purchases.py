"""Buying at the port, the "achat terrain" (P3-T12a, D-176): sent by a driver, checked and validated by the office."""

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory
from apps.closing import dashboard
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.inventory import selectors as inventory
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import selectors, services
from apps.purchasing.models import (
    FieldPurchase,
    FieldPurchaseStatus,
    GoodsReceipt,
    SupplierInvoice,
    SupplierInvoiceStatus,
    SupplierPayment,
)

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate
YEAR = timezone.localdate().year


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def driver(organization):
    return MembershipFactory.create(organization=organization, role=Role.DRIVER).user


@pytest.fixture
def supplier(organization):
    return SupplierFactory.create(organization=organization, name="Pêcheur Hamdi")


@pytest.fixture
def product(organization):
    return ProductFactory.create(organization=organization, name="Crevette royale")


@pytest.fixture
def room(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1")


def fields(**changes: Any) -> services.FieldPurchaseFields:
    values: dict[str, Any] = {
        "bought_on": TODAY(),
        "terms": "cash",
        "lines": [],
        "payments": [],
    }
    values.update(changes)
    return values  # type: ignore[return-value]


def a_purchase(organization, driver, supplier, product, **changes: Any) -> FieldPurchase:
    """50 kg at 20 DT/kg from the supplier, 600 DT given in cash."""
    values: dict[str, Any] = {
        "supplier": supplier,
        "lines": [{"product": product, "declared_quantity": "50", "unit_cost": "20.000"}],
        "payments": [{"method": "cash", "amount": "600"}],
    }
    values.update(changes)
    return services.submit_field_purchase(organization=organization, buyer=driver, fields=fields(**values))


def office_fields(purchase: FieldPurchase, **changes: Any) -> services.FieldPurchaseFields:
    """What the purchase says now, as the office's form sends it back, with `changes`."""
    lines = [
        {
            "product": line.product,
            "proposed_product": line.proposed_product,
            "declared_quantity": line.declared_quantity,
            "received_quantity": line.received_quantity,
            "unit_cost": line.unit_cost,
            "partner": line.partner,
        }
        for line in purchase.lines.order_by("id")
    ]
    payments = [
        {"method": p.method, "amount": p.amount, "reference": p.reference, "cash_on": p.cash_on}
        for p in purchase.payments.order_by("id")
    ]
    values: dict[str, Any] = {
        "supplier": purchase.supplier,
        "proposed_supplier": purchase.proposed_supplier,
        "bought_on": purchase.bought_on,
        "terms": purchase.terms,
        "due_days": purchase.due_days,
        "supplier_reference": purchase.supplier_reference,
        "notes": purchase.notes,
        "location": purchase.location,
        "boxes": purchase.boxes,
        "lines": lines,
        "payments": payments,
    }
    values.update(changes)
    return values  # type: ignore[return-value]


# ---- The deal gives the due date ----


@pytest.mark.parametrize(
    ("bought_on", "terms", "days", "due"),
    [
        (dt.date(2026, 10, 15), "cash", 0, dt.date(2026, 10, 15)),
        (dt.date(2026, 10, 15), "days", 30, dt.date(2026, 11, 14)),
        (dt.date(2026, 10, 15), "month_end", 0, dt.date(2026, 10, 31)),
        (dt.date(2028, 2, 3), "month_end", 0, dt.date(2028, 2, 29)),
        (dt.date(2026, 12, 31), "month_end", 10, dt.date(2027, 1, 10)),
    ],
)
def test_due_date_of_the_deal(bought_on, terms, days, due):
    assert services.due_date_of(bought_on, terms, days) == due


# ---- Sent by the driver ----


def test_a_purchase_sent_counts_for_nothing_yet(organization, driver, supplier, product):
    purchase = a_purchase(organization, driver, supplier, product)

    assert purchase.number == f"AT-{YEAR}-0001"
    assert purchase.status == FieldPurchaseStatus.SUBMITTED
    assert purchase.buyer == driver
    assert purchase.revision == 1
    first = purchase.revisions.get()
    assert first.action == "submitted"
    assert first.created_by == driver
    assert first.snapshot["lines"][0]["declared_quantity"] == "50.000"
    assert first.snapshot["total"] == "1000.000"
    assert first.snapshot["paid"] == "600.000"
    # Nothing in stock, nothing owed, nothing paid.
    assert not GoodsReceipt.objects.exists()
    assert not SupplierInvoice.objects.exists()
    assert not SupplierPayment.objects.exists()
    assert AuditLog.objects.filter(action="field_purchase.submitted").count() == 1


def test_a_new_supplier_and_a_new_product_are_given_by_name(organization, driver):
    purchase = services.submit_field_purchase(
        organization=organization,
        buyer=driver,
        fields=fields(
            proposed_supplier="  Hédi, barque bleue  ",
            proposed_supplier_phone="98 123 456",
            lines=[{"proposed_product": "Rouget de roche", "declared_quantity": "12.500", "unit_cost": "18"}],
        ),
    )

    assert purchase.supplier is None
    assert purchase.proposed_supplier == "Hédi, barque bleue"
    assert purchase.proposed_supplier_phone == "98 123 456"
    line = purchase.lines.get()
    assert line.product is None
    assert line.proposed_product == "Rouget de roche"


def test_a_purchase_is_checked_and_every_problem_comes_back_at_once(organization, driver, product):
    with pytest.raises(ValidationError) as caught:
        services.submit_field_purchase(
            organization=organization,
            buyer=driver,
            fields=fields(
                bought_on=TODAY() + dt.timedelta(days=1),
                terms="days",
                due_days=0,
                lines=[
                    {"declared_quantity": "5", "unit_cost": "10"},
                    {"product": product, "declared_quantity": "0", "unit_cost": "1,5"},
                ],
                payments=[{"method": "cheque", "amount": "0", "cash_on": TODAY() - dt.timedelta(days=1)}],
            ),
        )

    errors = caught.value.message_dict
    assert set(errors) == {
        "supplier",
        "bought_on",
        "due_days",
        "lines.0.product",
        "lines.1.declared_quantity",
        "lines.1.unit_cost",
        "payments.0.amount",
        "payments.0.cash_on",
    }
    assert not FieldPurchase.objects.exists()


def test_a_purchase_needs_a_product(organization, driver, supplier):
    with pytest.raises(ValidationError) as caught:
        services.submit_field_purchase(organization=organization, buyer=driver, fields=fields(supplier=supplier))
    assert "lines" in caught.value.message_dict


def test_a_supplier_picked_from_the_list_replaces_a_typed_name(organization, driver, supplier, product):
    purchase = a_purchase(organization, driver, supplier, product, proposed_supplier="Hamdi")
    assert purchase.proposed_supplier == ""


# ---- Changed by the office: revisions ----


def test_each_change_is_a_revision_with_what_changed(organization, driver, supplier, product, room):
    purchase = a_purchase(organization, driver, supplier, product)
    office = UserFactory.create()
    line = purchase.lines.get()

    services.update_field_purchase(
        purchase=purchase,
        actor=office,
        revision=1,
        fields=office_fields(
            purchase,
            location=room,
            lines=[
                {
                    "product": product,
                    "declared_quantity": line.declared_quantity,
                    "received_quantity": "48.500",
                    "unit_cost": line.unit_cost,
                }
            ],
        ),
        office_note="2 kg de glace en trop.",
    )

    purchase.refresh_from_db()
    assert purchase.revision == 2
    assert purchase.office_note == "2 kg de glace en trop."
    second = purchase.revisions.get(number=2)
    assert second.action == "edited"
    assert second.created_by == office
    assert second.note == "2 kg de glace en trop."
    changes = selectors.revision_changes(purchase.revisions.get(number=1).snapshot, second.snapshot)
    assert selectors.RevisionChange("location", None, None, "Chambre froide 1") in changes
    assert selectors.RevisionChange("lines.received_quantity", 0, None, "48.500") in changes
    assert len(changes) == 2


def test_a_save_without_any_change_keeps_the_revision(organization, driver, supplier, product):
    purchase = a_purchase(organization, driver, supplier, product)

    services.update_field_purchase(purchase=purchase, actor=None, revision=1, fields=office_fields(purchase))

    purchase.refresh_from_db()
    assert purchase.revision == 1
    assert purchase.revisions.count() == 1


def test_a_save_on_an_older_revision_is_refused(organization, driver, supplier, product):
    purchase = a_purchase(organization, driver, supplier, product)
    services.update_field_purchase(
        purchase=purchase, actor=None, revision=1, fields=office_fields(purchase, supplier_reference="T-12")
    )

    with pytest.raises(ValidationError) as caught:
        services.update_field_purchase(
            purchase=purchase, actor=None, revision=1, fields=office_fields(purchase, notes="Mon changement")
        )

    assert "revision" in caught.value.message_dict
    purchase.refresh_from_db()
    assert purchase.supplier_reference == "T-12"
    assert purchase.notes == ""


def test_lines_and_payments_added_or_removed_show_in_the_changes(organization, driver, supplier, product):
    other = ProductFactory.create(organization=organization, name="Poulpe")
    purchase = a_purchase(organization, driver, supplier, product)
    first = purchase.lines.get()

    services.update_field_purchase(
        purchase=purchase,
        actor=None,
        revision=1,
        fields=office_fields(
            purchase,
            lines=[
                {"product": product, "declared_quantity": first.declared_quantity, "unit_cost": first.unit_cost},
                {"product": other, "declared_quantity": "8", "unit_cost": "15"},
            ],
            payments=[],
        ),
    )

    revisions = list(purchase.revisions.order_by("number"))
    changes = selectors.revision_changes(revisions[0].snapshot, revisions[1].snapshot)
    assert selectors.RevisionChange("lines.added", 1, None, "Poulpe") in changes
    assert selectors.RevisionChange("payments.removed", 0, "600.000", None) in changes


# ---- Validated: stock, debt, payments ----


def test_validating_records_the_receipt_the_debt_and_the_payment(organization, driver, supplier, product, room):
    purchase = a_purchase(organization, driver, supplier, product, terms="days", due_days=30, supplier_reference="T-7")
    office = UserFactory.create()

    services.update_field_purchase(
        purchase=purchase,
        actor=office,
        revision=1,
        fields=office_fields(
            purchase,
            location=room,
            boxes={"small": 4},
            lines=[{"product": product, "declared_quantity": "50", "received_quantity": "48", "unit_cost": "20"}],
        ),
        validate=True,
    )

    purchase.refresh_from_db()
    assert purchase.status == FieldPurchaseStatus.VALIDATED
    assert purchase.decided_by == office
    assert purchase.revision == 3
    assert [r.action for r in purchase.revisions.order_by("number")] == ["submitted", "edited", "validated"]

    # The kg received are in stock; the kg typed at the port stay on the receipt as its "ordered" weight.
    receipt = purchase.receipt
    assert receipt is not None
    receipt_line = receipt.lines.get()
    assert receipt.location == room
    assert receipt.received_on == purchase.bought_on
    assert receipt.supplier_reference == "T-7"
    assert receipt_line.accepted_quantity == Decimal("48.000")
    assert receipt_line.invoiced_quantity == Decimal("48.000")
    assert receipt_line.ordered_quantity == Decimal("50.000")
    assert inventory.on_hand_of(organization, location_id=room.pk).get().quantity == Decimal("48.000")

    # No invoice yet (D-200): the receipt waits to be invoiced, the 600 DT given at the port are an advance.
    assert purchase.invoice is None
    payment = purchase.payments.get().supplier_payment
    assert payment is not None
    assert payment.amount == Decimal("600.000")
    assert payment.method == "cash"
    balance = selectors.supplier_balance(organization, supplier.pk)
    assert (balance.uninvoiced_receipts, balance.uninvoiced_total) == (1, Decimal("960.000"))
    assert balance.unallocated == Decimal("600.000")

    # The office invoices the receipt later; the advance pays part of it.
    invoice = services.create_invoice(
        organization=organization,
        actor=office,
        supplier=supplier,
        receipts=[receipt],
        invoice_date=TODAY(),
        due_date=TODAY() + dt.timedelta(days=30),
        post=True,
        apply_advances=True,
    )
    invoice = selectors.invoice_of(organization, invoice.pk)
    assert invoice.total == Decimal("960.000")
    assert invoice.status == SupplierInvoiceStatus.PARTLY_PAID
    balance = selectors.supplier_balance(organization, supplier.pk)
    assert balance.balance == Decimal("360.000")
    assert (balance.uninvoiced_receipts, balance.unallocated) == (0, Decimal("0.000"))


def test_more_given_than_owed_is_an_advance_and_a_cheque_keeps_its_cashing_day(
    organization, driver, supplier, product, room
):
    cash_on = TODAY() + dt.timedelta(days=20)
    purchase = a_purchase(
        organization,
        driver,
        supplier,
        product,
        payments=[
            {"method": "cash", "amount": "700"},
            {"method": "cheque", "amount": "300", "reference": "CH-118", "cash_on": cash_on},
        ],
    )
    # 1 000 DT given for the driver's 50 kg; the office counts 40 kg, so 800 DT are owed and 200 DT stay an advance.
    lines: list[dict[str, Any]] = [dict(line) for line in office_fields(purchase)["lines"]]
    lines[0]["received_quantity"] = "40"

    services.update_field_purchase(
        purchase=purchase,
        actor=None,
        revision=1,
        fields=office_fields(purchase, location=room, lines=lines),
        validate=True,
    )

    purchase.refresh_from_db()
    assert purchase.receipt is not None
    invoice = services.create_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        receipts=[purchase.receipt],
        invoice_date=TODAY(),
        due_date=TODAY(),
        post=True,
        apply_advances=True,
    )
    assert selectors.invoice_of(organization, invoice.pk).status == SupplierInvoiceStatus.PAID
    assert selectors.supplier_balance(organization, supplier.pk).unallocated == Decimal("200.000")
    cheque_id = purchase.payments.order_by("id")[1].supplier_payment_id
    assert cheque_id is not None
    cheque = selectors.payment_of(organization, cheque_id)
    assert cheque.reference == "CH-118"
    assert cheque.cash_on == cash_on
    assert cheque.unallocated_amount == Decimal("200.000")  # type: ignore[attr-defined]
    assert selectors.supplier_balance(organization, supplier.pk).balance == Decimal("-200.000")


def test_more_given_than_the_purchase_is_worth_is_refused(organization, driver, supplier, product):
    # 50 kg at 20 DT = 1 000 DT; 1 200 DT typed is a mistake.
    with pytest.raises(ValidationError) as caught:
        a_purchase(
            organization,
            driver,
            supplier,
            product,
            payments=[{"method": "cash", "amount": "700"}, {"method": "cheque", "amount": "500"}],
        )

    assert set(caught.value.message_dict) == {"payments.1.amount"}
    assert "1 000,000" in caught.value.message_dict["payments.1.amount"][0]
    assert not FieldPurchase.objects.exists()

    # Exactly the amount is fine, and so is a lower price later as long as the money still fits.
    purchase = a_purchase(organization, driver, supplier, product, payments=[{"method": "cash", "amount": "1000"}])
    lines: list[dict[str, Any]] = [dict(line) for line in office_fields(purchase)["lines"]]
    lines[0]["unit_cost"] = "19.000"
    with pytest.raises(ValidationError) as caught:
        services.update_field_purchase(
            purchase=purchase, actor=None, revision=1, fields=office_fields(purchase, lines=lines)
        )
    assert set(caught.value.message_dict) == {"payments.0.amount"}


def test_validating_needs_a_supplier_a_place_and_products_of_the_list(organization, driver, product):
    purchase = services.submit_field_purchase(
        organization=organization,
        buyer=driver,
        fields=fields(
            proposed_supplier="Hédi",
            lines=[
                {"proposed_product": "Rouget", "declared_quantity": "5", "unit_cost": "10"},
                {"product": product, "declared_quantity": "5", "unit_cost": "10"},
            ],
        ),
    )

    with pytest.raises(ValidationError) as caught:
        services.update_field_purchase(
            purchase=purchase, actor=None, revision=1, fields=office_fields(purchase), validate=True
        )

    assert set(caught.value.message_dict) == {"supplier", "location", "lines.0.product"}
    assert "Hédi" in caught.value.message_dict["supplier"][0]
    purchase.refresh_from_db()
    assert purchase.status == FieldPurchaseStatus.SUBMITTED
    assert not GoodsReceipt.objects.exists()


def test_a_validated_purchase_no_longer_changes(organization, driver, supplier, product, room):
    purchase = a_purchase(organization, driver, supplier, product)
    services.update_field_purchase(
        purchase=purchase, actor=None, revision=1, fields=office_fields(purchase, location=room), validate=True
    )
    purchase.refresh_from_db()

    with pytest.raises(ValidationError):
        services.update_field_purchase(
            purchase=purchase, actor=None, revision=purchase.revision, fields=office_fields(purchase)
        )
    with pytest.raises(ValidationError):
        services.refuse_field_purchase(purchase=purchase, actor=None, revision=purchase.revision, note="Non")


# ---- Refused ----


def test_refusing_needs_a_reason_and_records_nothing(organization, driver, supplier, product):
    purchase = a_purchase(organization, driver, supplier, product)

    with pytest.raises(ValidationError) as caught:
        services.refuse_field_purchase(purchase=purchase, actor=None, revision=1, note="  ")
    assert "office_note" in caught.value.message_dict

    services.refuse_field_purchase(purchase=purchase, actor=None, revision=1, note="Déjà saisi : AT doublon.")
    purchase.refresh_from_db()
    assert purchase.status == FieldPurchaseStatus.REFUSED
    assert purchase.office_note == "Déjà saisi : AT doublon."
    assert purchase.revisions.get(number=2).action == "refused"
    assert not GoodsReceipt.objects.exists()
    assert not SupplierPayment.objects.exists()


# ---- The dashboard alert ----


def test_purchases_waiting_and_late_are_counted(organization, driver, supplier, product):
    a_purchase(organization, driver, supplier, product)
    late = a_purchase(organization, driver, supplier, product)
    FieldPurchase.objects.filter(pk=late.pk).update(created_at=timezone.now() - dt.timedelta(hours=25))

    waiting = selectors.field_purchases_waiting(organization)
    assert (waiting.waiting, waiting.late) == (2, 1)
    board = dashboard.dashboard_of(organization, today=TODAY())
    assert (board.field_purchases_waiting, board.field_purchases_late) == (2, 1)


# ---- API ----


def client_for(role, organization):
    membership = MembershipFactory.create(role=role, organization=organization)
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def payload(purchase: FieldPurchase, room, **changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "revision": purchase.revision,
        "supplier": purchase.supplier_id,
        "bought_on": purchase.bought_on.isoformat(),
        "terms": purchase.terms,
        "location": room.pk,
        "lines": [
            {
                "product": line.product_id,
                "declared_quantity": str(line.declared_quantity),
                "received_quantity": "49",
                "unit_cost": str(line.unit_cost),
            }
            for line in purchase.lines.order_by("id")
        ],
        "payments": [{"method": p.method, "amount": str(p.amount)} for p in purchase.payments.order_by("id")],
    }
    values.update(changes)
    return values


def test_the_office_checks_and_validates_through_the_api(organization, driver, supplier, product, room):
    purchase = a_purchase(organization, driver, supplier, product)
    manager = client_for(Role.MANAGER, organization)

    listed = manager.get(reverse("field-purchase-list"), {"status": "submitted"}).json()
    assert [row["number"] for row in listed["results"]] == [purchase.number]
    assert listed["results"][0]["rest"] == "400.000"
    assert "revisions" not in listed["results"][0]

    saved = manager.put(
        reverse("field-purchase-detail", args=[purchase.pk]),
        payload(purchase, room, office_note="Pesé à 49 kg."),
        format="json",
    )
    assert saved.status_code == 200, saved.json()
    body = saved.json()
    assert body["revision"] == 2
    assert body["total"] == "980.000"
    assert body["declared_total"] == "1000.000"
    assert body["revisions"][1]["note"] == "Pesé à 49 kg."
    assert {"field": "lines.received_quantity", "line": 0, "before": None, "after": "49.000"} in body["revisions"][1][
        "changes"
    ]

    stale = manager.put(
        reverse("field-purchase-detail", args=[purchase.pk]), payload(purchase, room, revision=1), format="json"
    )
    assert stale.status_code == 400
    assert "revision" in stale.json()

    validated = manager.put(
        reverse("field-purchase-detail", args=[purchase.pk]),
        payload(purchase, room, revision=2, confirm=True),
        format="json",
    ).json()
    assert validated["status"] == "validated"
    assert validated["receipt"]["number"].startswith("BR-")
    assert validated["invoice"] is None  # invoiced later from "Nouvelle facture" (D-200)
    assert validated["payments"][0]["supplier_payment"]["number"].startswith(f"RF-{YEAR}-")


def test_only_the_owner_picks_a_partner(organization, driver, supplier, product, room):
    partner = SupplierFactory.create(organization=organization)
    purchase = a_purchase(organization, driver, supplier, product)
    with_partner = payload(purchase, room)
    with_partner["lines"][0]["partner"] = partner.pk

    manager = client_for(Role.MANAGER, organization)
    refused = manager.put(reverse("field-purchase-detail", args=[purchase.pk]), with_partner, format="json")
    assert refused.status_code == 400
    assert "lines.0.partner" in refused.json()

    owner = client_for(Role.OWNER, organization)
    chosen = owner.put(reverse("field-purchase-detail", args=[purchase.pk]), with_partner, format="json")
    assert chosen.status_code == 200
    assert chosen.json()["lines"][0]["partner"]["id"] == partner.pk

    # The manager may keep the partner the owner chose, and validate.
    with_partner["revision"] = 2
    with_partner["confirm"] = True
    kept = manager.put(reverse("field-purchase-detail", args=[purchase.pk]), with_partner, format="json")
    assert kept.status_code == 200, kept.json()


def test_the_accountant_reads_and_a_driver_is_refused(organization, driver, supplier, product, room):
    purchase = a_purchase(organization, driver, supplier, product)
    accountant = client_for(Role.ACCOUNTANT, organization)
    assert accountant.get(reverse("field-purchase-detail", args=[purchase.pk])).status_code == 200
    assert (
        accountant.put(
            reverse("field-purchase-detail", args=[purchase.pk]), payload(purchase, room), format="json"
        ).status_code
        == 403
    )
    assert client_for(Role.DRIVER, organization).get(reverse("field-purchase-list")).status_code == 403
    other = client_for(Role.OWNER, OrganizationFactory.create())
    assert other.get(reverse("field-purchase-detail", args=[purchase.pk])).status_code == 404


def test_refusing_through_the_api(organization, driver, supplier, product):
    purchase = a_purchase(organization, driver, supplier, product)
    owner = client_for(Role.OWNER, organization)

    refused = owner.post(
        reverse("field-purchase-refuse", args=[purchase.pk]),
        {"revision": 1, "office_note": "Produit abîmé, rendu au pêcheur."},
        format="json",
    )

    assert refused.status_code == 200
    assert refused.json()["status"] == "refused"
    assert refused.json()["revisions"][-1]["action"] == "refused"


def test_the_office_types_a_purchase_phoned_in(organization, product):
    owner = client_for(Role.OWNER, organization)

    created = owner.post(
        reverse("field-purchase-list"),
        {
            "proposed_supplier": "Hédi",
            "bought_on": TODAY().isoformat(),
            "terms": "month_end",
            "lines": [{"product": product.pk, "declared_quantity": "10", "unit_cost": "12.500"}],
        },
        format="json",
    )

    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["status"] == "submitted"
    assert body["proposed_supplier"] == "Hédi"
    assert body["total"] == "125.000"
    assert body["revisions"][0]["action"] == "submitted"
