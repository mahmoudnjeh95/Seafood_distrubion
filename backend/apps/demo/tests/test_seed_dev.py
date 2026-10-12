from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.catalog import selectors as catalog
from apps.core.models import Membership, Organization, Role, User
from apps.core.selectors import active_membership
from apps.fleet import selectors as fleet
from apps.inventory import selectors as inventory
from apps.partners import selectors as partners
from apps.purchasing import selectors as purchasing

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year


def test_seed_creates_an_organization_its_logins_catalogue_suppliers_locations_batches_and_stock(settings):
    settings.DEBUG = True

    call_command("seed_dev")
    call_command("seed_dev")  # running it again changes nothing

    organization = Organization.objects.get()
    assert organization.name == "Frutti Del Mare"
    assert set(Membership.objects.values_list("user__username", "role")) == {
        ("owner", Role.OWNER),
        ("driver", Role.DRIVER),
    }
    owner = User.objects.get(username="owner")
    assert owner.check_password("frutti-dev")
    membership = active_membership(owner)
    assert membership is not None
    assert membership.organization == organization

    products = catalog.products_of(organization)
    assert products.count() == 12
    shrimp = products.get(reference="CR-001")
    assert (shrimp.name_ar, shrimp.category.name, getattr(shrimp, "current_price")) == (  # noqa: B009
        "قمرون ملكي",
        "Crustacés",
        Decimal("42.000"),
    )
    assert catalog.categories_of(organization).count() == 5

    suppliers = partners.suppliers_of(organization)
    assert list(suppliers.values_list("reference", flat=True)) == ["F-003", "F-002", "F-001", "F-004"]
    assert suppliers.get(reference="F-002").contacts.count() == 2

    assert [(location.kind, location.sells) for location in inventory.locations_of(organization)] == [
        ("cold_room", True),
        ("cold_room", True),
        ("truck", True),
        ("truck", True),
        ("truck", True),
    ]
    driver = Membership.objects.get(user__username="driver")
    truck = fleet.truck_of_driver(driver)
    assert truck is not None
    assert (truck.location.name, truck.plate) == ("Camion 1", "101 TU 2001")
    # Today's truck of the day (D-046), written once although the seed ran twice.
    (assignment,) = fleet.assignments_of(organization)
    assert (assignment.truck, assignment.driver.username) == (truck, "driver")

    batches = inventory.batches_of(organization)
    assert batches.count() == 15 + 2  # the demo batches, then the demo receipt's two lines
    assert sorted(batches.values_list("number", flat=True))[:2] == ["L-0001", "L-0002"]
    # Q4: the same product from two suppliers at two costs.
    dorade = batches.filter(product__reference="DO-003")
    assert set(dorade.values_list("supplier__reference", "unit_cost")) == {
        ("F-002", Decimal("20.000")),
        ("F-003", Decimal("18.500")),
        ("F-002", Decimal("20.250")),
    }
    # Q7: the older Crevette Royale delivery leaves first.
    shrimp_batches = inventory.batches_oldest_first(organization, product_id=shrimp.pk)
    assert list(shrimp_batches.values_list("receipt_reference", flat=True)) == ["KRK-1187", "KRK-1192"]

    # Every batch was received into a cold room, and Camion 1 was loaded once.
    # + Camion 2's demo load and return, + the 1.5 kg of mussels lost on Camion 1, + the demo sales' lines
    assert inventory.movements_of(organization).count() == 15 + 4 + 2 + 4 + 1 + 7
    rooms = {location.name: location for location in inventory.locations_of(organization)}
    # 38.5 kg, then 7 kg sold to Restaurant Le Corail (P2-T04 demo sales)
    assert inventory.quantity_on_hand(organization, location_id=truck.location_id) == Decimal("31.500")
    # 65 kg, then 3 kg sold from Camion 1 and 4 kg on Sidi Mansour's converted quote
    assert inventory.quantity_on_hand(organization, product_id=shrimp.pk) == Decimal("58.000")
    assert inventory.quantity_on_hand(
        organization, location_id=rooms["Chambre froide 1 (frais)"].pk, product_id=shrimp.pk
    ) == Decimal("42.000")  # 53 kg, then 8 kg loaded on Camion 2 and 1 kg back, then 4 kg sold
    assert inventory.quantity_on_hand(organization, location_id=rooms["Chambre froide 2 (congelé)"].pk) == Decimal(
        "107.000"
    )

    # The demo receipt: 60 kg of dorade accepted for 62 ordered and invoiced.
    (receipt,) = purchasing.receipts_of(organization)
    assert (receipt.supplier.reference, receipt.supplier_reference, receipt.number) == ("F-002", "MPS-5544", "BR-0001")
    assert getattr(receipt, "has_differences") is True  # noqa: B009
    assert [line.accepted_quantity for line in receipt.lines.all()] == [Decimal("60.000"), Decimal("20.000")]

    # Its invoice, posted and partly paid by cheque: the supplier balance shows what is still owed.
    (invoice,) = purchasing.invoices_of(organization)
    assert (invoice.number, invoice.status, invoice.total) == ("FF-0001", "partly_paid", Decimal("1471.500"))
    assert [link.receipt for link in invoice.receipt_links.all()] == [receipt]
    (payment,) = purchasing.payments_of(organization)
    assert (payment.number, payment.method, payment.amount) == (f"RF-{YEAR}-0001", "cheque", Decimal("500.000"))
    balance = purchasing.supplier_balance(organization, receipt.supplier_id)
    assert (balance.invoiced, balance.paid, balance.balance) == (
        Decimal("1471.500"),
        Decimal("500.000"),
        Decimal("971.500"),
    )


def test_outside_development_the_known_password_is_refused(settings):
    settings.DEBUG = False

    with pytest.raises(CommandError):
        call_command("seed_dev")
    with pytest.raises(CommandError):
        call_command("seed_dev", password="short")
    assert not User.objects.exists()


def test_a_short_password_is_accepted_when_every_account_already_exists(settings):
    # Staging's first generated password had 11 characters; later deploys must still add the demo data.
    settings.DEBUG = False
    call_command("seed_dev", password="a-long-demo-password")

    call_command("seed_dev", password="short")

    assert User.objects.get(username="owner").check_password("a-long-demo-password")


def test_staging_demo_accounts_get_the_password_given(settings):
    settings.DEBUG = False

    call_command("seed_dev", password="a-long-demo-password")

    driver = User.objects.get(username="driver")
    assert driver.check_password("a-long-demo-password")
    assert not driver.check_password("frutti-dev")
