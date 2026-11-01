"""Every write on expenses goes through these functions (ARCHITECTURE §3)."""

import datetime as dt
import uuid
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from apps.core import audit, numbering
from apps.core.images import reencoded_photo
from apps.core.models import Organization, User
from apps.core.money import Number, checked_amount
from apps.inventory.services import LocationKind

from . import cost_selectors
from .costing import first_of_month, last_of_month, room_month_amounts
from .models import (
    ColdRoomEstimate,
    ColdRoomMonthRate,
    ColdRoomWeight,
    DayLabourEntry,
    DayLabourer,
    ElectricityBill,
    Expense,
    ExpenseCategory,
    ExpensePaymentMethod,
    ExpenseStatus,
    GeneralCostPeriod,
    LotCostAdjustment,
    LotCostAdjustmentKind,
    RecurringCost,
    WorkType,
)

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

    from apps.fleet.models import Truck
    from apps.inventory.models import Batch, StockLocation

# ---- Categories (P5-T01, D-053) ----

DAY_LABOUR = "day_labour"
# Every organization starts with these (the brief's list), in this order. Their names can be changed by the
# owner; their codes never change, so the app finds them (the day-labour calendar uses `DAY_LABOUR`).
DEFAULT_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("personnel", "Personnel"),
    (DAY_LABOUR, "Main-d'œuvre journalière"),
    ("transport", "Transport"),
    ("fuel", "Carburant"),
    ("cold_storage", "Froid et stockage"),
    ("handling", "Manutention"),
    ("rent", "Loyer"),
    ("accountant", "Comptable"),
    ("administration", "Administration"),
    ("financial", "Frais financiers"),
    ("miscellaneous", "Divers"),
)
# The owner's own categories come after the default ones.
CUSTOM_POSITION = 1000
# Offered on the driver's phone from the start; the owner changes it per category (D-205).
DRIVER_DEFAULT_CODES = ("fuel", "transport", "handling", "miscellaneous")


def ensure_default_categories(*, organization: Organization) -> None:
    """Create the default categories the organization does not have yet (by code). Safe to call again."""
    ExpenseCategory.objects.bulk_create(
        [
            ExpenseCategory(
                organization=organization,
                code=code,
                name=name,
                position=(index + 1) * 10,
                for_drivers=code in DRIVER_DEFAULT_CODES,
            )
            for index, (code, name) in enumerate(DEFAULT_CATEGORIES)
        ],
        ignore_conflicts=True,
    )


def _checked_name(organization: Organization, name: str, *, exclude_id: int | None = None) -> str:
    name = " ".join(name.split())
    if not name:
        raise ValidationError({"name": _("Indiquez un nom.")})
    if len(name) > 100:
        raise ValidationError({"name": _("100 caractères au plus.")})
    same = ExpenseCategory.objects.for_organization(organization).filter(name__iexact=name)
    if exclude_id is not None:
        same = same.exclude(pk=exclude_id)
    if same.exists():
        raise ValidationError({"name": _("Une autre catégorie porte déjà ce nom.")})
    return name


@transaction.atomic
def create_category(
    *, organization: Organization, actor: User | None, name: str, for_drivers: bool = False
) -> ExpenseCategory:
    """Add a category of the owner's own (after the default ones), offered on the drivers' phones or not."""
    category = ExpenseCategory.objects.create(
        organization=organization,
        name=_checked_name(organization, name),
        position=CUSTOM_POSITION,
        for_drivers=for_drivers,
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="expense_category.created",
        target=category,
        after={"name": name, "for_drivers": for_drivers},
    )
    return category


@transaction.atomic
def delete_category(*, category: ExpenseCategory, actor: User | None) -> None:
    """Remove a category of the owner's that was never used (D-205). A default one, or one an expense or a
    monthly cost uses, is refused: archive it instead, its records keep it."""
    category = ExpenseCategory.objects.select_for_update().get(pk=category.pk)
    if category.code:
        raise ValidationError(_("Une catégorie de base ne se supprime pas."))
    snapshot = {"name": category.name}
    try:
        with transaction.atomic():
            category.delete()
    except ProtectedError:
        raise ValidationError(_("Cette catégorie est déjà utilisée : archivez-la au lieu de la supprimer.")) from None
    audit.record(
        organization=category.organization,
        actor=actor,
        action="expense_category.deleted",
        target=None,
        before=snapshot,
    )


@transaction.atomic
def update_category(
    *,
    category: ExpenseCategory,
    actor: User | None,
    name: str | None = None,
    is_active: bool | None = None,
    for_drivers: bool | None = None,
) -> ExpenseCategory:
    """Rename a category or archive it (an archived one is no longer offered; its expenses keep it).

    The default categories can be renamed but not archived: the app relies on them.
    """
    category = ExpenseCategory.objects.select_for_update().get(pk=category.pk)
    before = {"name": category.name, "is_active": category.is_active, "for_drivers": category.for_drivers}
    if for_drivers is not None:
        category.for_drivers = for_drivers
    if name is not None:
        category.name = _checked_name(category.organization, name, exclude_id=category.pk)
    if is_active is not None:
        if not is_active and category.code:
            raise ValidationError({"is_active": _("Une catégorie de base ne s'archive pas : renommez-la si besoin.")})
        category.is_active = is_active
    category.save()
    audit.record(
        organization=category.organization,
        actor=actor,
        action="expense_category.updated",
        target=category,
        before=before,
        after={"name": category.name, "is_active": category.is_active, "for_drivers": category.for_drivers},
    )
    return category


# ---- Expenses (P5-T01, D-053) ----

MAX_RECEIPT_BYTES = 8 * 1024 * 1024
OPEN_STATUSES = frozenset({ExpenseStatus.DRAFT, ExpenseStatus.PENDING})


