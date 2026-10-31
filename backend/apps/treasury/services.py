"""Every write of the treasury: banks, effets (cheques and traites) and their moves (D-197)."""

import datetime as dt
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import Organization, User
from apps.core.money import Number, checked_amount

from .models import (
    FIRST_STATUS,
    Bank,
    Instrument,
    InstrumentDirection,
    InstrumentEvent,
    InstrumentKind,
    InstrumentStatus,
)

if TYPE_CHECKING:
    from apps.partners.models import Customer, Supplier

# The Tunisian banks every organization starts with (code, name). Kept again in migration 0001 as data.
DEFAULT_BANKS = (
    ("AMEN", "Amen Bank"),
    ("ATB", "Arab Tunisian Bank"),
    ("ABC", "ABC Bank"),
    ("ATTIJARI", "Attijari Bank"),
    ("BARAKA", "Al Baraka Bank"),
    ("BH", "BH Bank"),
    ("BIAT", "Banque Internationale Arabe de Tunisie"),
    ("BNA", "Banque Nationale Agricole"),
    ("BT", "Banque de Tunisie"),
    ("BTE", "Banque de Tunisie et des Émirats"),
    ("BTK", "BTK Bank"),
    ("BTL", "Banque Tuniso-Libyenne"),
    ("BTS", "Banque Tunisienne de Solidarité"),
    ("CITI", "Citibank"),
    ("QNB", "QNB Tunis"),
    ("STB", "Société Tunisienne de Banque"),
    ("STUSID", "Stusid Bank"),
    ("UBCI", "Union Bancaire pour le Commerce et l'Industrie"),
    ("UIB", "Union Internationale de Banques"),
    ("WIFAK", "Wifak International Bank"),
    ("ZITOUNA", "Banque Zitouna"),
    ("POSTE", "La Poste Tunisienne"),
)

# The furthest an échéance may be from the day the effet is handed over (provisional, D-197).
MAX_DUE_DAYS = 365

# The moves an effet may make (T04 writes most of them; T01 only cancels).
ALLOWED_MOVES: dict[str, frozenset[str]] = {
    InstrumentStatus.PORTFOLIO: frozenset(
        {InstrumentStatus.DEPOSITED, InstrumentStatus.CASHED, InstrumentStatus.ENDORSED, InstrumentStatus.CANCELLED}
    ),
    InstrumentStatus.DEPOSITED: frozenset(
        {InstrumentStatus.CASHED, InstrumentStatus.UNPAID, InstrumentStatus.PORTFOLIO}
    ),
    InstrumentStatus.UNPAID: frozenset({InstrumentStatus.RETURNED, InstrumentStatus.PORTFOLIO}),
    InstrumentStatus.ISSUED: frozenset(
        {InstrumentStatus.DEBITED, InstrumentStatus.REJECTED, InstrumentStatus.CANCELLED}
    ),
    InstrumentStatus.REJECTED: frozenset({InstrumentStatus.ISSUED}),
}


def ensure_default_banks(*, organization: Organization) -> None:
    """Create the default banks the organization does not have yet (by code). Safe to call again."""
    Bank.objects.bulk_create(
        [
            Bank(organization=organization, code=code, name=name, position=(index + 1) * 10)
            for index, (code, name) in enumerate(DEFAULT_BANKS)
        ],
        ignore_conflicts=True,
    )


def _bank_snapshot(bank: Bank) -> dict[str, Any]:
    return {"code": bank.code, "name": bank.name, "is_active": bank.is_active}


def _checked_bank_fields(
    organization: Organization, *, code: str, name: str, exclude_id: int | None = None
) -> tuple[str, str]:
    errors: dict[str, str] = {}
    code = "".join(code.split()).upper()
    name = " ".join(name.split())
    if not code:
        errors["code"] = _("Indiquez le sigle de la banque.")
    elif len(code) > 20:
        errors["code"] = _("20 caractères au plus.")
    else:
        same = Bank.objects.for_organization(organization).filter(code__iexact=code)
        if exclude_id is not None:
            same = same.exclude(pk=exclude_id)
        if same.exists():
            errors["code"] = _("Une autre banque porte déjà ce sigle.")
    if not name:
        errors["name"] = _("Indiquez le nom de la banque.")
    elif len(name) > 100:
        errors["name"] = _("100 caractères au plus.")
    if errors:
        raise ValidationError(errors)
    return code, name


