import io
import shutil
import tempfile
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory
from apps.expenses import services
from apps.fleet import services as fleet_services

from .conftest import category, client_for, load, member, receive

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year


@pytest.fixture(autouse=True)
def media_root():
    folder = tempfile.mkdtemp()
    with override_settings(MEDIA_ROOT=folder):
        yield folder
    shutil.rmtree(folder, ignore_errors=True)


def payload(cat, amount="45.500", **fields):
    body = {"spent_on": timezone.localdate().isoformat(), "category": cat.pk, "amount": amount}
    body.update(fields)
    return body


def create(api, cat, amount="45.500", **fields):
    return api.post(reverse("expense-list"), payload(cat, amount, **fields), format="json")


def test_an_expense_is_created_and_answered_with_amounts_as_strings(api, fuel, truck):
    response = create(api, fuel, description="Gasoil", payee="Station Agil", truck=truck.pk, payment_method="cash")

    assert response.status_code == 201
    body = response.json()
    assert (body["number"], body["status"], body["amount"]) == (f"DP-{YEAR}-0001", "draft", "45.500")
    assert body["category"] == {"id": fuel.pk, "code": "fuel", "name": "Carburant"}
    assert body["truck"] == {"id": truck.pk, "name": "Camion 2", "plate": "102 TU 2002"}
    assert (body["batch"], body["receipt_url"], body["shares"]) == (None, None, [])


def test_errors_come_back_on_their_fields(api, fuel, organization):
    response = create(api, fuel, amount="abc", batch=999999)
    assert response.status_code == 400
    assert "batch" in response.json()

    response = create(api, fuel, amount="-3")
    assert response.status_code == 400
    assert "amount" in response.json()


def test_approve_now_and_the_decision_endpoints(api, fuel):
    approved = create(api, fuel, approve_now=True).json()
    assert approved["status"] == "approved"
    assert approved["decided_by"]

    draft = create(api, fuel).json()
    refused = api.post(reverse("expense-reject", args=[draft["id"]]), {"reason": "Doublon"}, format="json")
    assert (refused.status_code, refused.json()["status"]) == (200, "rejected")
    again = api.post(reverse("expense-approve", args=[draft["id"]]))
    assert again.status_code == 400


def test_a_draft_is_edited_and_deleted(api, fuel, organization):
    draft = create(api, fuel).json()
    transport = category(organization, "transport")

    edited = api.put(reverse("expense-detail", args=[draft["id"]]), payload(transport, "12"), format="json")
    assert (edited.status_code, edited.json()["amount"], edited.json()["category"]["code"]) == (
        200,
        "12.000",
        "transport",
    )
    assert api.delete(reverse("expense-detail", args=[draft["id"]])).status_code == 204
    assert api.get(reverse("expense-detail", args=[draft["id"]])).status_code == 404


def test_list_filters_and_totals(api, fuel, organization):
    create(api, fuel, "10", approve_now=True, description="Gasoil")
    create(api, category(organization, "rent"), "800")

    listed = api.get(reverse("expense-list"), {"status": "approved"}).json()
    assert (listed["count"], listed["results"][0]["description"]) == (1, "Gasoil")
    assert api.get(reverse("expense-list"), {"search": "gasoil"}).json()["count"] == 1
    totals = api.get(reverse("expense-totals")).json()
    assert totals == {"count": 2, "approved": "10.000", "waiting": "800.000"}


def test_a_photo_receipt_is_stored_as_webp_and_a_pdf_as_it_is(api, fuel):
    draft = create(api, fuel).json()
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buffer, format="JPEG")
    photo = SimpleUploadedFile("ticket.jpg", buffer.getvalue(), content_type="image/jpeg")

    answer = api.put(reverse("expense-receipt", args=[draft["id"]]), {"receipt": photo}, format="multipart")
    assert answer.status_code == 200
    assert answer.json()["receipt_type"] == "image/webp"
    image = api.get(answer.json()["receipt_url"])
    assert (image.status_code, image["Content-Type"]) == (200, "image/webp")

    pdf = SimpleUploadedFile("facture.pdf", b"%PDF-1.4\n%%EOF\n", content_type="application/pdf")
    answer = api.put(reverse("expense-receipt", args=[draft["id"]]), {"receipt": pdf}, format="multipart")
    assert answer.json()["receipt_type"] == "application/pdf"
    document = api.get(answer.json()["receipt_url"])
    assert (document["Content-Type"], b"".join(document.streaming_content)) == (
        "application/pdf",
        b"%PDF-1.4\n%%EOF\n",
    )
    text = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
    refused = api.put(reverse("expense-receipt", args=[draft["id"]]), {"receipt": text}, format="multipart")
    assert (refused.status_code, list(refused.json())) == (400, ["receipt"])


