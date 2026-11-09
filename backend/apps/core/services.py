"""Every write on core models goes through these functions (ARCHITECTURE §3)."""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone
from django.utils.translation import gettext as _

from . import access, audit, numbering, selectors
from .images import reencoded_photo
from .models import CustomRole, Job, JobRun, Membership, NumberPrefix, Organization, Role, User

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile


@transaction.atomic
def create_organization(*, name: str) -> Organization:
    return Organization.objects.create(name=name)


@transaction.atomic
def create_user(
    *,
    username: str,
    password: str,
    first_name: str = "",
    last_name: str = "",
    language: str = "fr",
) -> User:
    return User.objects.create_user(
        username=username,
        password=password,
        first_name=first_name,
        last_name=last_name,
        language=language,
    )


@transaction.atomic
def set_language(*, user: User, language: str) -> User:
    """Save the language the user wants the apps in."""
    if language not in dict(settings.LANGUAGES):
        raise ValueError(f"Unsupported language: {language}")
    user.language = language
    user.save(update_fields=["language"])
    return user


@transaction.atomic
def add_member(
    *,
    organization: Organization,
    user: User,
    role: Role,
    actor: User | None = None,
    custom_role: CustomRole | None = None,
) -> Membership:
    """Give `user` a role in `organization`, or change the role they already have."""
    _check_custom_role(organization=organization, role=role, custom_role=custom_role)
    membership = Membership.objects.filter(organization=organization, user=user).first()
    before = {"role": membership.role, "is_active": membership.is_active} if membership else None
    if membership is None:
        membership = Membership(organization=organization, user=user)
    membership.role = role
    membership.custom_role = custom_role if role == Role.CUSTOM else None
    if role in (Role.OWNER, Role.DRIVER):
        membership.access_overrides = {}
    membership.is_active = True
    membership.save()
    audit.record(
        organization=organization,
        actor=actor,
        action="membership.set",
        target=membership,
        before=before,
        after={
            "role": membership.role,
            "is_active": True,
            **({"custom_role": membership.custom_role_id} if role == Role.CUSTOM else {}),
        },
    )
    return membership


# ---- Paramètres: company profile and user management (owner request, D-123) ----


def _delete_file_after_commit(field: Any, name: str) -> None:
    storage = field.storage
    transaction.on_commit(lambda: storage.delete(name))


@transaction.atomic
def set_organization_logo(
    *, organization: Organization, actor: User | None, upload: "UploadedFile[bytes]"
) -> Organization:
    """Replace the company logo shown on the company-profile page. Turned upright, shrunk, saved as WebP."""
    content = reencoded_photo(upload, field="logo")
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    old_name = organization.logo.name or ""
    organization.logo.save("logo.webp", content, save=False)
    try:
        organization.save(update_fields=["logo", "updated_at"])
        audit.record(organization=organization, actor=actor, action="organization.logo_set", target=organization)
    except BaseException:
        # The file is written before the row: never leave it behind when the change is rolled back.
        if organization.logo.name:
            organization.logo.storage.delete(organization.logo.name)
        raise
    if old_name:
        _delete_file_after_commit(organization.logo, old_name)
    return organization


@transaction.atomic
def remove_organization_logo(*, organization: Organization, actor: User | None) -> Organization:
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    old_name = organization.logo.name or ""
    if old_name:
        organization.logo.name = ""
        organization.save(update_fields=["logo", "updated_at"])
        audit.record(organization=organization, actor=actor, action="organization.logo_removed", target=organization)
        _delete_file_after_commit(organization.logo, old_name)
    return organization


@transaction.atomic
def set_user_avatar(*, user: User, upload: "UploadedFile[bytes]") -> User:
    """A user's own photo, set from their profile menu. Nobody else may change it (D-123)."""
    content = reencoded_photo(upload, field="avatar")
    user = User.objects.select_for_update().get(pk=user.pk)
    old_name = user.avatar.name or ""
    user.avatar.save("avatar.webp", content, save=False)
    try:
        user.save(update_fields=["avatar"])
        membership = selectors.active_membership(user)
        if membership is not None:
            audit.record(organization=membership.organization, actor=user, action="user.avatar_set", target=user)
    except BaseException:
        if user.avatar.name:
            user.avatar.storage.delete(user.avatar.name)
        raise
    if old_name:
        _delete_file_after_commit(user.avatar, old_name)
    return user


