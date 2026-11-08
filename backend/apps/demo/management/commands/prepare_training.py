"""Turn a fresh copy of the production database into the training database (D-290).

Run only by `deploy/reset-training.sh`, on the training stack, right after it loaded a copy of production. It refuses
to run unless the settings say this is the training copy (`FRUTTI_TRAINING=true`), so it can never empty production.

Two modes:

- `--export-logins`: prints, as JSON, the logins created in the training copy (every account with a usable password:
  the copied production accounts have none, see below). The script keeps them before it loads production again.
- the reset (default dry run, `--apply` for real): keeps the master data of production (company settings and
  numbering, products and their prices, customers and suppliers with their contacts, price lists, cold rooms and
  trucks, box holders, employees with their salaries, expense categories, day labourers, recurring costs, cold-room
  weights, public-site settings, banks and treasury accounts) and deletes the work: stock, purchases, sales,
  invoices, payments, closings, payroll, expenses, lots and partnerships, documents, notifications and the audit log.
  The copied production accounts stay (other rows point at them) but can no longer log in: no password, inactive,
  their sessions deleted. The logins given with `--logins` are put back, password included. A `formation` owner
  login is created when none of them is called so; its password is printed once.

Like `prepare_client_start` (D-146), it deletes with SQL inside one transaction and checks every foreign key before
the end (`SET CONSTRAINTS ALL IMMEDIATE`): a dangling reference rolls everything back.
"""

import json
import secrets
import sys
from pathlib import Path
from typing import Any

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import IntegrityError, connection, transaction
from django.db.models import Model, ProtectedError

from apps.boxes.models import BoxHolder
from apps.catalog.models import Category, PriceList, PriceListItem, Product, ProductPrice
from apps.core.models import Membership, NumberPrefix, NumberSeries, Organization, OrganizationScopedModel, Role, User
from apps.expenses.models import ColdRoomWeight, DayLabourer, ExpenseCategory, RecurringCost
from apps.fleet.models import Truck
from apps.hr.models import Employee
from apps.inventory.models import StockLocation, StockSettings
from apps.partners.models import Customer, CustomerContact, Supplier, SupplierContact
from apps.sales.models import FinanceSettings
from apps.storefront.models import SiteProduct, SiteSettings
from apps.treasury.models import Bank, TreasuryAccount

# The master data copied from production. Every other organization-scoped table is the work, and is emptied.
# The numbering is kept, so a training number never goes back over a number production has already given.
KEPT_MODELS: tuple[type[Model], ...] = (
    NumberSeries,
    NumberPrefix,
    Category,
    Product,
    ProductPrice,
    PriceList,
    PriceListItem,
    Supplier,
    SupplierContact,
    Customer,
    CustomerContact,
    StockLocation,
    StockSettings,
    BoxHolder,
    Truck,
    FinanceSettings,
    Employee,
    ExpenseCategory,
    DayLabourer,
    ColdRoomWeight,
    RecurringCost,
    SiteSettings,
    SiteProduct,
    Bank,
    TreasuryAccount,
)
TRAINING_OWNER = "formation"
# Production's database on the shared PostgreSQL server; the training copy's is `frutti_training`.
PRODUCTION_DATABASE = "frutti"


class Command(BaseCommand):
    help = (
        "Training copy only (D-290): keep production's master data, delete the work, put the training logins back. "
        "Without --apply it only reports, and rolls back. --export-logins prints the training logins as JSON."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--export-logins", action="store_true", help="Print the training logins as JSON, then stop."
        )
        parser.add_argument(
            "--logins", help="JSON file from --export-logins (`-`: read it from the input), put back after the reset."
        )
        parser.add_argument("--apply", action="store_true", help="Change the database for real (default: dry run).")

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.TRAINING_MODE:
            raise CommandError("Refused: this is not the training copy (FRUTTI_TRAINING is not true). Nothing changed.")
        if connection.settings_dict["NAME"] == PRODUCTION_DATABASE:
            raise CommandError(f"Refused: connected to production's database {PRODUCTION_DATABASE!r}. Nothing changed.")
        if options["export_logins"]:
            self.stdout.write(json.dumps(export_logins(), ensure_ascii=False, indent=2))
            return

        logins: list[dict[str, Any]] = []
        if options["logins"] == "-":
            logins = json.loads(sys.stdin.read() or "[]")
        elif options["logins"] is not None:
            logins = json.loads(Path(options["logins"]).read_text(encoding="utf-8"))
        apply = options["apply"]
        try:
            with transaction.atomic():
                report = empty_work()
                locked = lock_copied_accounts()
                created_password = restore_logins(logins)
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                if not apply:
                    transaction.set_rollback(True)
        except (IntegrityError, ProtectedError) as error:
            raise CommandError(f"Nothing was changed: a record would point at a deleted one ({error}).") from error

        self.stdout.write("Deleted (the work):" if apply else "Would delete (the work):")
        for label, count in report:
            self.stdout.write(f"  {label:<45} {count}")
        self.stdout.write(f"Production accounts locked (no password, inactive): {locked}")
        self.stdout.write(f"Training logins put back: {len(logins)}")
        if not apply:
            self.stdout.write(self.style.WARNING("Dry run: nothing was changed. Run again with --apply."))
            return
        if created_password:
            self.stdout.write(self.style.WARNING(f"New login {TRAINING_OWNER} (owner), password: {created_password}"))
        self.stdout.write(self.style.SUCCESS("Done. The training copy starts from today's master data."))


