import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from apps.catalog.models import Product, ProductPrice
from apps.core.models import Membership, NumberSeries, Organization, Role, User
from apps.expenses.models import Expense, ExpenseCategory
from apps.fleet.models import Truck
from apps.hr.models import Employee
from apps.inventory.models import Batch, StockLocation, StockMovement
from apps.partners.models import Customer, Supplier
from apps.sales.models import Invoice, Sale
from apps.treasury.models import TreasuryAccount, TreasuryMovement

pytestmark = pytest.mark.django_db


def _production_copy(settings) -> Organization:
    """What the training stack holds right after the script loaded production: the demo stands in for it."""
    settings.DEBUG = True
    call_command("seed_dev", stdout=StringIO())
    settings.TRAINING_MODE = True
    return Organization.objects.get()


def _work() -> dict[str, int]:
    return {
        "stock movements": StockMovement.objects.count(),
        "lots": Batch.objects.count(),
        "sales": Sale.objects.count(),
        "invoices": Invoice.objects.count(),
        "expenses": Expense.objects.count(),
        "treasury movements": TreasuryMovement.objects.count(),
    }


def _master() -> dict[str, int]:
    return {
        "products": Product.objects.count(),
        "prices": ProductPrice.objects.count(),
        "customers": Customer.objects.count(),
        "suppliers": Supplier.objects.count(),
        "employees": Employee.objects.count(),
        "locations": StockLocation.objects.count(),
        "trucks": Truck.objects.count(),
        "expense categories": ExpenseCategory.objects.count(),
        "treasury accounts": TreasuryAccount.objects.count(),
        "number series": NumberSeries.objects.count(),
    }


def _trainee(organization: Organization) -> User:
    trainee = User.objects.create_user("stagiaire-chauffeur", password="appris-2026", first_name="Sami")
    Membership.objects.create(user=trainee, organization=organization, role=Role.DRIVER, can_buy=True)
    return trainee


def test_reset_keeps_the_master_data_deletes_the_work_and_puts_the_trainees_back(settings, tmp_path: Path):
    organization = _production_copy(settings)
    _trainee(organization)
    master = _master()
    assert all(count > 0 for count in [*_work().values(), *master.values()]), (_work(), master)
    salaries = sorted(Employee.objects.values_list("monthly_salary", flat=True))

    exported = StringIO()
    call_command("prepare_training", "--export-logins", stdout=exported)
    logins = json.loads(exported.getvalue())
    # The demo's production accounts have a password here; on a real copy they were locked by an earlier reset.
    assert {login["username"] for login in logins} == {"owner", "driver", "stagiaire-chauffeur"}
    logins = [login for login in logins if login["username"] == "stagiaire-chauffeur"]
    file = tmp_path / "logins.json"
    file.write_text(json.dumps(logins), encoding="utf-8")

    output = StringIO()
    call_command("prepare_training", "--logins", str(file), "--apply", stdout=output)

    assert _work() == dict.fromkeys(_work(), 0)
    assert _master() == master
    assert sorted(Employee.objects.values_list("monthly_salary", flat=True)) == salaries
    assert not TreasuryAccount.objects.exclude(opening_balance=0).exists()
    # Production's accounts cannot log in any more.
    owner = User.objects.get(username="owner")
    assert not owner.is_active
    assert not owner.has_usable_password()
    # The trainee is back with their password and role.
    trainee = User.objects.get(username="stagiaire-chauffeur")
    assert trainee.is_active
    assert trainee.check_password("appris-2026")
    membership = trainee.memberships.get()
    assert (membership.organization_id, membership.role, membership.can_buy) == (organization.pk, Role.DRIVER, True)
    # No `formation` login among them: one is created, its password printed once.
    formation = User.objects.get(username="formation")
    assert formation.memberships.get().role == Role.OWNER
    password = output.getvalue().split("password: ")[1].split()[0]
    assert formation.check_password(password)


def test_the_next_reset_keeps_the_formation_owner_and_its_password(settings, tmp_path: Path):
    _production_copy(settings)
    call_command("prepare_training", "--apply", stdout=StringIO())
    formation = User.objects.get(username="formation")
    formation.set_password("mot-de-passe-du-chef")
    formation.save()

    exported = StringIO()
    call_command("prepare_training", "--export-logins", stdout=exported)
    file = tmp_path / "logins.json"
    file.write_text(exported.getvalue(), encoding="utf-8")
    assert [login["username"] for login in json.loads(exported.getvalue())] == ["formation"]
    output = StringIO()
    call_command("prepare_training", "--logins", str(file), "--apply", stdout=output)

    assert User.objects.get(username="formation").check_password("mot-de-passe-du-chef")
    assert "password:" not in output.getvalue()


def test_dry_run_changes_nothing(settings):
    _production_copy(settings)
    work = _work()
    output = StringIO()

    call_command("prepare_training", stdout=output)

    assert _work() == work
    assert User.objects.get(username="owner").check_password("frutti-dev")
    assert not User.objects.filter(username="formation").exists()
    assert "Dry run" in output.getvalue()


def test_refused_outside_the_training_copy(settings):
    _production_copy(settings)
    settings.TRAINING_MODE = False
    work = _work()

    with pytest.raises(CommandError, match="not the training copy"):
        call_command("prepare_training", "--apply", stdout=StringIO())
    with pytest.raises(CommandError, match="not the training copy"):
        call_command("prepare_training", "--export-logins", stdout=StringIO())
    assert _work() == work


def test_instance_says_which_copy_this_is(settings):
    client = APIClient()
    settings.TRAINING_MODE = False
    settings.TRAINING_ADMIN_URL = "https://app1.fruttidelmare.com"
    settings.TRAINING_DRIVER_URL = "https://ch1.fruttidelmare.com"
    assert client.get("/api/v1/instance").json() == {
        "training": False,
        "training_admin_url": "https://app1.fruttidelmare.com",
        "training_driver_url": "https://ch1.fruttidelmare.com",
    }

    settings.TRAINING_MODE = True
    assert client.get("/api/v1/instance").json() == {
        "training": True,
        "training_admin_url": "",
        "training_driver_url": "",
    }
