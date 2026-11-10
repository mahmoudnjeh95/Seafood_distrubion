"""Who may do what, section by section: the access matrix of roles and people (D-306).

The application is cut into **sections** (one per entry of the admin menu, roughly). Each person has a
**level** per section:

- ``none``: the section is hidden and its API answers 403;
- ``read``: they see it;
- ``write``: they work in it, as a manager does;
- ``full``: they also do what only the owner does there (approve, write off, change the rules).

Where a level comes from:

- the owner has ``full`` everywhere and a driver works only in the phone app: neither is governed by the matrix;
- a **custom role** (``Role.CUSTOM``) the owner made in Paramètres › Rôles has its own matrix;
- the owner may set a person's own level for some sections (``Membership.access_overrides``), over their role.

The API of a manager or an accountant keeps the permission classes it always had; only a section where that
person has their own level is decided by the matrix. A custom role is decided by the matrix everywhere.
``BUILTIN`` repeats what the classes allow the built-in roles, for the screens and for ``can``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from .models import Membership, Role


class Level(StrEnum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    FULL = "full"


RANK = {Level.NONE: 0, Level.READ: 1, Level.WRITE: 2, Level.FULL: 3}
ALL_LEVELS = (Level.NONE, Level.READ, Level.WRITE, Level.FULL)
READ_ONLY = (Level.NONE, Level.READ)
# The writes there are the owner's alone (payslips, partners' shares): reading, or everything.
READ_OR_FULL = (Level.NONE, Level.READ, Level.FULL)


@dataclass(frozen=True)
class Section:
    key: str
    label: str | Promise
    group: str | Promise
    levels: tuple[Level, ...] = ALL_LEVELS


_STEERING = _("Pilotage")
_SALES = _("Ventes")
_GOODS = _("Marchandise")
_FINANCE = _("Finance")
_SITE = _("Site web")
_ADMIN = _("Administration")

SECTIONS: tuple[Section, ...] = (
    Section("dashboard", _("Tableau de bord"), _STEERING, READ_ONLY),
    Section("reports", _("Rapports"), _STEERING, READ_ONLY),
    Section("quotes", _("Devis"), _SALES),
    Section("sales", _("Bons de livraison"), _SALES),
    Section("invoices", _("Factures et avoirs"), _SALES),
    Section("customers", _("Clients"), _SALES),
    Section("prices", _("Prix du jour"), _SALES),
    Section("stock", _("Stock, pertes et inventaires"), _GOODS),
    Section("transfers", _("Transferts et chargements"), _GOODS),
    Section("fleet", _("Camions, flotte et entretien"), _GOODS),
    Section("day_closings", _("Journées des chauffeurs"), _GOODS),
    Section("products", _("Produits"), _GOODS),
    Section("purchases", _("Achats"), _GOODS),
    Section("suppliers", _("Fournisseurs"), _GOODS),
    Section("documents", _("Documents"), _FINANCE),
    Section("expenses", _("Charges"), _FINANCE),
    Section("payroll", _("Salaires"), _FINANCE, READ_OR_FULL),
    Section("partnerships", _("Partenariats"), _FINANCE, READ_OR_FULL),
    Section("closing", _("Résultats des lots et clôture"), _FINANCE),
    Section("treasury", _("Trésorerie et règlements"), _FINANCE),
    Section("website", _("Site web"), _SITE),
    Section("settings", _("Paramètres (sauf utilisateurs et rôles)"), _ADMIN),
)
SECTION_BY_KEY: dict[str, Section] = {section.key: section for section in SECTIONS}


def _everywhere(level: Level) -> dict[str, Level]:
    return {section.key: level for section in SECTIONS}


# What the permission classes give the built-in roles, as a matrix. The owner's `full` everywhere is the truth;
# for the manager and the accountant it matches the classes section by section (checked by the tests).
BUILTIN: dict[str, dict[str, Level]] = {
    Role.OWNER: _everywhere(Level.FULL),
    Role.MANAGER: {
        **_everywhere(Level.WRITE),
        "dashboard": Level.NONE,
        "reports": Level.READ,
        "payroll": Level.NONE,
        "partnerships": Level.NONE,
        "closing": Level.NONE,
        "settings": Level.NONE,
    },
    Role.ACCOUNTANT: {
        **_everywhere(Level.READ),
        "closing": Level.WRITE,
        "settings": Level.NONE,
    },
    Role.DRIVER: _everywhere(Level.NONE),
}

# API routes (after `api/v1/`) and their section, the most precise first. A route matches a prefix when it is the
# prefix or goes on with "/". `True` marks the lists every office person reads, whatever their levels, because
# the forms of the other sections pick from them (a product, a customer, a cold room, a truck).
ROUTES: tuple[tuple[str, str, bool], ...] = (
    # Sales and invoicing
    ("customers/<int:customer_id>/balance", "treasury", False),
    ("customers/<int:customer_id>/write-off", "treasury", False),
    ("customer-types", "customers", True),
    ("customers", "customers", True),
    ("quotes", "quotes", False),
    ("batches/<int:batch_id>/sales", "sales", False),
    ("sales", "sales", False),
    ("finance-settings", "invoices", True),
    ("invoices", "invoices", False),
    ("credit-notes", "invoices", False),
    ("refunds", "invoices", False),
    ("withholding-certificates", "invoices", False),
    ("price-board", "prices", True),
    ("price-lists", "prices", True),
    # Treasury
    ("customer-payments", "treasury", False),
    ("customer-effets", "treasury", False),
    ("receivables", "treasury", False),
    ("withholding-summary", "treasury", False),
    ("supplier-balances", "treasury", False),
    ("supplier-payments", "treasury", False),
    ("supplier-settlements", "treasury", False),
    ("supplier-effets", "treasury", False),
    ("supplier-plan-lines", "treasury", False),
    ("treasury", "treasury", False),
    ("notifications/payment-orders", "treasury", False),
    ("notifications/recipients", "treasury", True),
    # Purchases and suppliers
    ("supplier-invoices", "purchases", False),
    ("supplier-credit-notes", "purchases", False),
    ("supplier-debts", "purchases", False),
    ("receipts", "purchases", False),
    ("purchase-orders", "purchases", False),
    ("price-requests", "purchases", False),
    ("field-purchases", "purchases", False),
    ("suppliers", "suppliers", True),
    # Products
    ("categories", "products", True),
    ("products", "products", True),
    ("vat-products", "products", True),
    ("vat-rates", "settings", True),
    # Stock
    ("batches/<int:batch_id>/recall", "stock", False),
    ("batches", "stock", True),
    ("stock/<int:product_id>/batches", "stock", True),
    ("stock-settings", "stock", False),
    ("stock", "stock", False),
    ("locations", "stock", True),
    ("losses", "stock", False),
    ("counts", "stock", False),
    ("boxes", "stock", False),
    ("temperatures", "stock", False),
    ("transformations", "stock", False),
    ("cold-chain", "stock", False),
    ("transfers", "transfers", False),
    # Trucks and the drivers' days
    ("trucks", "fleet", True),
    ("truck-assignments", "fleet", False),
    ("day-funds", "fleet", False),
    ("fleet", "fleet", False),
    ("maintenance-settings", "fleet", False),
    ("maintenance-types", "fleet", False),
    ("maintenance-plans", "fleet", False),
    ("papers", "fleet", False),
    ("odometer-readings", "fleet", False),
    ("day-overview", "day_closings", False),
    ("day-closings", "day_closings", False),
    ("sync-problems", "day_closings", False),
    # Documents (a PDF or an e-mail goes by the kind of document, see DOCUMENT_KINDS)
    ("document-index", "documents", False),
    ("attachments", "documents", False),
    # Expenses
    ("expense-categories", "expenses", True),
    ("expenses", "expenses", False),
    ("lot-costs", "expenses", False),
    ("day-labourers", "expenses", False),
    ("day-labour", "expenses", False),
    ("cold-room-weights", "expenses", False),
    ("cold-room-shares", "expenses", False),
    ("cold-room-costs", "expenses", False),
    ("cold-room-estimate", "expenses", False),
    ("electricity-bills", "expenses", False),
    ("recurring-costs", "expenses", False),
    ("general-costs", "expenses", False),
    # Payroll
    ("employees", "payroll", False),
    ("salary-records", "payroll", False),
    ("salary-payments", "payroll", False),
    ("payroll-summary", "payroll", False),
    ("lot-work-days", "payroll", False),
    # Partners' shares, lot results and the month
    ("partnerships", "partnerships", False),
    ("partners", "partnerships", False),
    ("lots/<int:batch_id>/settlement", "partnerships", False),
    ("lots/<int:batch_id>/settle", "partnerships", False),
    ("lots", "closing", False),
    ("lot-figures", "closing", False),
    ("months", "closing", False),
    ("dashboard", "dashboard", False),
    ("reports", "reports", False),
    # Website
    ("site-settings", "website", False),
    ("site-products", "website", False),
    ("web-requests", "website", False),
    # Settings (users, roles and the import stay the owner's: they are in no section)
    ("numbering", "settings", False),
    ("einvoicing-settings", "settings", True),
    ("organizations", "settings", True),
)

# The section of a printed document (`documents/<kind>/<id>/pdf` and its e-mail).
DOCUMENT_KINDS: dict[str, str] = {
    "quote": "quotes",
    "delivery_note": "sales",
    "invoice": "invoices",
    "credit_note": "invoices",
    "receipt": "treasury",
    "supplier_receipt": "treasury",
    "bank_deposit": "treasury",
    "partner_statement": "partnerships",
}
_DOCUMENTS_ROUTE = "documents/<str:kind>"
API_PREFIX = "api/v1/"


def route_section(route: str, kwargs: Mapping[str, Any] | None = None) -> tuple[str, bool] | None:
    """The section of an API route (written as in urls.py, without `api/v1/`) and whether every office person
    reads it. None for the routes in no section: logging in, one's own profile, the driver's phone (`my-…`),
    users, roles and the import (the owner's)."""
    if route == _DOCUMENTS_ROUTE or route.startswith(_DOCUMENTS_ROUTE + "/"):
        kind = str((kwargs or {}).get("kind", ""))
        section = DOCUMENT_KINDS.get(kind)
        return (section, False) if section else ("documents", False)
    for prefix, section, lookup in ROUTES:
        if route == prefix or route.startswith(prefix + "/"):
            return section, lookup
    return None


# ---- Levels of a person ----


def is_office(membership: Membership) -> bool:
    return membership.role != Role.DRIVER


def overrides_of(membership: Membership) -> dict[str, Level]:
    raw = membership.access_overrides or {}
    return {key: Level(value) for key, value in raw.items() if key in SECTION_BY_KEY and value in Level}


def role_matrix(membership: Membership) -> dict[str, Level]:
    """The levels of the person's role, before their own ones."""
    if membership.role == Role.CUSTOM:
        raw = membership.custom_role.access if membership.custom_role is not None else {}
        return {
            section.key: Level(raw[section.key]) if raw.get(section.key) in Level else Level.NONE
            for section in SECTIONS
        }
    return dict(BUILTIN.get(membership.role, _everywhere(Level.NONE)))


def access_of(membership: Membership) -> dict[str, Level]:
    """Every section with this person's level: their role's, replaced by their own where the owner set one."""
    levels = role_matrix(membership)
    if membership.role in (Role.OWNER, Role.DRIVER):
        return levels
    levels.update(overrides_of(membership))
    return levels


def level_of(membership: Membership, section: str) -> Level:
    return access_of(membership).get(section, Level.NONE)


def can(membership: Membership, section: str, level: Level | str) -> bool:
    """Whether this person has at least `level` in `section`. The views use it where the owner alone could act
    (`Level.FULL`) or where owners and managers could (`Level.WRITE`)."""
    return RANK[level_of(membership, section)] >= RANK[Level(level)]


def governs(membership: Membership, section: str) -> bool:
    """Whether the matrix, not the old permission classes, decides this person's API calls in this section."""
    if membership.role == Role.CUSTOM:
        return True
    if membership.role in (Role.MANAGER, Role.ACCOUNTANT):
        return section in overrides_of(membership)
    return False


def decide(
    membership: Membership, *, route: str, kwargs: Mapping[str, Any], method: str, owner_writes: bool
) -> bool | None:
    """The matrix's answer for one API call, or None when the permission classes decide.

    Reading needs `read` (or the route is a list every office person reads); writing needs `write`, or `full`
    where the classes leave the writes to the owner alone (`owner_writes`)."""
    if route.startswith(API_PREFIX):
        route = route[len(API_PREFIX) :]
    found = route_section(route, kwargs)
    if found is None:
        return None
    section, lookup = found
    if not governs(membership, section):
        return None
    level = level_of(membership, section)
    if method in ("GET", "HEAD", "OPTIONS"):
        return RANK[level] >= RANK[Level.READ] or lookup
    needed = Level.FULL if owner_writes else Level.WRITE
    return RANK[level] >= RANK[needed]


def clean_matrix(raw: Mapping[str, Any], *, partial: bool) -> dict[str, str]:
    """A matrix typed by the owner, checked: known sections, and a level each section offers. `partial`: the
    sections left out keep their role's level (a person's own levels); otherwise they are "none" (a role)."""
    from django.core.exceptions import ValidationError

    errors: dict[str, str] = {}
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        section = SECTION_BY_KEY.get(key)
        if section is None:
            errors[key] = str(_("Section inconnue."))
        elif value not in section.levels:
            errors[key] = str(_("Niveau non proposé pour cette section."))
        elif partial or value != Level.NONE:
            cleaned[key] = str(value)
    if errors:
        raise ValidationError(errors)
    return cleaned