@transaction.atomic
def create_bank(*, organization: Organization, actor: User | None, code: str, name: str) -> Bank:
    """Add a bank to the organization's list, after the others."""
    code, name = _checked_bank_fields(organization, code=code, name=name)
    last = Bank.objects.for_organization(organization).aggregate(last=Max("position"))["last"] or 0
    bank = Bank.objects.create(organization=organization, code=code, name=name, position=last + 10)
    audit.record(organization=organization, actor=actor, action="bank.created", target=bank, after=_bank_snapshot(bank))
    return bank


@transaction.atomic
def update_bank(*, bank: Bank, actor: User | None, code: str, name: str, is_active: bool) -> Bank:
    """Rename a bank or take it off the lists; effets already drawn on it keep it."""
    bank = Bank.objects.select_for_update().get(pk=bank.pk)
    before = _bank_snapshot(bank)
    bank.code, bank.name = _checked_bank_fields(bank.organization, code=code, name=name, exclude_id=bank.pk)
    bank.is_active = is_active
    bank.save(update_fields=["code", "name", "is_active", "updated_at"])
    audit.record(
        organization=bank.organization,
        actor=actor,
        action="bank.updated",
        target=bank,
        before=before,
        after=_bank_snapshot(bank),
    )
    return bank


def instrument_errors(
    *,
    organization: Organization,
    direction: str,
    kind: str,
    number: str,
    bank: Bank | None,
    issued_on: dt.date,
    due_on: dt.date | None,
    customer: "Customer | None" = None,
    taken: Sequence[tuple[str, int | None, str]] = (),
    partial: bool = False,
) -> dict[str, str]:
    """What is wrong with an effet about to be written, by field (`number`, `bank`, `due_on`); empty when fine.

    `taken` holds the (kind, bank id, number) of the effets written just before in the same règlement, so one
    règlement cannot hold the same paper twice either. `partial` lets the number, the bank and the échéance be
    missing: an effet given through a screen that does not ask them (the port purchase, a receipt paid at once),
    to complete later. Our own cheque (issued) is one paper whoever it went to; a received one is the customer's.
    """
    errors: dict[str, str] = {}
    number = number.strip()
    if kind not in InstrumentKind.values:
        errors["method"] = _("Ce moyen de paiement n'est ni un chèque ni une traite.")
        return errors
    if not number and not partial:
        errors["number"] = (
            _("Indiquez le numéro du chèque.")
            if kind == InstrumentKind.CHEQUE
            else _("Indiquez le numéro de la traite.")
        )
    elif len(number) > 50:
        errors["number"] = _("50 caractères au plus.")
    if bank is None:
        if not partial:
            errors["bank"] = _("Choisissez la banque.")
    elif bank.organization_id != organization.pk:
        errors["bank"] = _("Banque inconnue.")
    elif not bank.is_active:
        errors["bank"] = _("Cette banque n'est plus proposée.")
    latest = issued_on + dt.timedelta(days=MAX_DUE_DAYS)
    if due_on is None:
        if kind == InstrumentKind.BILL and not partial:
            errors["due_on"] = _("Indiquez l'échéance de la traite.")
    elif due_on > latest:
        errors["due_on"] = _("L'échéance ne peut pas dépasser un an (%(day)s au plus tard).") % {
            "day": latest.strftime("%d/%m/%Y")
        }
    elif kind == InstrumentKind.BILL and due_on < issued_on:
        errors["due_on"] = _("L'échéance d'une traite ne peut pas précéder le jour du règlement.")
    elif kind == InstrumentKind.CHEQUE and due_on < issued_on - dt.timedelta(days=MAX_DUE_DAYS):
        errors["due_on"] = _("Ce chèque a plus d'un an : il ne peut plus être encaissé.")
    if number and "number" not in errors and "bank" not in errors and bank is not None:
        key = (kind, bank.pk, number.casefold())
        if key in {(row_kind, row_bank, row_number.casefold()) for row_kind, row_bank, row_number in taken}:
            errors["number"] = _("Ce numéro est déjà sur une autre ligne de ce règlement.")
        else:
            same = Instrument.objects.for_organization(organization).filter(
                direction=direction, kind=kind, bank=bank, number__iexact=number
            )
            same = same.exclude(status=InstrumentStatus.CANCELLED)
            if customer is not None:
                same = same.filter(customer=customer)
            existing = same.first()
            if existing is not None:
                errors["number"] = _("Ce %(kind)s est déjà enregistré (%(source)s).") % {
                    "kind": existing.get_kind_display().lower(),
                    "source": existing.source_number or existing.number,
                }
    return errors