def test_a_truck_cost_of_the_day_answers_its_split(api, organization, actor, cold_room, truck):
    lot = receive(organization, "Dorade", "100", cold_room, number="L-0001")
    load(organization, actor, cold_room, truck, [(lot, "12.5")])

    body = create(api, category(organization, "transport"), "30", truck=truck.pk, approve_now=True).json()
    assert body["shares"] == [
        {
            "batch_id": lot.pk,
            "batch_number": "L-0001",
            "product_name": "Dorade",
            "quantity": "12.500",
            "day_quantity": "12.500",
            "amount": "30.000",
        }
    ]
    costs = api.get(reverse("lot-costs"), {"batch": lot.pk}).json()
    assert costs["total"] == "30.000"
    assert [(line["kind"], line["amount"], line["truck_name"]) for line in costs["lines"]] == [
        ("truck_day", "30.000", "Camion 2")
    ]


def test_the_accountant_reads_but_changes_nothing_and_drivers_get_403(organization, fuel):
    accountant = client_for(member(organization, Role.ACCOUNTANT))
    driver = client_for(member(organization, Role.DRIVER))

    assert accountant.get(reverse("expense-list")).status_code == 200
    assert create(accountant, fuel).status_code == 403
    assert driver.get(reverse("expense-list")).status_code == 403
    assert driver.get(reverse("expense-category-list")).status_code == 403


def test_only_the_owner_manages_categories(api, organization):
    owner = client_for(member(organization, Role.OWNER))

    assert api.post(reverse("expense-category-list"), {"name": "Glace"}, format="json").status_code == 403
    created = owner.post(reverse("expense-category-list"), {"name": "Glace"}, format="json")
    assert (created.status_code, created.json()["code"]) == (201, "")
    renamed = owner.patch(
        reverse("expense-category-detail", args=[created.json()["id"]]), {"is_active": False}, format="json"
    )
    assert renamed.json()["is_active"] is False
    names = [row["name"] for row in api.get(reverse("expense-category-list"), {"status": "all"}).json()]
    assert names[:2] == ["Personnel", "Main-d'œuvre journalière"]
    assert names[-1] == "Glace"


def test_another_organizations_expenses_are_invisible(api, organization):
    other = MembershipFactory.create(role=Role.MANAGER)
    expense = services.create_expense(
        organization=other.organization,
        actor=other.user,
        spent_on=timezone.localdate(),
        category=category(other.organization, "fuel"),
        amount="5",
    )

    assert api.get(reverse("expense-detail", args=[expense.pk])).status_code == 404
    assert api.get(reverse("expense-list")).json()["count"] == 0
    assert api.get(reverse("lot-costs"), {"batch": 999999}).status_code == 404


def test_a_driver_enters_a_road_expense_with_a_photo_and_it_waits_for_approval(organization, actor, truck):
    driver = member(organization, Role.DRIVER)
    fleet_services.assign_truck(
        organization=organization, actor=actor, truck=truck, driver=driver.user, date=timezone.localdate()
    )
    # The day starts with cash, so "La caisse" (the default) pays (D-220).
    fleet_services.set_day_fund(
        organization=organization,
        actor=actor,
        driver=driver.user,
        date=timezone.localdate(),
        opening_cash=Decimal("50"),
    )
    fleet_services.accept_day_fund(organization=organization, actor=driver.user, truck=truck, date=timezone.localdate())
    api = client_for(driver)
    categories = api.get(reverse("my-expense-categories")).json()
    assert {c["name"] for c in categories} >= {"Carburant", "Divers"}
    fuel_id = next(c["id"] for c in categories if c["name"] == "Carburant")
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buffer, format="JPEG")
    photo = SimpleUploadedFile("ticket.jpg", buffer.getvalue(), content_type="image/jpeg")
    body = {
        "category": fuel_id,
        "amount": "45.500",
        "description": "Gasoil",
        "receipt": photo,
        "client_uuid": str(uuid4()),
    }

    created = api.post(reverse("my-expenses"), body, format="multipart")
    again = api.post(reverse("my-expenses"), {k: v for k, v in body.items() if k != "receipt"}, format="multipart")

    assert created.status_code == 201
    assert (created.json()["status"], created.json()["amount"]) == ("pending", "45.500")
    assert again.json()["id"] == created.json()["id"]  # same client_uuid: no second expense
    assert [e["number"] for e in api.get(reverse("my-expenses")).json()] == [created.json()["number"]]
    # Not a road category, and not for the office.
    rent = category(organization, "rent")
    refused = api.post(reverse("my-expenses"), {"category": rent.pk, "amount": "10"}, format="multipart")
    assert refused.status_code == 400
    assert client_for(member(organization, Role.MANAGER)).get(reverse("my-expenses")).status_code == 403