def _checked_expense(
    organization: Organization,
    *,
    spent_on: dt.date,
    category: ExpenseCategory,
    amount: Any,
    payment_method: str,
    batch: "Batch | None",
    truck: "Truck | None",
    for_day_labour: bool,
    current: Expense | None = None,
) -> dict[str, Any]:
    """The checked values of an expense, or a ValidationError with every problem at once."""
    errors: dict[str, str] = {}
    values: dict[str, Any] = {}
    if spent_on > timezone.localdate():
        errors["spent_on"] = _("La date ne peut pas être dans le futur.")
    if category.organization_id != organization.pk:
        errors["category"] = _("Catégorie inconnue.")
    elif not category.is_active and (current is None or current.category_id != category.pk):
        errors["category"] = _("« %(name)s » est archivée.") % {"name": category.name}
    elif (category.code == DAY_LABOUR) != for_day_labour:
        errors["category"] = (
            _("Une journée de travail se saisit dans le calendrier des journaliers.")
            if not for_day_labour
            else _("Catégorie inconnue.")
        )
    try:
        values["amount"] = checked_amount(amount)
        if values["amount"] <= 0:
            errors["amount"] = _("Indiquez un montant supérieur à zéro.")
    except (ValueError, TypeError):
        errors["amount"] = _("Indiquez un montant en DT, au millime près.")
    if payment_method not in ExpensePaymentMethod.values:
        errors["payment_method"] = _("Mode de paiement inconnu.")
    if batch is not None and truck is not None:
        errors["truck"] = _("Une dépense va sur un lot ou sur un camion, pas les deux.")
    if batch is not None:
        if batch.organization_id != organization.pk:
            errors["batch"] = _("Lot inconnu.")
        elif spent_on < batch.received_on:
            errors["batch"] = _("Le lot %(number)s est arrivé le %(date)s, après cette date.") % {
                "number": batch.number,
                "date": date_format(batch.received_on, "SHORT_DATE_FORMAT"),
            }
    if truck is not None and truck.organization_id != organization.pk:
        errors["truck"] = _("Camion inconnu.")
    if errors:
        raise ValidationError(errors)
    return values


def _snapshot(expense: Expense) -> dict[str, Any]:
    return {
        "number": expense.number,
        "status": expense.status,
        "spent_on": expense.spent_on.isoformat(),
        "category": expense.category.name,
        "amount": str(expense.amount),
        "payment_method": expense.payment_method,
        "description": expense.description,
        "payee": expense.payee,
        "batch": expense.batch.number if expense.batch is not None else None,
        "truck": str(expense.truck.location.name) if expense.truck is not None else None,
    }