@transaction.atomic
def remove_user_avatar(*, user: User) -> User:
    user = User.objects.select_for_update().get(pk=user.pk)
    old_name = user.avatar.name or ""
    if old_name:
        user.avatar.name = ""
        user.save(update_fields=["avatar"])
        membership = selectors.active_membership(user)
        if membership is not None:
            audit.record(organization=membership.organization, actor=user, action="user.avatar_removed", target=user)
        _delete_file_after_commit(user.avatar, old_name)
    return user


@transaction.atomic
def update_own_profile(*, user: User, first_name: str, last_name: str) -> User:
    """A user changes their own display name from their profile menu."""
    user.first_name = first_name
    user.last_name = last_name
    user.save(update_fields=["first_name", "last_name"])
    return user


@transaction.atomic
def change_own_password(*, user: User, old_password: str, new_password: str) -> User:
    """A user changes their own password; the old one proves it is really them (no email reset exists, D-123)."""
    if not user.check_password(old_password):
        raise ValidationError({"old_password": _("Mot de passe actuel incorrect.")})
    validate_password(new_password, user=user)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    membership = selectors.active_membership(user)
    if membership is not None:
        audit.record(organization=membership.organization, actor=user, action="user.password_changed", target=user)
    return user


@transaction.atomic
def create_member(
    *,
    organization: Organization,
    actor: User | None,
    username: str,
    password: str,
    role: Role,
    first_name: str = "",
    last_name: str = "",
    email: str = "",
    custom_role: CustomRole | None = None,
) -> Membership:
    """The owner adds a new user with a role, and a password they will want to change (no email exists, D-123).
    A custom role (D-306) names the role the owner made."""
    _check_custom_role(organization=organization, role=role, custom_role=custom_role)
    validate_password(password)
    try:
        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
            email=email,
        )
    except IntegrityError:
        raise ValidationError({"username": _("Cet identifiant existe déjà.")}) from None
    return add_member(organization=organization, user=user, role=role, actor=actor, custom_role=custom_role)


