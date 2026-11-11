"""Every write on suppliers goes through these functions (ARCHITECTURE §3)."""

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, TypedDict, Unpack

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit, numbering
from apps.core.models import Organization, User

from .models import (
    Customer,
    CustomerContact,
    CustomerKind,
    CustomerType,
    IdentificationType,
    Supplier,
    SupplierContact,
    SupplierTaxRegime,
)

# 7 digits and a key letter, then the VAT code, the category and the establishment number (000 = head office).
_TAX_ID = re.compile(r"^(\d{6,7})([A-Z])(?:([A-Z])([A-Z])(\d{3}))?$")


class SupplierFields(TypedDict, total=False):
    reference: str
    name: str
    tax_id: str
    phone: str
    email: str
    address: str
    city: str
    notes: str
    payment_terms_days: int | None
    buys_with_vat: bool
    health_approval: str
    # "real", "flat", "none"; empty: "real" with a tax ID, "none" without (D-319).
    tax_regime: str
    subject_to_withholding: bool


class ContactFields(TypedDict, total=False):
    name: str
    role: str
    phone: str
    email: str


def normalized_tax_id(value: str) -> str:
    """A Tunisian tax ID ("matricule fiscal") written the usual way: `1234567A/A/M/000`, or `1234567A` alone.

    Spaces, dots, dashes and slashes are ignored when reading it, and an old 6-digit number gets its
    leading zero back. Raises ValueError when it does not have that shape. Empty stays empty.
    """
    compact = re.sub(r"[\s./-]", "", value.upper())
    if not compact:
        return ""
    match = _TAX_ID.match(compact)
    if match is None:
        raise ValueError(_("Matricule fiscal invalide : attendu 1234567A/A/M/000 ou 1234567A."))
    number, key, vat_code, category, establishment = match.groups()
    identifier = f"{number.zfill(7)}{key}"
    return f"{identifier}/{vat_code}/{category}/{establishment}" if vat_code else identifier


def _snapshot(supplier: Supplier, contacts: Sequence[SupplierContact]) -> dict[str, Any]:
    return {
        "reference": supplier.reference,
        "name": supplier.name,
        "tax_id": supplier.tax_id,
        "phone": supplier.phone,
        "email": supplier.email,
        "address": supplier.address,
        "city": supplier.city,
        "notes": supplier.notes,
        "payment_terms_days": supplier.payment_terms_days,
        "buys_with_vat": supplier.buys_with_vat,
        "health_approval": supplier.health_approval,
        "tax_regime": supplier.tax_regime,
        "subject_to_withholding": supplier.subject_to_withholding,
        "contacts": [
            {"name": contact.name, "role": contact.role, "phone": contact.phone, "email": contact.email}
            for contact in contacts
        ],
    }


def _email_error(value: str) -> bool:
    try:
        validate_email(value)
    except ValidationError:
        return True
    return False


def _clean_supplier(supplier: Supplier) -> None:
    """Business rules shared by creation and update. Raises ValidationError with one message per field."""
    errors: dict[str, str] = {}
    for field in ("reference", "name", "phone", "email", "address", "city", "notes"):
        setattr(supplier, field, getattr(supplier, field).strip())
    others = Supplier.objects.for_organization(supplier.organization).exclude(pk=supplier.pk)
    if not supplier.reference:
        errors["reference"] = _("La référence est obligatoire.")
    elif others.filter(reference__iexact=supplier.reference).exists():
        errors["reference"] = _("Un autre fournisseur porte déjà cette référence.")
    if not supplier.name:
        errors["name"] = _("Le nom est obligatoire.")
    try:
        supplier.tax_id = normalized_tax_id(supplier.tax_id)
    except ValueError as error:
        errors["tax_id"] = str(error)
    else:
        if supplier.tax_id and others.filter(tax_id=supplier.tax_id).exists():
            errors["tax_id"] = _("Un autre fournisseur a déjà ce matricule fiscal.")
    if supplier.email and _email_error(supplier.email):
        errors["email"] = _("Adresse e-mail invalide.")
    # Without a tax ID there is no regime to declare (D-319); with one, empty means the régime réel.
    if not supplier.tax_id:
        supplier.tax_regime = SupplierTaxRegime.NONE
    elif not supplier.tax_regime or supplier.tax_regime == SupplierTaxRegime.NONE:
        supplier.tax_regime = SupplierTaxRegime.REAL
    elif supplier.tax_regime not in SupplierTaxRegime.values:
        errors["tax_regime"] = _("Régime fiscal inconnu.")
    if errors:
        raise ValidationError(errors)