def _clean(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


@transaction.atomic
def create_expense(
    *,
    organization: Organization,
    actor: User | None,
    spent_on: dt.date,
    category: ExpenseCategory,
    amount: Number,
    payment_method: str = ExpensePaymentMethod.CASH,
    description: str = "",
    payee: str = "",
    notes: str = "",
    batch: "Batch | None" = None,
    truck: "Truck | None" = None,
    client_uuid: uuid.UUID | None = None,
    submit: bool = False,
    made_at: dt.datetime | None = None,
    approve: bool = False,
    for_day_labour: bool = False,
) -> Expense:
    """Record an expense as a draft. With `submit` it waits for approval (how a driver's expense from the
    phone arrives, P3-T04); with `approve` the owner or a manager approves it at once (same transaction).

    `batch` charges it to one lot; `truck` makes it a truck cost of that day, split over the lots loaded
    on the truck that day. A day labourer's day is recorded through `create_day_labour` (`for_day_labour`
    is for that function only). A `client_uuid` already used returns that expense.
    """
    if client_uuid is not None:
        existing = Expense.objects.for_organization(organization).filter(client_uuid=client_uuid).first()
        if existing is not None:
            return existing
    values = _checked_expense(
        organization,
        spent_on=spent_on,
        category=category,
        amount=amount,
        payment_method=payment_method,
        batch=batch,
        truck=truck,
        for_day_labour=for_day_labour,
    )
    expense = Expense.objects.create(
        organization=organization,
        number=numbering.next_number(organization, "expense"),
        status=ExpenseStatus.PENDING if submit else ExpenseStatus.DRAFT,
        spent_on=spent_on,
        made_at=made_at,
        category=category,
        amount=values["amount"],
        payment_method=payment_method,
        description=_clean(description, 255),
        payee=_clean(payee, 150),
        notes=notes.strip(),
        batch=batch,
        truck=truck,
        entered_by=actor,
        client_uuid=client_uuid,
    )
    audit.record(
        organization=organization, actor=actor, action="expense.created", target=expense, after=_snapshot(expense)
    )
    if approve:
        return approve_expense(expense=expense, actor=actor)
    return expense


def _locked(expense: Expense) -> Expense:
    """The expense locked until commit, so two decisions taken at once never both apply."""
    return (
        Expense.objects.select_for_update(of=("self",))
        .select_related("organization", "category", "batch", "truck__location")
        .get(pk=expense.pk)
    )


def _status_name(expense: Expense) -> str:
    return str(ExpenseStatus(expense.status).label).lower()


def _locked_open(expense: Expense) -> Expense:
    locked = _locked(expense)
    if locked.status not in OPEN_STATUSES:
        raise ValidationError(
            _("Cette dépense est %(status)s : elle ne se modifie plus. Une correction est une nouvelle dépense.")
            % {"status": _status_name(locked)}
        )
    return locked


def is_day_labour(expense: Expense) -> bool:
    """Whether the expense is a day labourer's day (P5-T03): it is then changed through the calendar."""
    return expense.category.code == DAY_LABOUR


def _refuse_linked(expense: Expense, linked: bool) -> None:
    """An electricity bill or a general cost (P5-T02, P5-T05) is changed through its own screen."""
    if not linked and is_linked(expense):
        raise ValidationError(_("Cette dépense se modifie depuis les coûts de chambre froide ou les frais généraux."))


@transaction.atomic
def update_expense(
    *,
    expense: Expense,
    actor: User | None,
    spent_on: dt.date,
    category: ExpenseCategory,
    amount: Number,
    payment_method: str = ExpensePaymentMethod.CASH,
    description: str = "",
    payee: str = "",
    notes: str = "",
    batch: "Batch | None" = None,
    truck: "Truck | None" = None,
    approve: bool = False,
    for_day_labour: bool = False,
    linked: bool = False,
) -> Expense:
    """Correct a draft or an expense waiting for approval (every field); with `approve`, approve it too."""
    expense = _locked_open(expense)
    if is_day_labour(expense) and not for_day_labour:
        raise ValidationError(_("Une journée de travail se modifie dans le calendrier des journaliers."))
    _refuse_linked(expense, linked)
    before = _snapshot(expense)
    values = _checked_expense(
        expense.organization,
        spent_on=spent_on,
        category=category,
        amount=amount,
        payment_method=payment_method,
        batch=batch,
        truck=truck,
        for_day_labour=for_day_labour,
        current=expense,
    )
    expense.spent_on = spent_on
    expense.category = category
    expense.amount = values["amount"]
    expense.payment_method = payment_method
    expense.description = _clean(description, 255)
    expense.payee = _clean(payee, 150)
    expense.notes = notes.strip()
    expense.batch = batch
    expense.truck = truck
    expense.save()
    audit.record(
        organization=expense.organization,
        actor=actor,
        action="expense.updated",
        target=expense,
        before=before,
        after=_snapshot(expense),
    )
    if approve:
        return approve_expense(expense=expense, actor=actor)
    return expense


@transaction.atomic
def delete_expense(*, expense: Expense, actor: User | None, for_day_labour: bool = False, linked: bool = False) -> None:
    """Delete a draft typed by mistake (its number is not reused). Anything sent for approval is refused
    instead, so its trace stays."""
    expense = _locked(expense)
    if expense.status != ExpenseStatus.DRAFT:
        raise ValidationError(_("Seul un brouillon se supprime : refusez plutôt cette dépense."))
    if is_day_labour(expense) and not for_day_labour:
        raise ValidationError(_("Une journée de travail se supprime dans le calendrier des journaliers."))
    _refuse_linked(expense, linked)
    audit.record(
        organization=expense.organization,
        actor=actor,
        action="expense.deleted",
        target=expense,
        before=_snapshot(expense),
    )
    receipt = expense.receipt.name
    storage = expense.receipt.storage
    expense.delete()
    if receipt:
        transaction.on_commit(lambda: storage.delete(receipt))


@transaction.atomic
def approve_expense(*, expense: Expense, actor: User | None) -> Expense:
    """Approve a draft or a waiting expense: from now on it counts in the costs and never changes."""
    expense = _locked_open(expense)
    if not expense.category.is_active:
        raise ValidationError({"category": _("« %(name)s » est archivée.") % {"name": expense.category.name}})
    expense.status = ExpenseStatus.APPROVED
    expense.decided_by = actor
    expense.decided_at = timezone.now()
    expense.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    audit.record(
        organization=expense.organization,
        actor=actor,
        action="expense.approved",
        target=expense,
        after={"amount": str(expense.amount)},
    )
    after_expense_approved(expense=expense, actor=actor)
    return expense


@transaction.atomic
def reject_expense(*, expense: Expense, actor: User | None, reason: str) -> Expense:
    """Refuse a draft or a waiting expense, saying why. It never counts and never changes again."""
    reason = _clean(reason, 255)
    if not reason:
        raise ValidationError({"reason": _("Indiquez pourquoi cette dépense est refusée.")})
    expense = _locked_open(expense)
    expense.status = ExpenseStatus.REJECTED
    expense.decided_by = actor
    expense.decided_at = timezone.now()
    expense.rejection_reason = reason
    expense.save(update_fields=["status", "decided_by", "decided_at", "rejection_reason", "updated_at"])
    audit.record(
        organization=expense.organization,
        actor=actor,
        action="expense.rejected",
        target=expense,
        after={"reason": reason},
    )
    return expense


def _receipt_content(upload: "UploadedFile[bytes]") -> tuple[ContentFile[bytes], str]:
    """A PDF kept as it is, or a photo turned upright, shrunk and saved as WebP; with the file name."""
    head = upload.read(5)
    upload.seek(0)
    if head == b"%PDF-":
        if upload.size is not None and upload.size > MAX_RECEIPT_BYTES:
            raise ValidationError({"receipt": _("Le fichier dépasse 8 Mo.")})
        return ContentFile(upload.read()), "receipt.pdf"
    return reencoded_photo(upload, field="receipt"), "receipt.webp"


@transaction.atomic
def add_expense_receipt(*, expense: Expense, actor: User | None, upload: "UploadedFile[bytes]") -> Expense:
    """Join the receipt (a photo or a PDF). It can be replaced while the expense is open; once approved
    or refused, a receipt can still be joined if there was none, never replaced."""
    content, name = _receipt_content(upload)
    expense = _locked(expense)
    if expense.status not in OPEN_STATUSES and expense.receipt:
        raise ValidationError({"receipt": _("Cette dépense est décidée : son justificatif ne change plus.")})
    previous = expense.receipt.name
    storage = expense.receipt.storage
    expense.receipt.save(name, content, save=False)
    try:
        expense.save(update_fields=["receipt", "updated_at"])
        audit.record(organization=expense.organization, actor=actor, action="expense.receipt_added", target=expense)
    except BaseException:
        # The file is written before the row: never leave it behind when the change is rolled back.
        if expense.receipt.name:
            expense.receipt.storage.delete(expense.receipt.name)
        raise
    if previous:
        transaction.on_commit(lambda: storage.delete(previous))
    return expense


# ---- Day labour (P5-T03, D-054) ----


def _checked_labourer(
    organization: Organization,
    *,
    name: str,
    phone: str,
    usual_daily_pay: Any,
    exclude_id: int | None = None,
) -> dict[str, Any]:
    errors: dict[str, str] = {}
    values: dict[str, Any] = {"name": " ".join(name.split()), "phone": " ".join(phone.split())[:30]}
    if not values["name"]:
        errors["name"] = _("Indiquez un nom.")
    elif len(values["name"]) > 100:
        errors["name"] = _("100 caractères au plus.")
    else:
        same = DayLabourer.objects.for_organization(organization).filter(name__iexact=values["name"])
        if exclude_id is not None:
            same = same.exclude(pk=exclude_id)
        if same.exists():
            errors["name"] = _("Un autre journalier porte déjà ce nom.")
    values["usual_daily_pay"] = None
    if usual_daily_pay not in (None, ""):
        try:
            values["usual_daily_pay"] = checked_amount(usual_daily_pay)
            if values["usual_daily_pay"] <= 0:
                errors["usual_daily_pay"] = _("Indiquez un montant supérieur à zéro, ou rien.")
        except (ValueError, TypeError):
            errors["usual_daily_pay"] = _("Indiquez un montant en DT, au millime près.")
    if errors:
        raise ValidationError(errors)
    return values


def _labourer_snapshot(labourer: DayLabourer) -> dict[str, Any]:
    return {
        "name": labourer.name,
        "phone": labourer.phone,
        "usual_daily_pay": str(labourer.usual_daily_pay) if labourer.usual_daily_pay is not None else None,
        "is_active": labourer.is_active,
    }


@transaction.atomic
def create_labourer(
    *,
    organization: Organization,
    actor: User | None,
    name: str,
    phone: str = "",
    usual_daily_pay: Number | None = None,
    notes: str = "",
) -> DayLabourer:
    """Add a day labourer: a name, a phone and what they are usually paid for a day (optional)."""
    values = _checked_labourer(organization, name=name, phone=phone, usual_daily_pay=usual_daily_pay)
    labourer = DayLabourer.objects.create(organization=organization, notes=notes.strip(), **values)
    audit.record(
        organization=organization,
        actor=actor,
        action="day_labourer.created",
        target=labourer,
        after=_labourer_snapshot(labourer),
    )
    return labourer


@transaction.atomic
def update_labourer(
    *,
    labourer: DayLabourer,
    actor: User | None,
    name: str,
    phone: str = "",
    usual_daily_pay: Number | None = None,
    notes: str = "",
    is_active: bool = True,
) -> DayLabourer:
    """Change a day labourer, or archive them (no longer offered; their days stay)."""
    labourer = DayLabourer.objects.select_for_update().get(pk=labourer.pk)
    before = _labourer_snapshot(labourer)
    values = _checked_labourer(
        labourer.organization, name=name, phone=phone, usual_daily_pay=usual_daily_pay, exclude_id=labourer.pk
    )
    for field, value in values.items():
        setattr(labourer, field, value)
    labourer.notes = notes.strip()
    labourer.is_active = is_active
    labourer.save()
    audit.record(
        organization=labourer.organization,
        actor=actor,
        action="day_labourer.updated",
        target=labourer,
        before=before,
        after=_labourer_snapshot(labourer),
    )
    return labourer


def _day_labour_values(
    organization: Organization,
    labourer: DayLabourer,
    amount: Number | None,
    work_type: str,
    *,
    current: DayLabourEntry | None = None,
) -> Number:
    """The amount paid (the labourer's usual pay when none is typed), or a ValidationError."""
    errors: dict[str, str] = {}
    if labourer.organization_id != organization.pk:
        errors["labourer"] = _("Journalier inconnu.")
    elif not labourer.is_active and (current is None or current.labourer_id != labourer.pk):
        errors["labourer"] = _("« %(name)s » est archivé.") % {"name": labourer.name}
    if work_type not in WorkType.values:
        errors["work_type"] = _("Type de travail inconnu.")
    if amount in (None, ""):
        if labourer.usual_daily_pay is None:
            errors["amount"] = _("Indiquez le montant payé : ce journalier n'a pas de paie habituelle.")
        else:
            amount = labourer.usual_daily_pay
    if errors:
        raise ValidationError(errors)
    assert amount is not None
    return amount


def _day_labour_category(organization: Organization) -> ExpenseCategory:
    ensure_default_categories(organization=organization)
    return ExpenseCategory.objects.for_organization(organization).get(code=DAY_LABOUR)


def _day_labour_snapshot(entry: DayLabourEntry) -> dict[str, Any]:
    return {"labourer": entry.labourer.name, "work_type": entry.work_type, "expense": entry.expense.number}


@transaction.atomic
def create_day_labour(
    *,
    organization: Organization,
    actor: User | None,
    labourer: DayLabourer,
    worked_on: dt.date,
    amount: Number | None = None,
    batch: "Batch | None" = None,
    work_type: str = WorkType.OTHER,
    notes: str = "",
    payment_method: str = ExpensePaymentMethod.CASH,
    approve: bool = False,
    client_uuid: uuid.UUID | None = None,
) -> DayLabourEntry:
    """Record a day worked by a day labourer, from the calendar or from a lot: the same single record,
    an expense of category day labour plus who worked (D-054). Without `amount`, their usual daily pay.
    With `batch` it is a cost of that lot; without, a general cost. With `approve`, approved at once.
    A `client_uuid` already used returns that day."""
    if client_uuid is not None:
        existing = (
            DayLabourEntry.objects.for_organization(organization).filter(expense__client_uuid=client_uuid).first()
        )
        if existing is not None:
            return existing
    amount = _day_labour_values(organization, labourer, amount, work_type)
    expense = create_expense(
        organization=organization,
        actor=actor,
        spent_on=worked_on,
        category=_day_labour_category(organization),
        amount=amount,
        payment_method=payment_method,
        description=labourer.name,
        payee=labourer.name,
        notes=notes,
        batch=batch,
        client_uuid=client_uuid,
        for_day_labour=True,
    )
    entry = DayLabourEntry.objects.create(
        organization=organization, expense=expense, labourer=labourer, work_type=work_type
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="day_labour.created",
        target=entry,
        after=_day_labour_snapshot(entry),
    )
    if approve:
        approve_expense(expense=expense, actor=actor)
        entry.expense.refresh_from_db()
    return entry


@transaction.atomic
def update_day_labour(
    *,
    entry: DayLabourEntry,
    actor: User | None,
    labourer: DayLabourer,
    worked_on: dt.date,
    amount: Number | None = None,
    batch: "Batch | None" = None,
    work_type: str = WorkType.OTHER,
    notes: str = "",
    payment_method: str = ExpensePaymentMethod.CASH,
    approve: bool = False,
) -> DayLabourEntry:
    """Correct a day not approved yet (who, which day, how much, which lot, what work)."""
    entry = DayLabourEntry.objects.select_for_update().select_related("expense", "labourer").get(pk=entry.pk)
    organization = entry.expense.organization
    before = _day_labour_snapshot(entry)
    amount = _day_labour_values(organization, labourer, amount, work_type, current=entry)
    update_expense(
        expense=entry.expense,
        actor=actor,
        spent_on=worked_on,
        category=entry.expense.category,
        amount=amount,
        payment_method=payment_method,
        description=labourer.name,
        payee=labourer.name,
        notes=notes,
        batch=batch,
        approve=approve,
        for_day_labour=True,
    )
    entry.labourer = labourer
    entry.work_type = work_type
    entry.save()
    entry.expense.refresh_from_db()
    audit.record(
        organization=organization,
        actor=actor,
        action="day_labour.updated",
        target=entry,
        before=before,
        after=_day_labour_snapshot(entry),
    )
    return entry


@transaction.atomic
def delete_day_labour(*, entry: DayLabourEntry, actor: User | None) -> None:
    """Delete a day typed by mistake, while it is a draft (with its expense: they are one record)."""
    entry = DayLabourEntry.objects.select_related("expense", "labourer").get(pk=entry.pk)
    audit.record(
        organization=entry.expense.organization,
        actor=actor,
        action="day_labour.deleted",
        target=entry,
        before=_day_labour_snapshot(entry),
    )
    delete_expense(expense=entry.expense, actor=actor, for_day_labour=True)


# ---- Cold-room cost and general costs (P5-T02, P5-T05, D-058, D-059) ----

COLD_STORAGE = "cold_storage"
MAX_WEIGHT = Decimal("1000.000")
MAX_MONTHS = 60


def is_linked(expense: Expense) -> bool:
    """Whether the expense is the other half of an electricity bill or a general cost: then it is changed
    or deleted through those records, never alone."""
    return (
        ElectricityBill.objects.filter(expense=expense).exists()
        or GeneralCostPeriod.objects.filter(expense=expense).exists()
    )


def _category(organization: Organization, code: str) -> ExpenseCategory:
    ensure_default_categories(organization=organization)
    return ExpenseCategory.objects.for_organization(organization).get(code=code)


def _month(value: dt.date, field: str) -> dt.date:
    if value.day != 1:
        raise ValidationError({field: _("Indiquez le premier jour du mois.")})
    return value


# ---- Weights of the cold rooms ----


@transaction.atomic
def set_cold_room_weight(
    *, organization: Organization, actor: User | None, location: "StockLocation", weight: Number
) -> ColdRoomWeight:
    """Set how much of the electricity bill a cold room takes (relative to the others; default 1). It is
    read when a bill is approved: months already billed keep the weights they were billed with."""
    if location.organization_id != organization.pk or location.kind != LocationKind.COLD_ROOM:
        raise ValidationError({"location": _("Chambre froide inconnue.")})
    try:
        value = Decimal(str(weight))
        if value != value.quantize(Decimal("0.001")) or value <= 0 or value > MAX_WEIGHT:
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValidationError({"weight": _("Indiquez un poids supérieur à zéro, au millième près.")}) from None
    row = ColdRoomWeight.objects.for_organization(organization).filter(location=location).first()
    before = str(row.weight) if row is not None else None
    if row is None:
        row = ColdRoomWeight(organization=organization, location=location)
    row.weight = value.quantize(Decimal("0.001"))
    row.save()
    audit.record(
        organization=organization,
        actor=actor,
        action="cold_room_weight.set",
        target=row,
        before={"weight": before},
        after={"room": location.name, "weight": str(row.weight)},
    )
    return row


@transaction.atomic
def set_cold_room_shares(
    *, organization: Organization, actor: User | None, shares: Mapping[int, Number]
) -> list[ColdRoomWeight]:
    """Set every active cold room's share of the electricity bill in %, all at once: they must cover every
    active room and add up to exactly 100 %. A share is stored as the room's weight, so the split stays
    proportional. Months already billed keep the shares they were billed with."""
    rooms = {room.pk: room for room in cost_selectors.cold_rooms(organization)}
    if set(shares) != set(rooms):
        raise ValidationError({"shares": _("Indiquez la part de chaque chambre froide active.")})
    values: dict[int, Decimal] = {}
    for room_id, raw in shares.items():
        try:
            value = Decimal(str(raw))
            if value != value.quantize(Decimal("0.001")) or value <= 0 or value > 100:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValidationError({"shares": _("Chaque part doit être supérieure à zéro, au millième près.")}) from None
        values[room_id] = value.quantize(Decimal("0.001"))
    if sum(values.values(), Decimal("0")) != Decimal("100.000"):
        raise ValidationError({"shares": _("Les parts doivent faire 100 % au total.")})
    return [
        set_cold_room_weight(organization=organization, actor=actor, location=rooms[room_id], weight=value)
        for room_id, value in values.items()
    ]


@transaction.atomic
def set_cold_room_estimate(
    *, organization: Organization, actor: User | None, month: dt.date, amount: Number, reason: str = ""
) -> ColdRoomEstimate:
    """Type the electricity estimate of a month for all the cold rooms (D-227): the rooms share it by weight
    and the lots are charged it until the month's bill is approved. The month must be the current one or
    an earlier one; once the bill is approved the estimate is frozen."""
    _month(month, "month")
    if month > first_of_month(timezone.localdate()):
        raise ValidationError({"month": _("L'estimation se saisit pour le mois en cours ou un mois passé.")})
    if ElectricityBill.objects.for_organization(organization).filter(month=month, finalized_at__isnull=False).exists():
        raise ValidationError({"month": _("La facture de ce mois est approuvée : l'estimation est figée.")})
    try:
        value = checked_amount(amount)
    except (ValueError, TypeError):
        raise ValidationError({"amount": _("Indiquez un montant en DT, au millime près.")}) from None
    if value <= 0:
        raise ValidationError({"amount": _("Indiquez un montant supérieur à zéro.")})
    row = ColdRoomEstimate.objects.for_organization(organization).filter(month=month).first()
    before = str(row.amount) if row is not None else None
    if row is None:
        row = ColdRoomEstimate(organization=organization, month=month)
    row.amount = value
    row.save()
    audit.record(
        organization=organization,
        actor=actor,
        action="cold_room_estimate.set",
        target=row,
        before={"amount": before},
        after={"month": month.isoformat(), "amount": str(value), "reason": reason.strip()},
    )
    return row


# ---- Electricity bills ----


def _bill_snapshot(bill: ElectricityBill) -> dict[str, Any]:
    return {
        "month": bill.month.isoformat(),
        "amount": str(bill.expense.amount),
        "expense": bill.expense.number,
        "status": bill.expense.status,
    }


def _checked_bill_month(organization: Organization, month: dt.date) -> None:
    _month(month, "month")
    Organization.objects.select_for_update().filter(pk=organization.pk).first()  # one bill per month at a time
    if month >= first_of_month(timezone.localdate()):
        raise ValidationError({"month": _("La facture se saisit une fois le mois terminé.")})
    existing = ElectricityBill.objects.for_organization(organization).filter(month=month).select_related("expense")
    for bill in existing:
        if bill.expense.status == ExpenseStatus.REJECTED:
            bill.delete()  # the refused expense stays as a trace; the month can be billed again
        else:
            raise ValidationError({"month": _("Ce mois a déjà une facture d'électricité.")})


@transaction.atomic
def create_electricity_bill(
    *,
    organization: Organization,
    actor: User | None,
    month: dt.date,
    amount: Number,
    payment_method: str = ExpensePaymentMethod.TRANSFER,
    payee: str = "",
    notes: str = "",
    approve: bool = False,
    client_uuid: uuid.UUID | None = None,
) -> ElectricityBill:
    """Type the electricity bill of a finished month: one expense (cold storage, dated the last day of the
    month) plus the month it is for. A draft until approved; approving freezes the rooms' shares and books
    the difference with the estimate on each lot (`finalize_bill`)."""
    _checked_bill_month(organization, month)
    expense = create_expense(
        organization=organization,
        actor=actor,
        spent_on=last_of_month(month),
        category=_category(organization, COLD_STORAGE),
        amount=amount,
        payment_method=payment_method,
        description=_("Électricité %(month)s") % {"month": f"{month:%m/%Y}"},
        payee=payee,
        notes=notes,
        client_uuid=client_uuid,
    )
    bill = ElectricityBill.objects.create(organization=organization, month=month, expense=expense)
    audit.record(
        organization=organization,
        actor=actor,
        action="electricity_bill.created",
        target=bill,
        after=_bill_snapshot(bill),
    )
    if approve:
        approve_expense(expense=expense, actor=actor)
    return cost_selectors.bill_of(organization, bill.pk)


@transaction.atomic
def update_electricity_bill(
    *,
    bill: ElectricityBill,
    actor: User | None,
    amount: Number,
    payment_method: str = ExpensePaymentMethod.TRANSFER,
    payee: str = "",
    notes: str = "",
    approve: bool = False,
) -> ElectricityBill:
    """Correct a bill not approved yet (amount, payment, payee, notes)."""
    bill = ElectricityBill.objects.select_related("expense__category", "organization").get(pk=bill.pk)
    before = _bill_snapshot(bill)
    update_expense(
        expense=bill.expense,
        actor=actor,
        spent_on=bill.expense.spent_on,
        category=bill.expense.category,
        amount=amount,
        payment_method=payment_method,
        description=bill.expense.description,
        payee=payee,
        notes=notes,
        approve=approve,
        linked=True,
    )
    bill = cost_selectors.bill_of(bill.organization, bill.pk)
    audit.record(
        organization=bill.organization,
        actor=actor,
        action="electricity_bill.updated",
        target=bill,
        before=before,
        after=_bill_snapshot(bill),
    )
    return bill


@transaction.atomic
def delete_electricity_bill(*, bill: ElectricityBill, actor: User | None) -> None:
    """Delete a bill typed by mistake while it is a draft (with its expense: they are one record)."""
    bill = ElectricityBill.objects.select_related("expense__category", "organization").get(pk=bill.pk)
    audit.record(
        organization=bill.organization,
        actor=actor,
        action="electricity_bill.deleted",
        target=bill,
        before=_bill_snapshot(bill),
    )
    delete_expense(expense=bill.expense, actor=actor, linked=True)


def after_expense_approved(*, expense: Expense, actor: User | None) -> None:
    """Called by `approve_expense`: an approved electricity bill freezes the month's shares."""
    bill = ElectricityBill.objects.filter(expense=expense).select_related("organization", "expense").first()
    if bill is not None and bill.finalized_at is None:
        finalize_bill(bill=bill, actor=actor)


def finalize_bill(*, bill: ElectricityBill, actor: User | None) -> list[LotCostAdjustment]:
    """Freeze an approved bill and correct the lots (D-041, D-058).

    The bill is shared between the active cold rooms by weight (to the millime, adding up exactly); each
    room's part and weight are kept, with the estimate's daily rate that had been in force. Then for every
    lot that spent days in a room that month, the real cost minus the estimate becomes a
    `LotCostAdjustment` dated today: a lot already closed is never reopened, a later settlement picks the
    line up. Immutable afterwards.
    """
    organization = bill.organization
    weights = cost_selectors.room_weights(organization)
    if not weights:
        raise ValidationError(_("Aucune chambre froide : créez-en une avant d'approuver la facture."))
    amounts = room_month_amounts(bill.expense.amount, weights)
    estimate = cost_selectors.estimate_for_new_bill(organization, month=bill.month)
    source = estimate.source_month
    estimates = estimate.day_amounts
    ColdRoomMonthRate.objects.bulk_create(
        ColdRoomMonthRate(
            organization=organization,
            bill=bill,
            location_id=room_id,
            weight=weights[room_id],
            month_amount=amounts[room_id],
            estimate_day_amount=estimates.get(room_id),
        )
        for room_id in weights
    )
    bill.finalized_at = timezone.now()
    bill.estimate_source_month = source
    bill.save(update_fields=["finalized_at", "estimate_source_month", "updated_at"])
    differences = cost_selectors.bill_adjustments(
        organization,
        month=bill.month,
        rates={room_id: (amounts[room_id], estimates.get(room_id)) for room_id in weights},
    )
    today = timezone.localdate()
    adjustments = LotCostAdjustment.objects.bulk_create(
        LotCostAdjustment(
            organization=organization,
            kind=LotCostAdjustmentKind.COLD_ROOM,
            batch_id=difference.batch_id,
            location_id=difference.location_id,
            month=bill.month,
            amount=difference.amount,
            dated_on=today,
            bill=bill,
        )
        for difference in differences
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="electricity_bill.finalized",
        target=bill,
        after={
            "month": bill.month.isoformat(),
            "rooms": {str(room_id): str(amount) for room_id, amount in amounts.items()},
            "adjustments": len(adjustments),
            "estimate_source_month": source.isoformat() if source is not None else None,
            "estimate_typed": estimate.typed,
        },
    )
    return adjustments


# ---- Recurring general costs and bills over several months (P5-T05, D-059) ----


def _checked_general_category(organization: Organization, category: ExpenseCategory) -> None:
    if category.organization_id != organization.pk or not category.is_active or category.code == DAY_LABOUR:
        raise ValidationError({"category": _("Catégorie inconnue.")})


def _checked_monthly(amount: Number) -> Decimal:
    try:
        value = checked_amount(amount)
    except (ValueError, TypeError):
        raise ValidationError({"monthly_amount": _("Indiquez un montant en DT, au millime près.")}) from None
    if value <= 0:
        raise ValidationError({"monthly_amount": _("Indiquez un montant supérieur à zéro.")})
    return value


def _checked_range(start_month: dt.date, end_month: dt.date | None) -> None:
    _month(start_month, "start_month")
    if end_month is not None:
        _month(end_month, "end_month")
        if end_month < start_month:
            raise ValidationError({"end_month": _("Le dernier mois précède le premier.")})


def _recurring_snapshot(cost: RecurringCost) -> dict[str, Any]:
    return {
        "name": cost.name,
        "category": cost.category.name,
        "monthly_amount": str(cost.monthly_amount),
        "start_month": cost.start_month.isoformat(),
        "end_month": cost.end_month.isoformat() if cost.end_month else None,
        "is_active": cost.is_active,
    }


def _checked_cost_name(organization: Organization, name: str, *, exclude_id: int | None = None) -> str:
    name = " ".join(name.split())
    if not name:
        raise ValidationError({"name": _("Indiquez un nom.")})
    same = RecurringCost.objects.for_organization(organization).filter(name__iexact=name)
    if exclude_id is not None:
        same = same.exclude(pk=exclude_id)
    if same.exists():
        raise ValidationError({"name": _("Un autre frais récurrent porte déjà ce nom.")})
    return name[:100]


@transaction.atomic
def create_recurring_cost(
    *,
    organization: Organization,
    actor: User | None,
    name: str,
    category: ExpenseCategory,
    monthly_amount: Number,
    start_month: dt.date,
    end_month: dt.date | None = None,
    payment_method: str = ExpensePaymentMethod.TRANSFER,
    payee: str = "",
) -> RecurringCost:
    """Add a monthly cost (rent, accountant, insurance): a template that generates the month's expense."""
    _checked_general_category(organization, category)
    _checked_range(start_month, end_month)
    if payment_method not in ExpensePaymentMethod.values:
        raise ValidationError({"payment_method": _("Mode de paiement inconnu.")})
    cost = RecurringCost.objects.create(
        organization=organization,
        name=_checked_cost_name(organization, name),
        category=category,
        monthly_amount=_checked_monthly(monthly_amount),
        payment_method=payment_method,
        payee=" ".join(payee.split())[:150],
        start_month=start_month,
        end_month=end_month,
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="recurring_cost.created",
        target=cost,
        after=_recurring_snapshot(cost),
    )
    return cost


@transaction.atomic
def update_recurring_cost(
    *,
    cost: RecurringCost,
    actor: User | None,
    name: str,
    category: ExpenseCategory,
    monthly_amount: Number,
    start_month: dt.date,
    end_month: dt.date | None = None,
    payment_method: str = ExpensePaymentMethod.TRANSFER,
    payee: str = "",
    is_active: bool = True,
) -> RecurringCost:
    """Change a template, or stop it (`is_active` false). A month already generated takes the change while its
    expense is still a draft or waiting for approval; an approved month keeps its amount (D-128)."""
    cost = RecurringCost.objects.select_for_update().select_related("category", "organization").get(pk=cost.pk)
    organization = cost.organization
    before = _recurring_snapshot(cost)
    if category.pk != cost.category_id:
        _checked_general_category(organization, category)
    _checked_range(start_month, end_month)
    if payment_method not in ExpensePaymentMethod.values:
        raise ValidationError({"payment_method": _("Mode de paiement inconnu.")})
    cost.name = _checked_cost_name(organization, name, exclude_id=cost.pk)
    cost.category = category
    cost.monthly_amount = _checked_monthly(monthly_amount)
    cost.payment_method = payment_method
    cost.payee = " ".join(payee.split())[:150]
    cost.start_month = start_month
    cost.end_month = end_month
    cost.is_active = is_active
    cost.save()
    audit.record(
        organization=organization,
        actor=actor,
        action="recurring_cost.updated",
        target=cost,
        before=before,
        after=_recurring_snapshot(cost),
    )
    open_periods = GeneralCostPeriod.objects.filter(recurring=cost, expense__status__in=OPEN_STATUSES).select_related(
        "expense"
    )
    for period in open_periods:
        expense = period.expense
        update_expense(
            expense=expense,
            actor=actor,
            spent_on=expense.spent_on,
            category=cost.category,
            amount=cost.monthly_amount,
            payment_method=cost.payment_method,
            description=cost.name,
            payee=cost.payee,
            notes=expense.notes,
            linked=True,
        )
    return cost


def _general_expense(
    *,
    organization: Organization,
    actor: User | None,
    spent_on: dt.date,
    category: ExpenseCategory,
    amount: Number,
    payment_method: str,
    description: str,
    payee: str,
    notes: str,
    first_month: dt.date,
    months: int,
    recurring: RecurringCost | None = None,
) -> GeneralCostPeriod:
    expense = create_expense(
        organization=organization,
        actor=actor,
        spent_on=spent_on,
        category=category,
        amount=amount,
        payment_method=payment_method,
        description=description,
        payee=payee,
        notes=notes,
    )
    period = GeneralCostPeriod.objects.create(
        organization=organization, expense=expense, first_month=first_month, months=months, recurring=recurring
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="general_cost.created",
        target=period,
        after={"expense": expense.number, "first_month": first_month.isoformat(), "months": months},
    )
    return period


@transaction.atomic
def generate_recurring_costs(
    *, organization: Organization, actor: User | None, month: dt.date, approve: bool = False
) -> list[GeneralCostPeriod]:
    """Generate the month's expense of every active template that applies to it and has none yet (safe to
    run again). The expense is dated the first of the month, a draft unless `approve`. Not for a future
    month. A template whose category was archived is skipped (named in the audit log); one whose expense was
    refused is generated again."""
    _month(month, "month")
    if month > timezone.localdate():
        raise ValidationError({"month": _("Ce mois n'a pas commencé.")})
    Organization.objects.select_for_update().filter(pk=organization.pk).first()  # one generation at a time
    created: list[GeneralCostPeriod] = []
    skipped: list[str] = []
    for cost in cost_selectors.recurring_costs_of(organization, active_only=True):
        if cost.start_month > month or (cost.end_month is not None and cost.end_month < month):
            continue
        done = GeneralCostPeriod.objects.filter(recurring=cost, first_month=month).select_related("expense").first()
        if done is not None:
            if done.expense.status != ExpenseStatus.REJECTED:
                continue
            done.delete()  # the refused expense stays as a trace; the month can be generated again
        if not cost.category.is_active:
            skipped.append(cost.name)
            continue
        period = _general_expense(
            organization=organization,
            actor=actor,
            spent_on=month,
            category=cost.category,
            amount=cost.monthly_amount,
            payment_method=cost.payment_method,
            description=cost.name,
            payee=cost.payee,
            notes="",
            first_month=month,
            months=1,
            recurring=cost,
        )
        if approve:
            approve_expense(expense=period.expense, actor=actor)
            period.expense.refresh_from_db()
        created.append(period)
    if skipped:
        audit.record(
            organization=organization,
            actor=actor,
            action="recurring_cost.skipped",
            after={"month": month.isoformat(), "archived_category": skipped},
        )
    return created


@transaction.atomic
def create_general_cost(
    *,
    organization: Organization,
    actor: User | None,
    spent_on: dt.date,
    category: ExpenseCategory,
    amount: Number,
    first_month: dt.date,
    months: int = 1,
    payment_method: str = ExpensePaymentMethod.TRANSFER,
    description: str = "",
    payee: str = "",
    notes: str = "",
    approve: bool = False,
) -> GeneralCostPeriod:
    """A bill covering one or several months (an insurance for a year): one expense, spread equally over
    the months it covers; each month's part is then charged to the lots "like a salary" (D-059)."""
    _checked_general_category(organization, category)
    _month(first_month, "first_month")
    if not 1 <= months <= MAX_MONTHS:
        raise ValidationError({"months": _("Entre 1 et %(max)s mois.") % {"max": MAX_MONTHS}})
    period = _general_expense(
        organization=organization,
        actor=actor,
        spent_on=spent_on,
        category=category,
        amount=amount,
        payment_method=payment_method,
        description=description,
        payee=payee,
        notes=notes,
        first_month=first_month,
        months=months,
    )
    if approve:
        approve_expense(expense=period.expense, actor=actor)
    return cost_selectors.general_period_of(organization, period.pk)


@transaction.atomic
def delete_general_cost(*, period: GeneralCostPeriod, actor: User | None) -> None:
    """Delete a general cost typed by mistake while it is a draft (with its expense)."""
    period = GeneralCostPeriod.objects.select_related("expense__category", "organization").get(pk=period.pk)
    audit.record(
        organization=period.organization,
        actor=actor,
        action="general_cost.deleted",
        target=period,
        before={"expense": period.expense.number, "first_month": period.first_month.isoformat()},
    )
    delete_expense(expense=period.expense, actor=actor, linked=True)


@transaction.atomic
def submit_road_expense(
    *,
    organization: Organization,
    actor: User,
    truck: "Truck",
    category: ExpenseCategory,
    amount: Number,
    description: str = "",
    upload: "UploadedFile[bytes] | None" = None,
    client_uuid: uuid.UUID | None = None,
    made_at: dt.datetime | None = None,
    payment_method: str = ExpensePaymentMethod.CASH,
    paid_by_driver: bool = False,
) -> Expense:
    """A driver's expense from the road (P3-T04): today, a cost of their truck that day, waiting for the
    office to approve it. The receipt photo, when given, is joined in the same transaction.

    Paid with the day's cash, out of the driver's own pocket (`paid_by_driver`: owed to them), or by card or
    another way (`payment_method`), whatever cash the day holds (D-205)."""
    if not category.for_drivers or not category.is_active:
        raise ValidationError({"category": _("Cette catégorie n'est pas disponible depuis la route.")})
    if client_uuid is not None:
        # A retry of an entry already saved (a phone resending after a lost answer): answer with it as it is, even
        # when the office decided it meanwhile and its receipt can no longer change.
        existing = Expense.objects.for_organization(organization).filter(client_uuid=client_uuid).first()
        if existing is not None:
            return existing
    expense = create_expense(
        organization=organization,
        actor=actor,
        # Dated by the moment it was spent (the phone's time, when there is one), else today.
        spent_on=timezone.localtime(made_at or timezone.now()).date(),
        category=category,
        amount=amount,
        description=description,
        truck=truck,
        client_uuid=client_uuid,
        submit=True,
        made_at=made_at,
        payment_method=payment_method,
    )
    if paid_by_driver:
        expense.paid_by_driver = True
        expense.save(update_fields=["paid_by_driver", "updated_at"])
    if upload is not None:
        expense = add_expense_receipt(expense=expense, actor=actor, upload=upload)
    return expense