def register_instrument(
    *,
    organization: Organization,
    actor: User | None,
    direction: str,
    kind: str,
    number: str,
    bank: Bank | None,
    amount: Number,
    issued_on: dt.date,
    due_on: dt.date | None,
    drawer: str = "",
    customer: "Customer | None" = None,
    supplier: "Supplier | None" = None,
    source_number: str = "",
    partial: bool = False,
) -> Instrument:
    """Write a received or issued effet in its first status. Runs inside the règlement's transaction; the caller
    checked it with `instrument_errors` first (checked again here, so a bad effet is never written). `partial` as
    in `instrument_errors`: a traite without its échéance falls due on the day it was given."""
    errors = instrument_errors(
        organization=organization,
        direction=direction,
        kind=kind,
        number=number,
        bank=bank,
        issued_on=issued_on,
        due_on=due_on,
        customer=customer,
        partial=partial,
    )
    if direction not in InstrumentDirection.values:
        errors["direction"] = _("Sens inconnu.")
    value = checked_amount(amount)
    if value <= 0:
        errors["amount"] = _("Le montant doit être supérieur à zéro.")
    if errors:
        raise ValidationError(errors)
    status = FIRST_STATUS[InstrumentDirection(direction)]
    instrument = Instrument.objects.create(
        organization=organization,
        direction=direction,
        kind=kind,
        number=number.strip(),
        bank=bank,
        drawer=" ".join(drawer.split())[:150],
        amount=value,
        issued_on=issued_on,
        # A cheque handed over with no date on it may be cashed at once.
        due_on=due_on or issued_on,
        status=status,
        customer=customer if direction == InstrumentDirection.RECEIVED else None,
        supplier=supplier if direction == InstrumentDirection.ISSUED else None,
        source_number=source_number,
        created_by=actor,
    )
    InstrumentEvent.objects.create(
        organization=organization, instrument=instrument, to_status=status, happened_on=issued_on, actor=actor
    )
    return instrument


def _move(instrument: Instrument, *, to_status: str, happened_on: dt.date, actor: User | None, note: str = "") -> None:
    if to_status not in ALLOWED_MOVES.get(instrument.status, frozenset()):
        raise ValidationError(
            _("%(instrument)s est « %(status)s » : il ne peut pas passer à « %(to)s ».")
            % {
                "instrument": instrument,
                "status": instrument.get_status_display(),
                "to": InstrumentStatus(to_status).label,
            }
        )
    InstrumentEvent.objects.create(
        organization=instrument.organization,
        instrument=instrument,
        from_status=instrument.status,
        to_status=to_status,
        happened_on=happened_on,
        note=note.strip()[:255],
        actor=actor,
    )
    instrument.status = to_status
    instrument.save(update_fields=["status", "updated_at"])


def locked_instruments(instrument_ids: Sequence[int]) -> list[Instrument]:
    """The effets, locked in a fixed order (by id), so two moves of the same paper wait for each other."""
    return list(
        Instrument.objects.select_for_update(of=("self",))
        .select_related("organization")
        .filter(pk__in=instrument_ids)
        .order_by("id")
    )


def check_cancellable(instrument_ids: Sequence[int]) -> None:
    """Refuse when one of the effets moved on from its first status (at the bank, cashed, unpaid, endorsed...):
    voiding its règlement would leave a paper the bank still handles."""
    moved = [
        row
        for row in locked_instruments(instrument_ids)
        if row.status != FIRST_STATUS[InstrumentDirection(row.direction)]
    ]
    if moved:
        row = moved[0]
        raise ValidationError(
            _("%(instrument)s est déjà « %(status)s » : ce règlement ne peut plus être annulé.")
            % {"instrument": row, "status": row.get_status_display()}
        )


def cancel_instruments(
    *, instrument_ids: Sequence[int], actor: User | None, happened_on: dt.date, note: str = ""
) -> None:
    """Cancel the effets of a voided règlement. Every one must still be in its first status (`check_cancellable`)."""
    check_cancellable(instrument_ids)
    for instrument in locked_instruments(instrument_ids):
        _move(instrument, to_status=InstrumentStatus.CANCELLED, happened_on=happened_on, actor=actor, note=note)
