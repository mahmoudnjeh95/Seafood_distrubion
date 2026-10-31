import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, TimeStampedModel
from apps.core.money import MoneyField

# ---- Expenses (P5-T01, D-053) ----


class ExpenseCategory(OrganizationScopedModel, TimeStampedModel):
    """What an expense is for: fuel, transport, rent... Every organization starts with the default ones
    (`services.DEFAULT_CATEGORIES`, which carry a `code`); the owner adds others (no code), renames any and
    archives his own."""

    # Set on the default categories only ("fuel", "day_labour"...): code finds them whatever their name.
    code = models.CharField(max_length=30, blank=True)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    # Offered on the driver's phone (D-205): fuel, transport, handling and miscellaneous at first; the owner
    # chooses the others.
    for_drivers = models.BooleanField(default=False)
    # Order in lists: the default ones in the order of the brief, the owner's after them.
    position = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["position", "name", "id"]
        verbose_name_plural = "expense categories"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                condition=~models.Q(code=""),
                name="expense_category_code_unique_per_organization",
            ),
            models.UniqueConstraint(
                "organization", Lower("name"), name="expense_category_name_unique_per_organization"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ExpenseStatus(models.TextChoices):
    # Typed at the office, still being checked: it changes freely and can be deleted.
    DRAFT = "draft", _("Brouillon")
    # Sent for approval (a driver's expense from the phone, P3-T04): it can still be corrected.
    PENDING = "pending", _("À approuver")
    # Approved by the owner or a manager: it counts in the costs and never changes again.
    APPROVED = "approved", _("Approuvée")
    # Refused, with a reason: it never counts.
    REJECTED = "rejected", _("Refusée")


class ExpensePaymentMethod(models.TextChoices):
    # The same list as supplier payments (D-043), so the API has one payment method type.
    CASH = "cash", _("Espèces")
    CHEQUE = "cheque", _("Chèque")
    TRANSFER = "transfer", _("Virement")
    BILL = "bill", _("Traite")
    OTHER = "other", _("Autre")


class LotCostKind(models.TextChoices):
    """Where a cost line of a lot comes from (`selectors.lot_cost_lines`); not stored."""

    # An expense typed on the lot.
    LOT = "lot", _("Sur le lot")
    # The lot's share of a truck's costs on a day it was loaded (by kg loaded).
    TRUCK_DAY = "truck_day", _("Frais du camion du jour")
    # The lot's share of a cold room's electricity, by kg held per day (P5-T02, D-058). Estimated until the
    # month's bill is typed.
    COLD_ROOM = "cold_room", _("Chambre froide")
    # The difference between the estimate and the real bill, dated when the bill was typed (D-041).
    COLD_ROOM_ADJUSTMENT = "cold_room_adjustment", _("Correction chambre froide")
    # The lot's share of rent, accountant and other general costs, "like a salary" (P5-T05, D-059).
    GENERAL = "general", _("Frais généraux")


def receipt_path(expense: "Expense", filename: str) -> str:
    # A random name: the receipt's address cannot be guessed from the expense number.
    extension = ".pdf" if filename.lower().endswith(".pdf") else ".webp"
    return f"expenses/{expense.organization_id}/{uuid.uuid4().hex}{extension}"


class Expense(OrganizationScopedModel, TimeStampedModel):
    """Money spent on something other than goods: fuel, transport, rent, a day labourer...

    It may be charged to one lot (`batch`): then it is a cost of that lot. Tagged to a truck instead, it is a
    truck cost of that day, split over the lots loaded on the truck that day by kg (D-041, D-053). With
    neither it is a general cost. Only an approved expense counts; once approved or refused it never
    changes (a correction is a new expense).
    """

    # "DP-0001", "DP-0002"... per organization, given by the services.
    number = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=ExpenseStatus.choices, default=ExpenseStatus.DRAFT)
    spent_on = models.DateField()
    # When the driver's phone says it was spent (D-133); empty for an expense entered at the office.
    made_at = models.DateTimeField(null=True, blank=True)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    amount = MoneyField()
    # Paid by the driver out of their own pocket on the road (D-205): owed to them, not taken from the day's cash.
    paid_by_driver = models.BooleanField(default=False)
    payment_method = models.CharField(
        max_length=20, choices=ExpensePaymentMethod.choices, default=ExpensePaymentMethod.CASH
    )
    # What it was: "Gasoil", "Glace pour le camion"...
    description = models.CharField(max_length=255, blank=True)
    # Who was paid, as written on the receipt ("Station Agil Sakiet Ezzit").
    payee = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    # By name, not by import: an app only uses another app's services and selectors (ARCHITECTURE §3).
    batch = models.ForeignKey("inventory.Batch", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    truck = models.ForeignKey("fleet.Truck", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    # The receipt or invoice: a photo (stored as WebP) or a PDF.
    receipt = models.FileField(upload_to=receipt_path, blank=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    # The driver app sends expenses from the road (P3-T04) and may retry (ARCHITECTURE §4.7).
    client_uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["-spent_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="expense_number_unique_per_organization"),
            models.UniqueConstraint(
                fields=["organization", "client_uuid"],
                condition=models.Q(client_uuid__isnull=False),
                name="expense_client_uuid_unique_per_organization",
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=Decimal("0")), name="expense_amount_positive"),
            models.CheckConstraint(
                condition=models.Q(batch__isnull=True) | models.Q(truck__isnull=True),
                name="expense_lot_or_truck_not_both",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "spent_on"], name="expense_status_day_idx"),
            models.Index(fields=["organization", "truck", "spent_on"], name="expense_truck_day_idx"),
            models.Index(fields=["organization", "batch"], name="expense_lot_idx"),
        ]

    def __str__(self) -> str:
        return self.number


# ---- Day labour (P5-T03, D-054) ----


class DayLabourer(OrganizationScopedModel, TimeStampedModel):
    """Someone paid by the day when there is work (unloading, sorting, cleaning). Not an employee: no
    payroll, no CNSS (P5-T04 is for employees)."""

    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    # What they are usually paid for a day: proposed when a day is added. Empty when it varies.
    usual_daily_pay = models.DecimalField[Decimal | None, Decimal | None](
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint("organization", Lower("name"), name="day_labourer_name_unique_per_organization"),
            models.CheckConstraint(
                condition=models.Q(usual_daily_pay__isnull=True) | models.Q(usual_daily_pay__gt=Decimal("0")),
                name="day_labourer_pay_positive",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class WorkType(models.TextChoices):
    # What the day was spent on (client meeting §6); "other" when nobody says.
    LOADING = "loading", _("Chargement, déchargement")
    STOCK = "stock", _("Rangement du stock")
    STORE = "store", _("Magasin")
    CLEANING = "cleaning", _("Nettoyage")
    OTHER = "other", _("Autre")


class DayLabourEntry(OrganizationScopedModel, TimeStampedModel):
    """One day worked by a day labourer, and what they were paid.

    It is **one record with its expense** (category day labour): the expense carries the day, the amount,
    the lot and the approval; this row adds who worked and on what. Typed from a lot or from the calendar,
    it is the same record, so it is never counted twice (D-041, D-054). Without a lot it is a general cost.
    """

    expense = models.OneToOneField(Expense, on_delete=models.CASCADE, related_name="day_labour")
    labourer = models.ForeignKey(DayLabourer, on_delete=models.PROTECT, related_name="entries")
    work_type = models.CharField(max_length=20, choices=WorkType.choices, default=WorkType.OTHER)

    class Meta:
        ordering = ["-expense__spent_on", "labourer__name", "id"]
        verbose_name_plural = "day labour entries"

    def __str__(self) -> str:
        return f"{self.labourer} · {self.expense}"


# ---- Cold-room cost per day (P5-T02, D-058) ----


class ColdRoomWeight(OrganizationScopedModel, TimeStampedModel):
    """How much of the electricity bill a cold room takes, relative to the others (D-041): equal by default
    (a room with no row weighs 1), more for a -20 degree room. Read when a bill is approved."""

    location = models.ForeignKey("inventory.StockLocation", on_delete=models.PROTECT, related_name="+")
    weight = models.DecimalField(max_digits=8, decimal_places=3, default=Decimal("1.000"))

    class Meta:
        ordering = ["location__name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "location"], name="cold_room_weight_one_per_room"),
            models.CheckConstraint(condition=models.Q(weight__gt=Decimal("0")), name="cold_room_weight_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.location} · {self.weight}"


class ElectricityBill(OrganizationScopedModel, TimeStampedModel):
    """The month's electricity bill, typed by the owner once the month is over.

    **One record with its expense** (category cold storage): the expense carries the amount, the date, the
    payment and the approval and feeds the books; this row says which month it is the bill of. Approving it
    freezes the rooms' weights and shares (`ColdRoomMonthRate`) and books the difference with the estimate
    on each lot (`LotCostAdjustment`).
    """

    # The first day of the month the bill is for.
    month = models.DateField()
    expense = models.OneToOneField(Expense, on_delete=models.CASCADE, related_name="electricity_bill")
    # Set when the bill is approved and the shares are frozen.
    finalized_at = models.DateTimeField(null=True, blank=True)
    # The earlier billed month whose daily rate served as the estimate (empty: there was none).
    estimate_source_month = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-month", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "month"], name="electricity_bill_one_per_month"),
        ]

    def __str__(self) -> str:
        return f"{self.month:%Y-%m} · {self.expense}"


class ColdRoomMonthRate(OrganizationScopedModel):
    """Frozen when a bill is approved: what a cold room's part of that month was, and the daily rate that
    had been used as its estimate. Never changes (later weight changes do not touch past bills)."""

    bill = models.ForeignKey(ElectricityBill, on_delete=models.CASCADE, related_name="rates")
    location = models.ForeignKey("inventory.StockLocation", on_delete=models.PROTECT, related_name="+")
    weight = models.DecimalField(max_digits=8, decimal_places=3)
    # The room's part of the bill: the rooms' parts add up to the bill exactly.
    month_amount = MoneyField()
    # The daily rate the estimate used for this room; empty when there was no earlier month to copy.
    estimate_day_amount = models.DecimalField[Decimal | None, Decimal | None](
        max_digits=14, decimal_places=3, null=True, blank=True
    )

    class Meta:
        ordering = ["location__name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["bill", "location"], name="cold_room_rate_one_per_room_and_bill"),
        ]


class LotCostAdjustmentKind(models.TextChoices):
    COLD_ROOM = "cold_room", _("Chambre froide")


class LotCostAdjustment(OrganizationScopedModel):
    """A correction line on a lot's costs: the real bill minus the estimate, dated when the bill was typed.

    A lot already closed is never reopened (D-041): the correction is a separate line that the next
    settlement picks up. Immutable, never edited or deleted; a mistake is another adjustment.
    """

    kind = models.CharField(max_length=30, choices=LotCostAdjustmentKind.choices)
    batch = models.ForeignKey("inventory.Batch", on_delete=models.PROTECT, related_name="+")
    location = models.ForeignKey(
        "inventory.StockLocation", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # The first day of the month corrected.
    month = models.DateField()
    # Signed: positive when the real bill is higher than the estimate.
    amount = MoneyField()
    # The day the real bill was typed: the line belongs to that day, not to the month corrected.
    dated_on = models.DateField()
    bill = models.ForeignKey(
        ElectricityBill, null=True, blank=True, on_delete=models.PROTECT, related_name="adjustments"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["dated_on", "id"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(amount=Decimal("0")), name="lot_cost_adjustment_not_zero"),
            models.UniqueConstraint(
                fields=["bill", "batch", "location"],
                condition=models.Q(bill__isnull=False),
                name="lot_cost_adjustment_one_per_bill_lot_room",
            ),
        ]
        indexes = [models.Index(fields=["organization", "batch"], name="lot_cost_adjustment_lot_idx")]


# ---- General costs on lots (P5-T05, D-059) ----


class RecurringCost(OrganizationScopedModel, TimeStampedModel):
    """A cost that comes every month (rent, accountant, insurance): a template that generates the
    month's expense (`services.generate_recurring_costs`)."""

    name = models.CharField(max_length=100)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="+")
    monthly_amount = MoneyField()
    payment_method = models.CharField(
        max_length=20, choices=ExpensePaymentMethod.choices, default=ExpensePaymentMethod.TRANSFER
    )
    payee = models.CharField(max_length=150, blank=True)
    # First day of the first and (optional) last month it applies to.
    start_month = models.DateField()
    end_month = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint("organization", Lower("name"), name="recurring_cost_name_unique_per_organization"),
            models.CheckConstraint(condition=models.Q(monthly_amount__gt=Decimal("0")), name="recurring_cost_positive"),
        ]

    def __str__(self) -> str:
        return self.name


class GeneralCostPeriod(OrganizationScopedModel):
    """Makes an expense a general cost spread over lots: it covers `months` months from `first_month`,
    each month carrying an equal part (D-059). One record with its expense; generated by a recurring
    template (one month) or typed for a bill covering several months (an insurance for a year)."""

    expense = models.OneToOneField(Expense, on_delete=models.CASCADE, related_name="general_period")
    first_month = models.DateField()
    months = models.PositiveSmallIntegerField(default=1)
    recurring = models.ForeignKey(
        RecurringCost, null=True, blank=True, on_delete=models.PROTECT, related_name="periods"
    )

    class Meta:
        ordering = ["-first_month", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(months__gte=1, months__lte=60), name="general_period_months"),
            models.UniqueConstraint(
                fields=["recurring", "first_month"],
                condition=models.Q(recurring__isnull=False),
                name="general_period_one_per_template_and_month",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.first_month:%Y-%m} x {self.months}"