def _lock_owners(organization: Organization) -> None:
    """Lock the organization's active owners, before the member changed: two owners removing each other at the
    same moment would otherwise both see the other one still there and both pass the guard below (D-141)."""
    list(
        Membership.objects.select_for_update()
        .filter(organization=organization, role=Role.OWNER, is_active=True)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def _guard_last_owner(*, organization: Organization, membership: Membership) -> None:
    if membership.role == Role.OWNER and selectors.active_owner_count(organization) <= 1:
        raise ValidationError({"detail": _("Impossible : ce serait le dernier propriétaire actif.")})


@transaction.atomic
def set_member_role(
    *,
    organization: Organization,
    membership: Membership,
    actor: User | None,
    role: Role,
    custom_role: CustomRole | None = None,
) -> Membership:
    """Change a member's role. Refused when it would leave the organization without an active owner. A custom role
    (D-306) names the role the owner made; becoming the owner or a driver drops the person's own levels."""
    _check_custom_role(organization=organization, role=role, custom_role=custom_role)
    _lock_owners(organization)
    membership = Membership.objects.select_for_update().get(pk=membership.pk, organization=organization)
    if role != Role.OWNER:
        _guard_last_owner(organization=organization, membership=membership)
    before = {"role": membership.role, "custom_role": membership.custom_role_id}
    membership.role = role
    membership.custom_role = custom_role if role == Role.CUSTOM else None
    if role in (Role.OWNER, Role.DRIVER):
        membership.access_overrides = {}
    else:
        # A level equal to the new role's is no longer the person's own.
        membership.access_overrides = _own_levels(membership, membership.access_overrides)
    membership.save(update_fields=["role", "custom_role", "access_overrides", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="membership.role_set",
        target=membership,
        before=before,
        after={"role": membership.role, "custom_role": membership.custom_role_id},
    )
    return membership


# ---- Custom roles and each person's own levels (D-306) ----


def _check_custom_role(*, organization: Organization, role: Role, custom_role: CustomRole | None) -> None:
    if role == Role.CUSTOM and custom_role is None:
        raise ValidationError({"custom_role": _("Choisissez le rôle personnalisé.")})
    if custom_role is not None and custom_role.organization_id != organization.pk:
        raise ValidationError({"custom_role": _("Rôle inconnu.")})


def _matrix_errors(error: ValidationError) -> list[str]:
    """The errors of a typed matrix, one line per section ("payroll : …")."""
    return [f"{key} : {text}" for key, texts in error.message_dict.items() for text in texts]


def _own_levels(membership: Membership, overrides: Mapping[str, Any]) -> dict[str, str]:
    """The levels that differ from the person's role: the same level as the role is not their own."""
    of_role = access.role_matrix(membership)
    return {key: str(value) for key, value in overrides.items() if of_role.get(key) != value}


def _role_name_taken(organization: Organization, name: str, *, exclude: int | None = None) -> bool:
    rows = CustomRole.objects.filter(organization=organization, name__iexact=name)
    if exclude is not None:
        rows = rows.exclude(pk=exclude)
    return rows.exists() or name.casefold() in {str(label).casefold() for label in Role.labels}


def _checked_role_fields(
    organization: Organization, name: str, levels: Mapping[str, Any], *, exclude: int | None = None
) -> tuple[str, dict[str, str]]:
    name = name.strip()
    if not name:
        raise ValidationError({"name": _("Donnez un nom au rôle.")})
    if _role_name_taken(organization, name, exclude=exclude):
        raise ValidationError({"name": _("Un rôle porte déjà ce nom.")})
    try:
        cleaned = access.clean_matrix(levels, partial=False)
    except ValidationError as error:
        raise ValidationError({"access": _matrix_errors(error)}) from None
    return name, cleaned


@transaction.atomic
def create_custom_role(
    *, organization: Organization, actor: User | None, name: str, access_levels: Mapping[str, Any]
) -> CustomRole:
    """The owner makes a role and chooses its level in each section (Paramètres › Rôles, D-306)."""
    name, levels = _checked_role_fields(organization, name, access_levels)
    role = CustomRole.objects.create(organization=organization, name=name, access=levels)
    audit.record(
        organization=organization,
        actor=actor,
        action="custom_role.created",
        target=role,
        after={"name": name, "access": levels},
    )
    return role


@transaction.atomic
def update_custom_role(
    *, organization: Organization, role: CustomRole, actor: User | None, name: str, access_levels: Mapping[str, Any]
) -> CustomRole:
    """Rename a role or change its levels. The people who have it get the new levels at their next call."""
    role = CustomRole.objects.select_for_update().get(pk=role.pk, organization=organization)
    name, levels = _checked_role_fields(organization, name, access_levels, exclude=role.pk)
    before = {"name": role.name, "access": role.access}
    role.name = name
    role.access = levels
    role.save(update_fields=["name", "access", "updated_at"])
    # A person's own level that the role now gives is no longer their own.
    for membership in role.memberships.select_for_update():
        own = _own_levels(membership, membership.access_overrides or {})
        if own != membership.access_overrides:
            membership.access_overrides = own
            membership.save(update_fields=["access_overrides", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="custom_role.updated",
        target=role,
        before=before,
        after={"name": name, "access": levels},
    )
    return role


@transaction.atomic
def delete_custom_role(*, organization: Organization, role: CustomRole, actor: User | None) -> None:
    """Delete a role nobody has (deactivated people included: give them another role first)."""
    role = CustomRole.objects.select_for_update().get(pk=role.pk, organization=organization)
    if role.memberships.exists():
        raise ValidationError({"detail": _("Des utilisateurs ont ce rôle : donnez-leur un autre rôle d'abord.")})
    audit.record(
        organization=organization,
        actor=actor,
        action="custom_role.deleted",
        target=role,
        before={"name": role.name, "access": role.access},
    )
    role.delete()


@transaction.atomic
def set_member_access(
    *, organization: Organization, membership: Membership, actor: User | None, overrides: Mapping[str, Any]
) -> Membership:
    """The owner gives one person their own level in some sections, over their role's (D-306). The whole set is
    replaced; a section left out follows the role again. The owner has everything and a driver works only on the
    phone: neither takes levels of their own."""
    membership = Membership.objects.select_for_update().get(pk=membership.pk, organization=organization)
    if membership.role in (Role.OWNER, Role.DRIVER):
        raise ValidationError(
            {"detail": _("Le propriétaire a tous les accès et un chauffeur travaille sur le téléphone.")}
        )
    try:
        cleaned = access.clean_matrix(overrides, partial=True)
    except ValidationError as error:
        raise ValidationError({"overrides": _matrix_errors(error)}) from None
    before = dict(membership.access_overrides or {})
    membership.access_overrides = _own_levels(membership, cleaned)
    membership.save(update_fields=["access_overrides", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="membership.access_set",
        target=membership,
        before=before,
        after=dict(membership.access_overrides),
    )
    return membership


@transaction.atomic
def set_member_active(
    *, organization: Organization, membership: Membership, actor: User | None, is_active: bool
) -> Membership:
    """Deactivate (or reactivate) a member. Never a hard delete: other tables point to the user (D-123)."""
    _lock_owners(organization)
    membership = Membership.objects.select_for_update().get(pk=membership.pk, organization=organization)
    if not is_active:
        _guard_last_owner(organization=organization, membership=membership)
    before = {"is_active": membership.is_active}
    membership.is_active = is_active
    membership.save(update_fields=["is_active", "updated_at"])
    user = membership.user
    user.is_active = is_active
    user.save(update_fields=["is_active"])
    audit.record(
        organization=organization,
        actor=actor,
        action="membership.activated" if is_active else "membership.deactivated",
        target=membership,
        before=before,
        after={"is_active": is_active},
    )
    return membership


@transaction.atomic
def set_member_can_buy(
    *, organization: Organization, membership: Membership, actor: User | None, can_buy: bool
) -> Membership:
    """Let a member buy at the port from the phone, or stop it (D-158). What they already sent stays."""
    membership = Membership.objects.select_for_update().get(pk=membership.pk, organization=organization)
    before = {"can_buy": membership.can_buy}
    membership.can_buy = can_buy
    membership.save(update_fields=["can_buy", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="membership.can_buy_set",
        target=membership,
        before=before,
        after={"can_buy": can_buy},
    )
    return membership


@transaction.atomic
def update_member_profile(
    *,
    organization: Organization,
    membership: Membership,
    actor: User | None,
    username: str,
    first_name: str,
    last_name: str,
) -> Membership:
    """The owner corrects a member's login identifier and name (D-143); the identifier stays unique."""
    membership = Membership.objects.select_for_update().get(pk=membership.pk, organization=organization)
    user = User.objects.select_for_update().get(pk=membership.user_id)
    before = {"username": user.username, "first_name": user.first_name, "last_name": user.last_name}
    user.username = username
    user.first_name = first_name
    user.last_name = last_name
    try:
        with transaction.atomic():
            user.save(update_fields=["username", "first_name", "last_name"])
    except IntegrityError:
        raise ValidationError({"username": _("Cet identifiant existe déjà.")}) from None
    membership.user = user
    audit.record(
        organization=organization,
        actor=actor,
        action="membership.profile_changed",
        target=membership,
        before=before,
        after={"username": username, "first_name": first_name, "last_name": last_name},
    )
    return membership


@transaction.atomic
def delete_member(*, organization: Organization, membership: Membership, actor: User | None) -> None:
    """The owner deletes a user. Only possible while the account has no history: its invoices, closings, days
    and audit entries point to the user and must keep working, so those accounts are deactivated instead (D-143)."""
    _lock_owners(organization)
    membership = Membership.objects.select_for_update().get(pk=membership.pk, organization=organization)
    user = membership.user
    if actor is not None and user.pk == actor.pk:
        raise ValidationError({"detail": _("Vous ne pouvez pas supprimer votre propre compte.")})
    _guard_last_owner(organization=organization, membership=membership)
    if user.memberships.exclude(organization=organization).exists():
        raise ValidationError({"detail": _("Ce compte a aussi accès à une autre société : désactivez-le à la place.")})
    avatar_name = user.avatar.name if user.avatar else None
    audit.record(
        organization=organization,
        actor=actor,
        action="membership.deleted",
        target=membership,
        before={"username": user.username, "role": membership.role},
    )
    try:
        with transaction.atomic():
            user.delete()
    except ProtectedError:
        raise ValidationError(
            {"detail": _("Ce compte a déjà des opérations à son nom : il ne peut pas être supprimé. Désactivez-le.")}
        ) from None
    if avatar_name:
        _delete_file_after_commit(User._meta.get_field("avatar"), avatar_name)


@transaction.atomic
def reset_member_password(
    *, organization: Organization, membership: Membership, actor: User | None, new_password: str
) -> Membership:
    """The owner types a new password for someone else (shown once); no email or SMS reset exists (D-123)."""
    membership = Membership.objects.select_for_update().get(pk=membership.pk, organization=organization)
    validate_password(new_password, user=membership.user)
    membership.user.set_password(new_password)
    membership.user.save(update_fields=["password"])
    audit.record(organization=organization, actor=actor, action="membership.password_reset", target=membership)
    return membership


@transaction.atomic
def record_job_run(*, job: Job, ok: bool, problems: int = 0) -> JobRun:
    """Keeps the last run of a scheduled job (P4-T04, D-140): the monitoring reads it, the next run replaces it."""
    run, _ = JobRun.objects.update_or_create(
        job=job, defaults={"ran_at": timezone.now(), "ok": ok, "problems": problems}
    )
    return run


@transaction.atomic
def set_number_prefixes(
    *,
    organization: Organization,
    actor: User | None,
    prefixes: Sequence[tuple[str, str]],
    draft_prefixes: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Change the prefixes printed before the numbers (Paramètres, D-223). Every kind is sent, in the order of
    `numbering.NUMBER_KINDS`. A prefix is 1 to 6 capitals or digits, and no two kinds share one in the organization.
    Numbers already given keep their prefix; the counters go on.

    `draft_prefixes` (D-283): the prefix of the provisional reference of the drafts, for the kinds with a draft
    step only; empty means none. A draft prefix shares no value with any other prefix, definitive or draft."""
    # One change at a time in an organization, so two owners cannot both take the same prefix.
    Organization.objects.select_for_update().filter(pk=organization.pk).first()
    before = numbering.prefixes_of(organization)
    before_drafts = numbering.draft_prefixes_of(organization)
    draft_prefixes = draft_prefixes or {}
    errors: dict[str, str] = {}
    chosen: dict[str, str] = {}
    chosen_drafts: dict[str, str] = {}
    for index, (key, prefix) in enumerate(prefixes):
        value = prefix.strip().upper()
        if key not in numbering.KIND_BY_KEY:
            errors[f"prefixes.{index}.kind"] = _("Type de numéro inconnu.")
            continue
        if not numbering.PREFIX_PATTERN.match(value):
            errors[f"prefixes.{index}.prefix"] = _("1 à 6 lettres majuscules ou chiffres, sans espace.")
        else:
            chosen[key] = value
        if key in draft_prefixes:
            draft = draft_prefixes[key].strip().upper()
            if key not in before_drafts:
                errors[f"prefixes.{index}.draft_prefix"] = _("Ce type de numéro n'a pas de brouillon.")
            elif draft and not numbering.PREFIX_PATTERN.match(draft):
                errors[f"prefixes.{index}.draft_prefix"] = _("1 à 6 lettres majuscules ou chiffres, sans espace.")
            else:
                chosen_drafts[key] = draft
    if not errors:
        effective = {**before, **chosen}
        effective_drafts = {key: value for key, value in {**before_drafts, **chosen_drafts}.items() if value}
        everything = [*effective.values(), *effective_drafts.values()]
        for index, (key, _prefix) in enumerate(prefixes):
            if everything.count(effective[key]) > 1:
                errors[f"prefixes.{index}.prefix"] = _("Ce préfixe sert déjà à un autre type de numéro.")
            if key in effective_drafts and everything.count(effective_drafts[key]) > 1:
                errors[f"prefixes.{index}.draft_prefix"] = _("Ce préfixe sert déjà à un autre type de numéro.")
    if errors:
        raise ValidationError(errors)
    changed = {key: value for key, value in chosen.items() if value != before[key]}
    changed_drafts = {key: value for key, value in chosen_drafts.items() if value != before_drafts[key]}
    for key, value in changed.items():
        NumberPrefix.objects.update_or_create(organization=organization, kind=key, defaults={"prefix": value})
    for key, value in changed_drafts.items():
        NumberPrefix.objects.update_or_create(
            organization=organization,
            kind=key,
            defaults={"draft_prefix": value, "draft_prefix_set": True},
            create_defaults={"prefix": chosen.get(key, before[key]), "draft_prefix": value, "draft_prefix_set": True},
        )
    if changed or changed_drafts:
        audit.record(
            organization=organization,
            actor=actor,
            action="numbering.prefixes_changed",
            before={
                **{key: before[key] for key in changed},
                **{f"{key}.draft": before_drafts[key] for key in changed_drafts},
            },
            after={**changed, **{f"{key}.draft": value for key, value in changed_drafts.items()}},
        )
    return numbering.prefixes_of(organization)