def _cleaned_contacts(supplier: Supplier, contacts: Sequence[ContactFields]) -> list[SupplierContact]:
    cleaned = []
    for number, fields in enumerate(contacts, start=1):
        contact = SupplierContact(
            organization=supplier.organization,
            supplier=supplier,
            name=fields.get("name", "").strip(),
            role=fields.get("role", "").strip(),
            phone=fields.get("phone", "").strip(),
            email=fields.get("email", "").strip(),
        )
        if not contact.name:
            raise ValidationError({"contacts": _("Contact %(number)s : le nom est obligatoire.") % {"number": number}})
        if contact.email and _email_error(contact.email):
            raise ValidationError({"contacts": _("Contact %(number)s : adresse e-mail invalide.") % {"number": number}})
        cleaned.append(contact)
    return cleaned


@transaction.atomic
def create_supplier(
    *,
    organization: Organization,
    actor: User | None,
    contacts: Sequence[ContactFields] = (),
    **fields: Unpack[SupplierFields],
) -> Supplier:
    """A new supplier. Without a reference it gets the next supplier number (F-001 by default, D-223)."""
    # Serializes creations in one organization, so two of them cannot take the same generated reference.
    Organization.objects.select_for_update().filter(pk=organization.pk).first()
    supplier = Supplier(organization=organization, **fields)
    if not supplier.reference.strip():
        supplier.reference = numbering.next_free_reference(
            organization, "supplier", Supplier.objects.for_organization(organization)
        )
    _clean_supplier(supplier)
    new_contacts = _cleaned_contacts(supplier, contacts)
    supplier.save()
    SupplierContact.objects.bulk_create(new_contacts)
    audit.record(
        organization=organization,
        actor=actor,
        action="supplier.created",
        target=supplier,
        after=_snapshot(supplier, new_contacts),
    )
    return supplier


@transaction.atomic
def update_supplier(
    *,
    supplier: Supplier,
    actor: User | None,
    contacts: Sequence[ContactFields] | None = None,
    **fields: Unpack[SupplierFields],
) -> Supplier:
    """Change a supplier. `contacts`, when given, replaces the whole list; absent, the list is kept."""
    supplier = Supplier.objects.select_for_update().get(pk=supplier.pk)
    old_contacts = list(supplier.contacts.order_by("id"))
    before = _snapshot(supplier, old_contacts)
    for field, value in fields.items():
        setattr(supplier, field, value)
    _clean_supplier(supplier)
    new_contacts = old_contacts if contacts is None else _cleaned_contacts(supplier, contacts)
    supplier.save()
    if contacts is not None:
        supplier.contacts.all().delete()
        SupplierContact.objects.bulk_create(new_contacts)
    after = _snapshot(supplier, new_contacts)
    changed = [field for field in after if after[field] != before[field]]
    if changed:
        audit.record(
            organization=supplier.organization,
            actor=actor,
            action="supplier.updated",
            target=supplier,
            before={field: before[field] for field in changed},
            after={field: after[field] for field in changed},
        )
    return supplier


@transaction.atomic
def set_supplier_active(*, supplier: Supplier, actor: User | None, is_active: bool) -> Supplier:
    """Archive a supplier (it keeps its history but is no longer bought from), or bring it back."""
    supplier = Supplier.objects.select_for_update().get(pk=supplier.pk)
    if supplier.is_active != is_active:
        supplier.is_active = is_active
        supplier.save(update_fields=["is_active", "updated_at"])
        action = "supplier.restored" if is_active else "supplier.archived"
        audit.record(organization=supplier.organization, actor=actor, action=action, target=supplier)
    return supplier


# ---- customers (P2-T01, D-047) ----

WALK_IN_NAME = "Client de passage"
_MILLIME = Decimal("0.001")


class CustomerFields(TypedDict, total=False):
    reference: str
    name: str
    kind: str
    id_type: str
    tax_id: str
    phone: str
    email: str
    address: str
    city: str
    notes: str
    credit_limit: Decimal
    payment_terms_days: int
    withholding_subject: bool