def export_logins() -> list[dict[str, Any]]:
    """The accounts made in the training copy. Copied production accounts have an unusable password, so they are out."""
    logins: list[dict[str, Any]] = []
    for user in User.objects.order_by("username").prefetch_related("memberships"):
        if not user.has_usable_password():
            continue
        logins.append(
            {
                "username": user.username,
                "password": user.password,  # the hash, never the password itself
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "language": user.language,
                "is_active": user.is_active,
                "memberships": [
                    {
                        "organization": membership.organization_id,
                        "role": membership.role,
                        "is_active": membership.is_active,
                        "can_buy": membership.can_buy,
                    }
                    for membership in user.memberships.all()
                ],
            }
        )
    return logins


def empty_work() -> list[tuple[str, int]]:
    """Delete every organization-scoped row that is not master data. Returns the rows deleted per table."""
    report: list[tuple[str, int]] = []
    with connection.cursor() as cursor:
        for model in apps.get_models():
            if not issubclass(model, OrganizationScopedModel) or model in KEPT_MODELS:
                continue
            cursor.execute(f"DELETE FROM {connection.ops.quote_name(model._meta.db_table)}")
            if cursor.rowcount:
                report.append((model._meta.label, cursor.rowcount))
        # The sessions of production's browsers mean nothing here.
        cursor.execute("DELETE FROM django_session")
    # Money starts at zero: no cash in the Caisse or the banks before the trainees put some. Trucks keep their
    # place; the driver is chosen again on the day (D-042), as after the client start (D-146).
    TreasuryAccount.objects.update(opening_balance=0, opening_on=None)
    Truck.objects.update(driver=None)
    return report


def lock_copied_accounts() -> int:
    """Production's accounts stay (kept rows name them) but cannot log in to the training copy."""
    users = list(User.objects.all())
    for user in users:
        user.set_unusable_password()
        user.is_active = False
    User.objects.bulk_update(users, ["password", "is_active"])
    return len(users)


def restore_logins(logins: list[dict[str, Any]]) -> str | None:
    """Put the training logins back; create the `formation` owner when none is called so. Returns its new password."""
    organizations = {organization.pk: organization for organization in Organization.objects.all()}
    for login in logins:
        user, _created = User.objects.get_or_create(username=login["username"])
        user.password = login["password"]
        user.first_name = login["first_name"]
        user.last_name = login["last_name"]
        user.email = login["email"]
        user.language = login["language"]
        user.is_active = login["is_active"]
        user.save()
        # A production account of the same name becomes the training login: its own roles go.
        user.memberships.all().delete()
        for membership in login["memberships"]:
            organization = organizations.get(membership["organization"])
            if organization is None:
                continue
            Membership.objects.create(
                user=user,
                organization=organization,
                role=membership["role"],
                is_active=membership["is_active"],
                can_buy=membership["can_buy"],
            )

    if any(login["username"] == TRAINING_OWNER for login in logins):
        return None
    password = secrets.token_urlsafe(12)
    owner, _created = User.objects.get_or_create(username=TRAINING_OWNER)
    owner.first_name = "Formation"
    owner.is_active = True
    owner.set_password(password)
    owner.save()
    owner.memberships.all().delete()
    for organization in organizations.values():
        Membership.objects.create(user=owner, organization=organization, role=Role.OWNER)
    return password