def test_the_owner_chooses_the_phone_categories_and_removes_an_unused_one(organization, actor, truck):
    owner = client_for(member(organization, Role.OWNER))
    driver = member(organization, Role.DRIVER)
    fleet_services.assign_truck(
        organization=organization, actor=actor, truck=truck, driver=driver.user, date=timezone.localdate()
    )
    api = client_for(driver)
    tolls = owner.post(reverse("expense-category-list"), {"name": "Péage", "for_drivers": True}, format="json").json()
    unused = owner.post(reverse("expense-category-list"), {"name": "Essai"}, format="json").json()
    names = {c["name"] for c in api.get(reverse("my-expense-categories")).json()}
    assert "Péage" in names
    assert "Essai" not in names

    # Paid out of the driver's pocket on a day started at 0 DT (D-205).
    paid = api.post(
        reverse("my-expenses"), {"category": tolls["id"], "amount": "3.500", "paid_with": "pocket"}, format="multipart"
    )
    assert paid.status_code == 201, paid.json()
    assert (paid.json()["paid_by_driver"], paid.json()["payment_method"]) == (True, "cash")
    card = api.post(
        reverse("my-expenses"), {"category": tolls["id"], "amount": "2", "paid_with": "card"}, format="multipart"
    )
    assert (card.json()["paid_by_driver"], card.json()["payment_method"]) == (False, "other")

    detail = lambda pk: reverse("expense-category-detail", args=[pk])  # noqa: E731
    assert owner.delete(detail(unused["id"])).status_code == 204
    assert owner.delete(detail(tolls["id"])).status_code == 400  # used: archive it instead
    assert owner.delete(detail(category(organization, "rent").pk)).status_code == 400  # a default one stays
    assert owner.patch(detail(tolls["id"]), {"for_drivers": False}, format="json").json()["for_drivers"] is False
    assert "Péage" not in {c["name"] for c in api.get(reverse("my-expense-categories")).json()}


def test_a_road_expense_sent_again_with_its_photo_after_the_office_decided_it_answers_with_it(
    organization, actor, truck
):
    driver = member(organization, Role.DRIVER)
    fleet_services.assign_truck(
        organization=organization, actor=actor, truck=truck, driver=driver.user, date=timezone.localdate()
    )
    # The day starts with cash, so "La caisse" (the default) pays (D-220).
    fleet_services.set_day_fund(
        organization=organization,
        actor=actor,
        driver=driver.user,
        date=timezone.localdate(),
        opening_cash=Decimal("50"),
    )
    fleet_services.accept_day_fund(organization=organization, actor=driver.user, truck=truck, date=timezone.localdate())
    api = client_for(driver)
    fuel = next(c["id"] for c in api.get(reverse("my-expense-categories")).json() if c["name"] == "Carburant")
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buffer, format="JPEG")

    def body():
        photo = SimpleUploadedFile("ticket.jpg", buffer.getvalue(), content_type="image/jpeg")
        return {
            "category": fuel,
            "amount": "45.500",
            "receipt": photo,
            "client_uuid": "6f0e9c4e-2d57-4f3a-9d2b-5f0f4c1a7a10",
        }

    created = api.post(reverse("my-expenses"), body(), format="multipart")
    office = client_for(member(organization, Role.MANAGER))
    assert office.post(reverse("expense-approve", args=[created.json()["id"]])).status_code == 200

    again = api.post(reverse("my-expenses"), body(), format="multipart")

    assert again.status_code == 201
    assert again.json()["id"] == created.json()["id"]
    assert again.json()["status"] == "approved"