def _customer_snapshot(customer: Customer, contacts: Sequence[CustomerContact]) -> dict[str, Any]:
    return {
        "reference": customer.reference,
        "name": customer.name,
        "kind": customer.kind,
        "id_type": customer.id_type,
        "tax_id": customer.tax_id,
        "phone": customer.phone,
        "email": customer.email,
        "address": customer.address,
        "city": customer.city,
        "notes": customer.notes,
        "credit_limit": str(Decimal(customer.credit_limit).quantize(_MILLIME)),
        "payment_terms_days": customer.payment_terms_days,
        "withholding_subject": customer.withholding_subject,
        "contacts": [
            {"name": contact.name, "role": contact.role, "phone": contact.phone, "email": contact.email}
            for contact in contacts
        ],
    }


# A CIN is 8 digits; a passport or a residence card, letters and digits (D-283).
_CIN = re.compile(r"^\d{8}$")
_DOCUMENT_NUMBER = re.compile(r"^[A-Z0-9]{5,20}$")


def normalized_identification(id_type: str, value: str) -> str:
    """The identification number of a customer written the usual way for its type (D-283). Kept as text, so the
    leading zeros of a CIN stay. Raises ValueError when it does not have that shape. Empty stays empty."""
    if id_type == IdentificationType.TAX_ID:
        return normalized_tax_id(value)
    compact = re.sub(r"[\s.-]", "", value.upper())
    if not compact:
        return ""
    if id_type == IdentificationType.CIN:
        if not _CIN.match(compact):
            raise ValueError(_("Numéro de CIN invalide : 8 chiffres attendus, par exemple 01234567."))
        return compact
    if not _DOCUMENT_NUMBER.match(compact):
        if id_type == IdentificationType.PASSPORT:
            raise ValueError(_("Numéro de passeport invalide : 5 à 20 lettres ou chiffres."))
        raise ValueError(_("Numéro de carte de séjour invalide : 5 à 20 lettres ou chiffres."))
    return compact


def _clean_customer(customer: Customer, *, previous_kind: str | None = None) -> None:
    """Business rules shared by creation and update. Raises ValidationError with one message per field.
    `previous_kind`: the type the customer had, still accepted even when deactivated since (D-283)."""
    errors: dict[str, str] = {}
    for field in ("reference", "name", "phone", "email", "address", "city", "notes"):
        setattr(customer, field, getattr(customer, field).strip())
    others = Customer.objects.for_organization(customer.organization).exclude(pk=customer.pk)
    if not customer.reference:
        errors["reference"] = _("La référence est obligatoire.")
    elif others.filter(reference__iexact=customer.reference).exists():
        errors["reference"] = _("Un autre client porte déjà cette référence.")
    if not customer.name:
        errors["name"] = _("Le nom est obligatoire.")
    types = {row.code: row for row in customer_types_of(customer.organization)}
    chosen_type = types.get(customer.kind)
    if chosen_type is None:
        errors["kind"] = _("Type de client inconnu.")
    elif not chosen_type.is_active and customer.kind != previous_kind:
        errors["kind"] = _("Ce type de client est désactivé : choisissez-en un autre.")
    if customer.id_type not in IdentificationType.values:
        errors["id_type"] = _("Type d'identification inconnu.")
    else:
        try:
            customer.tax_id = normalized_identification(customer.id_type, customer.tax_id)
        except ValueError as error:
            errors["tax_id"] = str(error)
        else:
            if customer.tax_id and others.filter(id_type=customer.id_type, tax_id=customer.tax_id).exists():
                errors["tax_id"] = _("Un autre client a déjà ce numéro d'identification.")
    if customer.email and _email_error(customer.email):
        errors["email"] = _("Adresse e-mail invalide.")
    limit = Decimal(customer.credit_limit)
    if limit < 0:
        errors["credit_limit"] = _("La limite de crédit ne peut pas être négative.")
    elif limit != limit.quantize(_MILLIME):
        errors["credit_limit"] = _("La limite de crédit s'exprime avec 3 décimales au plus.")
    elif customer.is_walk_in and limit != 0:
        errors["credit_limit"] = _("Le client de passage paie comptant : pas de crédit.")
    if not 0 <= customer.payment_terms_days <= 365:
        errors["payment_terms_days"] = _("Le délai de paiement va de 0 à 365 jours.")
    if errors:
        raise ValidationError(errors)


