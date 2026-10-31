"""Every number the application gives out (D-223): customers, suppliers, employees, products and each document kind.

A kind has a key (its name in the code), a French label for the Paramètres page, a default prefix and a padding.
The organization may change the prefix of each kind there (`NumberPrefix`); the counter (`NumberSeries`) is never
reset, so a new prefix goes on from the last number given. A yearly kind (quotes, invoices...) restarts at 1 every
year: FA-2026-0001. The defaults are the prefixes the documents already carried (D-057, D-120), so nothing changes
for an existing installation until the owner edits them.

`next_number` takes the counter's row lock. Call it inside the transaction that saves the record, after every check:
a refusal then rolls the counter back with everything else, so there is no gap.
"""

import re
from dataclasses import dataclass
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import NumberPrefix, NumberSeries, Organization


@dataclass(frozen=True)
class NumberKind:
    key: str
    label: Any
    group: Any
    prefix: str
    padding: int
    yearly: bool = False
    # Between the prefix and the number: "C-001", but the owner's product codes are "ART0002".
    separator: str = "-"


_PARTNERS = _("Partenaires et produits")
_SALES = _("Ventes")
_PURCHASES = _("Achats")
_STOCK = _("Stock")
_TREASURY = _("Trésorerie et charges")
_PAYROLL = _("Paie")

NUMBER_KINDS: tuple[NumberKind, ...] = (
    NumberKind("customer", _("Client"), _PARTNERS, "C", 3),
    NumberKind("supplier", _("Fournisseur"), _PARTNERS, "F", 3),
    NumberKind("product", _("Produit"), _PARTNERS, "ART", 4, separator=""),
    NumberKind("employee", _("Employé"), _PAYROLL, "E", 3),
    NumberKind("quote", _("Devis"), _SALES, "DV", 4, yearly=True),
    NumberKind("sale", _("Vente (comptoir)"), _SALES, "VE", 4),
    NumberKind("delivery_note", _("Bon de livraison (BL)"), _SALES, "BL", 4, yearly=True),
    NumberKind("invoice", _("Facture"), _SALES, "FA", 4, yearly=True),
    NumberKind("credit_note", _("Avoir"), _SALES, "AV", 4, yearly=True),
    NumberKind("payment", _("Règlement client"), _SALES, "RG", 4),
    NumberKind("opening_receivable", _("Solde d'ouverture client"), _SALES, "OUV", 4, yearly=True),
    NumberKind("purchase_order", _("Commande d'achat"), _PURCHASES, "BA", 4),
    NumberKind("receipt", _("Bon de réception (BR)"), _PURCHASES, "BR", 4),
    NumberKind("supplier_invoice", _("Facture fournisseur"), _PURCHASES, "FF", 4),
    NumberKind("supplier_payment", _("Règlement fournisseur"), _PURCHASES, "RF", 4, yearly=True),
    NumberKind("field_purchase", _("Achat terrain"), _PURCHASES, "AT", 4, yearly=True),
    NumberKind("batch", _("Lot"), _STOCK, "L", 4),
    NumberKind("transfer", _("Transfert"), _STOCK, "TR", 4),
    NumberKind("loss", _("Perte"), _STOCK, "PE", 4),
    NumberKind("count", _("Inventaire"), _STOCK, "INV", 4),
    NumberKind("expense", _("Dépense"), _TREASURY, "DP", 4, yearly=True),
    NumberKind("deposit", _("Remise en banque"), _TREASURY, "RB", 4, yearly=True),
    NumberKind("salary_payment", _("Paiement de salaire"), _PAYROLL, "PS", 4, yearly=True),
)

KIND_BY_KEY: dict[str, NumberKind] = {kind.key: kind for kind in NUMBER_KINDS}
# Capitals and digits only, so a number reads the same on paper, on the phone and in a search.
PREFIX_PATTERN = re.compile(r"^[A-Z0-9]{1,6}$")


def kind_of(key: str) -> NumberKind:
    """The kind behind a key. An unknown key is a bug in the caller, not a user error."""
    return KIND_BY_KEY[key]


def prefixes_of(organization: Organization) -> dict[str, str]:
    """The prefix in force for every kind: the organization's own, else the default."""
    chosen = dict(NumberPrefix.objects.for_organization(organization).values_list("kind", "prefix"))
    return {kind.key: chosen.get(kind.key, kind.prefix) for kind in NUMBER_KINDS}


def _counted_year(kind: NumberKind, year: int | None) -> int:
    """Yearly kinds count per year (today's unless the caller says which); the others use year 0."""
    if not kind.yearly:
        return 0
    return year if year is not None else timezone.localdate().year


def _format(kind: NumberKind, prefix: str, year: int, number: int) -> str:
    padded = f"{number:0{kind.padding}d}"
    return f"{prefix}-{year}-{padded}" if kind.yearly else f"{prefix}{kind.separator}{padded}"


def next_number(organization: Organization, key: str, *, year: int | None = None) -> str:
    """Take the next number of a kind: "FA-2026-0007", "C-004". Locks the counter until the transaction ends."""
    kind = kind_of(key)
    counted_year = _counted_year(kind, year)
    NumberSeries.objects.bulk_create(
        [NumberSeries(organization=organization, kind=key, year=counted_year)], ignore_conflicts=True
    )
    series = NumberSeries.objects.select_for_update().get(organization=organization, kind=key, year=counted_year)
    series.last_number += 1
    series.save(update_fields=["last_number"])
    prefix = prefixes_of(organization)[key]
    return _format(kind, prefix, counted_year, series.last_number)


def _highest_in_use(organization: Organization, key: str, records: QuerySet[Any]) -> int:
    """The highest number of this kind already carried by a record: where the counter of a new organization starts,
    so the next customer is not C-001 when the company typed C-007 by hand."""
    kind = kind_of(key)
    prefix = prefixes_of(organization)[key]
    pattern = re.compile(rf"^{re.escape(prefix)}{re.escape(kind.separator)}(\d+)$", re.IGNORECASE)
    matches = (pattern.match(reference) for reference in records.values_list("reference", flat=True))
    return max((int(match.group(1)) for match in matches if match), default=0)


def next_free_reference(organization: Organization, key: str, records: QuerySet[Any]) -> str:
    """The next number of a kind that no record of `records` (the organization's customers, products...) carries
    already. The counter starts after the highest number in use; a reference typed by hand (such as the owner's
    ART0047) is skipped, never reused."""
    if not NumberSeries.objects.for_organization(organization).filter(kind=key, year=0).exists():
        seed = _highest_in_use(organization, key, records)
        NumberSeries.objects.bulk_create(
            [NumberSeries(organization=organization, kind=key, last_number=seed)], ignore_conflicts=True
        )
    while True:
        candidate = next_number(organization, key)
        if not records.filter(reference__iexact=candidate).exists():
            return candidate


def next_preview(organization: Organization, key: str, prefixes: dict[str, str] | None = None) -> str:
    """The number the next record of a kind will get, without taking it (Paramètres)."""
    kind = kind_of(key)
    counted_year = _counted_year(kind, None)
    last = (
        NumberSeries.objects.for_organization(organization)
        .filter(kind=key, year=counted_year)
        .values_list("last_number", flat=True)
        .first()
    ) or 0
    prefix = (prefixes or prefixes_of(organization))[key]
    return _format(kind, prefix, counted_year, last + 1)
