import uuid
from typing import Any, Self

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def organization_logo_path(organization: "Organization", filename: str) -> str:
    # A new random name on every upload: the old URL never shows the new logo from a cache.
    return f"organizations/{organization.pk}/{uuid.uuid4().hex}.webp"


class Organization(TimeStampedModel):
    """A company using the software. One exists today; every business table points to it (D-004)."""

    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    # Shown in the app header, as the browser-tab icon and on every PDF (D-123, D-125).
    logo = models.ImageField(upload_to=organization_logo_path, blank=True)
    # Set when the client's real data is entered (prepare_client_start, D-146). The demo seed then adds nothing.
    real_data_since = models.DateTimeField(null=True, blank=True)
    # The books are locked up to this day, included (D-315): a month declared to the tax office takes no new dated
    # entry; a correction is dated in the open month. Empty: nothing is locked.
    books_locked_until = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


def user_avatar_path(user: "User", filename: str) -> str:
    # A new random name on every upload: the old URL never shows the new photo from a cache.
    return f"users/{user.pk}/{uuid.uuid4().hex}.webp"


class User(AbstractUser):
    """Custom from the first migration, because swapping the user model later is costly."""

    language = models.CharField(max_length=5, choices=settings.LANGUAGES, default=settings.LANGUAGE_CODE)
    # Set by the user themselves from their own profile menu (D-123); nobody else may change it.
    avatar = models.ImageField(upload_to=user_avatar_path, blank=True)

    def __str__(self) -> str:
        return self.get_full_name() or self.username


class Role(models.TextChoices):
    OWNER = "owner", _("Propriétaire")
    MANAGER = "manager", _("Gestionnaire")
    DRIVER = "driver", _("Chauffeur")
    ACCOUNTANT = "accountant", _("Comptable")
    # A role the owner made in Paramètres › Rôles: what it may do is its own access matrix (D-306).
    CUSTOM = "custom", _("Rôle personnalisé")


class CustomRole(TimeStampedModel):
    """A role the owner names and gives an access level per section of the application (D-306).

    `access` maps a section key of `apps.core.access.SECTIONS` to a level ("none", "read", "write", "full");
    a section left out is "none".
    """

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="custom_roles")
    name = models.CharField(max_length=60)
    access = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="one_custom_role_name_per_organization"),
        ]

    def __str__(self) -> str:
        return self.name


class Membership(TimeStampedModel):
    """What a user may do in one organization."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    # A driver the owner lets buy at the port and send the purchase from the phone (D-158). Not every driver may.
    can_buy = models.BooleanField(default=False)
    # Set when `role` is "custom": the role the owner made (D-306). A role still in use cannot be deleted.
    custom_role = models.ForeignKey(
        CustomRole, null=True, blank=True, on_delete=models.PROTECT, related_name="memberships"
    )
    # This person's own levels, section by section, over those of their role (D-306): {"sales": "read", ...}.
    access_overrides = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "organization"], name="one_membership_per_user_and_organization"),
            models.CheckConstraint(
                condition=(models.Q(role="custom") & models.Q(custom_role__isnull=False))
                | (~models.Q(role="custom") & models.Q(custom_role__isnull=True)),
                name="custom_role_set_only_for_the_custom_role",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.organization} · {self.get_role_display()}"


class OrganizationScopedQuerySet[M: models.Model](models.QuerySet[M]):
    def for_organization(self, organization: Organization) -> Self:
        """The only way business code should read rows: always inside one organization."""
        return self.filter(organization=organization)


class OrganizationScopedModel(models.Model):
    """Base of every business table (ARCHITECTURE §4.6)."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="+")

    objects = OrganizationScopedQuerySet.as_manager()

    class Meta:
        abstract = True


class AuditLogQuerySet(OrganizationScopedQuerySet["AuditLog"]):
    def update(self, **kwargs: Any) -> int:
        raise TypeError("Audit entries are append-only: write a new entry instead of changing one")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise TypeError("Audit entries are append-only: they are never deleted")


class AuditLog(OrganizationScopedModel):
    """Who did what, when, with the values before and after. Append-only (ARCHITECTURE §4.9)."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # Null when the system acts on its own (a scheduled job).
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    action = models.CharField(max_length=100, db_index=True)
    target_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    target_id = models.CharField(max_length=64, blank=True)
    target = GenericForeignKey("target_type", "target_id")
    target_repr = models.CharField(max_length=200, blank=True)
    before = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    after = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)

    # mypy sees the base manager as a class variable; replacing it per model is the Django way.
    objects = AuditLogQuerySet.as_manager()  # type: ignore[misc]

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self) -> str:
        return f"{self.action} · {self.target_repr}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise TypeError("Audit entries are append-only: write a new entry instead of changing one")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise TypeError("Audit entries are append-only: they are never deleted")


class Job(models.TextChoices):
    """Scheduled jobs whose last run is watched (P4-T04, D-140)."""

    STOCK_CHECK = "stock_check", "Nightly stock check"


class JobRun(models.Model):
    """The last run of a scheduled job, one row per job, for monitoring (P4-T04, D-140).

    Not a business table: a job such as the nightly stock check runs once for the whole installation, over every
    organization, so the row has no `organization`. It keeps only when the job ran, whether it passed and how many
    problems it found; the public status endpoint shows the time and ok/failed only.
    """

    job = models.CharField(max_length=50, choices=Job.choices, unique=True)
    ran_at = models.DateTimeField()
    ok = models.BooleanField()
    problems = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["job"]

    def __str__(self) -> str:
        return f"{self.job} · {'ok' if self.ok else 'failed'} · {self.ran_at:%Y-%m-%d %H:%M}"


class NumberSeries(OrganizationScopedModel):
    """The last number given to one kind of number in an organization (D-223): customers, suppliers, products and
    every document kind. A yearly kind has one row per year; the others use year 0. Its row is locked while a number
    is taken (`numbering.next_number`), so two records saved at the same moment never share one."""

    kind = models.CharField(max_length=30)
    year = models.PositiveIntegerField(default=0)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "kind", "year"], name="one_number_series_per_kind_year"),
        ]

    def __str__(self) -> str:
        return f"{self.organization} · {self.kind} · {self.year} · {self.last_number}"


class NumberPrefix(OrganizationScopedModel):
    """The prefix printed before the numbers of one kind, set on the Paramètres page (D-223). A kind without a row
    uses its default prefix (`numbering.NUMBER_KINDS`)."""

    kind = models.CharField(max_length=30)
    prefix = models.CharField(max_length=6)
    # The prefix of the provisional reference of a draft (D-283), for the kinds with a draft step. Empty: no
    # provisional reference. `draft_prefix_set` tells an empty choice from "never chosen" (the default applies).
    draft_prefix = models.CharField(max_length=6, blank=True)
    draft_prefix_set = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "kind"], name="one_number_prefix_per_kind"),
        ]

    def __str__(self) -> str:
        return f"{self.organization} · {self.kind} · {self.prefix}"