def _cleaned_customer_contacts(customer: Customer, contacts: Sequence[ContactFields]) -> list[CustomerContact]:
    cleaned = []
    for number, fields in enumerate(contacts, start=1):
        contact = CustomerContact(
            organization=customer.organization,
            customer=customer,
            name=fields.get("name", "").strip(),
            role=fields.get("role", "").strip(),
            phone=fields.get("phone", "").strip(),
            email=fields.get("email", "").strip(),
        )
        if not contact.name:
            raise ValidationError({"contacts": _("Contact %(number)s : le nom est obligatoire.") % {"number": number}})
        if contact.email and _email_error(contact.email):
            raise ValidationError({"contacts": _("Contact %(number)s : adresse e-mail invalide.") % {"number": number}})
        cleaned.append(contact)
    return cleaned


@transaction.atomic
def create_customer(
    *,
    organization: Organization,
    actor: User | None,
    contacts: Sequence[ContactFields] = (),
    is_walk_in: bool = False,
    **fields: Unpack[CustomerFields],
) -> Customer:
    """A new customer. Without a reference it gets the next customer number (C-001 by default, D-223)."""
    # Serializes creations in one organization, so two of them cannot take the same generated reference.
    Organization.objects.select_for_update().filter(pk=organization.pk).first()
    customer = Customer(organization=organization, is_walk_in=is_walk_in, **fields)
    if not customer.reference.strip():
        customer.reference = numbering.next_free_reference(
            organization, "customer", Customer.objects.for_organization(organization)
        )
    _clean_customer(customer)
    new_contacts = _cleaned_customer_contacts(customer, contacts)
    customer.save()
    CustomerContact.objects.bulk_create(new_contacts)
    audit.record(
        organization=organization,
        actor=actor,
        action="customer.created",
        target=customer,
        after=_customer_snapshot(customer, new_contacts),
    )
    return customer


@transaction.atomic
def update_customer(
    *,
    customer: Customer,
    actor: User | None,
    contacts: Sequence[ContactFields] | None = None,
    **fields: Unpack[CustomerFields],
) -> Customer:
    """Change a customer. `contacts`, when given, replaces the whole list; absent, the list is kept."""
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    old_contacts = list(customer.contacts.order_by("id"))
    before = _customer_snapshot(customer, old_contacts)
    previous_kind = customer.kind
    for field, value in fields.items():
        setattr(customer, field, value)
    _clean_customer(customer, previous_kind=previous_kind)
    new_contacts = old_contacts if contacts is None else _cleaned_customer_contacts(customer, contacts)
    customer.save()
    if contacts is not None:
        customer.contacts.all().delete()
        CustomerContact.objects.bulk_create(new_contacts)
    after = _customer_snapshot(customer, new_contacts)
    changed = [field for field in after if after[field] != before[field]]
    if changed:
        audit.record(
            organization=customer.organization,
            actor=actor,
            action="customer.updated",
            target=customer,
            before={field: before[field] for field in changed},
            after={field: after[field] for field in changed},
        )
    return customer


@transaction.atomic
def set_customer_active(*, customer: Customer, actor: User | None, is_active: bool) -> Customer:
    """Archive a customer (it keeps its history but is no longer sold to), or bring it back."""
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    if customer.is_walk_in and not is_active:
        raise ValidationError({"detail": _("Le client de passage ne peut pas être archivé.")})
    if customer.is_active != is_active:
        customer.is_active = is_active
        customer.save(update_fields=["is_active", "updated_at"])
        action = "customer.restored" if is_active else "customer.archived"
        audit.record(organization=customer.organization, actor=actor, action=action, target=customer)
    return customer


@transaction.atomic
@transaction.atomic
def set_customer_location(
    *, customer: Customer, actor: User | None, latitude: Decimal | None, longitude: Decimal | None
) -> Customer:
    """Save where a customer is (D-172), from a stop of a driver's route; both empty forget it. The walk-in
    customer has no place."""
    if (latitude is None) != (longitude is None):
        raise ValidationError({"latitude": _("Indiquez la latitude et la longitude, ou aucune des deux.")})
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    if customer.is_walk_in:
        raise ValidationError({"detail": _("Le client de passage n'a pas d'adresse sur la carte.")})
    before = {"latitude": str(customer.latitude), "longitude": str(customer.longitude)}
    customer.latitude, customer.longitude = latitude, longitude
    customer.save(update_fields=["latitude", "longitude", "updated_at"])
    audit.record(
        organization=customer.organization,
        actor=actor,
        action="customer.location_set",
        target=customer,
        before=before,
        after={"latitude": str(latitude), "longitude": str(longitude)},
    )
    return customer


def ensure_walk_in_customer(*, organization: Organization, actor: User | None = None) -> Customer:
    """The organization's "Client de passage" record, created when missing (counter sales, P2-T04).

    It always pays at once: no credit limit, no payment terms.
    """
    Organization.objects.select_for_update().filter(pk=organization.pk).first()
    existing = Customer.objects.for_organization(organization).filter(is_walk_in=True).first()
    if existing is not None:
        return existing
    return create_customer(
        organization=organization,
        actor=actor,
        is_walk_in=True,
        name=WALK_IN_NAME,
        kind=CustomerKind.INDIVIDUAL,
    )


# ---- customer types (Paramètres › Types de clients, D-283) ----

_TYPE_CODE = re.compile(r"[^a-z0-9]+")


def ensure_default_customer_types(*, organization: Organization) -> None:
    """The seven customer types a new organization starts with (signal); those made before D-283 got them from
    the migration. Nothing changes when the organization already has types."""
    if CustomerType.objects.for_organization(organization).exists():
        return
    CustomerType.objects.bulk_create(
        [
            CustomerType(organization=organization, code=choice.value, label=str(choice.label), position=index)
            for index, choice in enumerate(CustomerKind)
        ],
        ignore_conflicts=True,
    )


def customer_types_of(organization: Organization) -> list[CustomerType]:
    """The organization's customer types, in their order (read only)."""
    return list(CustomerType.objects.for_organization(organization))


def _clean_type_label(organization: Organization, label: str, *, exclude: int | None = None) -> str:
    label = label.strip()
    if not label:
        raise ValidationError({"label": _("Le libellé est obligatoire.")})
    if len(label) > 60:
        raise ValidationError({"label": _("60 caractères au plus.")})
    others = CustomerType.objects.for_organization(organization)
    if exclude is not None:
        others = others.exclude(pk=exclude)
    if others.filter(label__iexact=label).exists():
        raise ValidationError({"label": _("Ce type de client existe déjà.")})
    return label


@transaction.atomic
def create_customer_type(*, organization: Organization, actor: User | None, label: str) -> CustomerType:
    """A new customer type, active, at the end of the list. Its code is made from the label once and never changes."""
    Organization.objects.select_for_update().filter(pk=organization.pk).first()
    existing = customer_types_of(organization)
    label = _clean_type_label(organization, label)
    base = _TYPE_CODE.sub("_", label.lower()).strip("_")[:16] or "type"
    codes = {row.code for row in existing}
    code, suffix = base, 2
    while code in codes:
        code, suffix = f"{base}_{suffix}"[:20], suffix + 1
    created = CustomerType.objects.create(
        organization=organization,
        code=code,
        label=label,
        position=max((row.position for row in existing), default=-1) + 1,
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="customer_type.created",
        target=created,
        after={"code": code, "label": label},
    )
    return created


@transaction.atomic
def update_customer_type(
    *, customer_type: CustomerType, actor: User | None, label: str | None = None, is_active: bool | None = None
) -> CustomerType:
    """Rename a customer type, or deactivate it (still shown on its customers, no longer offered) or bring it back."""
    locked = CustomerType.objects.select_for_update().get(pk=customer_type.pk)
    before = {"label": locked.label, "is_active": locked.is_active}
    if label is not None:
        locked.label = _clean_type_label(locked.organization, label, exclude=locked.pk)
    if is_active is not None:
        locked.is_active = is_active
    locked.save(update_fields=["label", "is_active", "updated_at"])
    after = {"label": locked.label, "is_active": locked.is_active}
    if after != before:
        audit.record(
            organization=locked.organization,
            actor=actor,
            action="customer_type.updated",
            target=locked,
            before=before,
            after=after,
        )
    return locked


@transaction.atomic
def delete_customer_type(*, customer_type: CustomerType, actor: User | None) -> None:
    """Delete a customer type that no customer has, archived ones included; else deactivate it instead."""
    locked = CustomerType.objects.select_for_update().get(pk=customer_type.pk)
    if Customer.objects.for_organization(locked.organization).filter(kind=locked.code).exists():
        raise ValidationError(
            {"detail": _("Des clients ont ce type : il ne peut pas être supprimé. Désactivez-le plutôt.")}
        )
    audit.record(
        organization=locked.organization,
        actor=actor,
        action="customer_type.deleted",
        before={"code": locked.code, "label": locked.label},
    )
    locked.delete()
