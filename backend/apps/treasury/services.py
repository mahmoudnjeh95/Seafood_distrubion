"""Every write of the treasury: banks, effets (cheques and traites) and their moves (D-197); our accounts, their
movements, transfers between them and the arrêté de caisse (D-219)."""

import datetime as dt
import re
from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit, numbering
from apps.core.models import Organization, User
from apps.core.money import Number, checked_amount, money

from .models import (
    FIRST_STATUS,
    AccountKind,
    AccountTransfer,
    Bank,
    CashCount,
    CashType,
    Deposit,
    Instrument,
    InstrumentDirection,
    InstrumentEvent,
    InstrumentKind,
    InstrumentStatus,
    MovementKind,
    TransferKind,
    TreasuryAccount,
    TreasuryMovement,
)

if TYPE_CHECKING:
    from apps.partners.models import Customer, Supplier

# A SWIFT code is 8 or 11 characters. An IBAN is written as the bank's documents show it (two letters, two digits,
# four characters, four digits, three digits); spaces are dropped before the check.
SWIFT_RE = re.compile(r"[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?")
IBAN_RE = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{4}[0-9]{3}")

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
    # The bank may take back a cheque it had credited (D-217).
    InstrumentStatus.CASHED: frozenset({InstrumentStatus.UNPAID}),
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
    return {
        "code": bank.code,
        "name": bank.name,
        "swift": bank.swift,
        "address": bank.address,
        "is_active": bank.is_active,
    }


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


def _checked_bank_details(swift: str, address: str) -> tuple[str, str]:
    """The SWIFT code (8 or 11 characters, spaces dropped) and the branch address; both may be left blank."""
    errors: dict[str, str] = {}
    swift = "".join(swift.split()).upper()
    address = " ".join(address.split())
    if swift and not SWIFT_RE.fullmatch(swift):
        errors["swift"] = _("Le code SWIFT compte 8 ou 11 caractères.")
    if len(address) > 255:
        errors["address"] = _("255 caractères au plus.")
    if errors:
        raise ValidationError(errors)
    return swift, address


@transaction.atomic
def create_bank(
    *, organization: Organization, actor: User | None, code: str, name: str, swift: str = "", address: str = ""
) -> Bank:
    """Add a bank to the organization's list, after the others."""
    code, name = _checked_bank_fields(organization, code=code, name=name)
    swift, address = _checked_bank_details(swift, address)
    last = Bank.objects.for_organization(organization).aggregate(last=Max("position"))["last"] or 0
    bank = Bank.objects.create(
        organization=organization, code=code, name=name, swift=swift, address=address, position=last + 10
    )
    audit.record(organization=organization, actor=actor, action="bank.created", target=bank, after=_bank_snapshot(bank))
    return bank


@transaction.atomic
def update_bank(
    *, bank: Bank, actor: User | None, code: str, name: str, is_active: bool, swift: str = "", address: str = ""
) -> Bank:
    """Rename a bank, give its SWIFT code and address, or take it off the lists; effets already drawn on it keep it."""
    bank = Bank.objects.select_for_update().get(pk=bank.pk)
    before = _bank_snapshot(bank)
    bank.code, bank.name = _checked_bank_fields(bank.organization, code=code, name=name, exclude_id=bank.pk)
    bank.swift, bank.address = _checked_bank_details(swift, address)
    bank.is_active = is_active
    bank.save(update_fields=["code", "name", "swift", "address", "is_active", "updated_at"])
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
    account: TreasuryAccount | None = None,
) -> Instrument:
    """Write a received or issued effet in its first status. An issued one may name our bank `account` it will be
    debited from (D-219). Runs inside the règlement's transaction; the caller
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
        account=account if direction == InstrumentDirection.ISSUED else None,
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
    event = InstrumentEvent.objects.create(
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
    _post_effet_movement(instrument, event)


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


# ---- The portfolio: remise en banque, encaissé, débité (P9-T04a, D-216) ----

# The effets one action may move at once.
MAX_BATCH = 200


def _batch(
    organization: Organization,
    instrument_ids: Sequence[int],
    *,
    direction: str,
    statuses: frozenset[str],
    happened_on: dt.date | None,
) -> list[Instrument]:
    """The effets named, locked, once checked: all of the organization, of `direction`, in one of `statuses`; and
    a day not in the future. Every problem comes back at once."""
    errors: dict[str, str] = {}
    ids = list(dict.fromkeys(instrument_ids))
    if not ids:
        errors["instruments"] = _("Choisissez au moins un effet.")
    elif len(ids) > MAX_BATCH:
        errors["instruments"] = _("%(count)s effets au plus à la fois.") % {"count": MAX_BATCH}
    if happened_on is None:
        errors["day"] = _("Indiquez le jour.")
    elif happened_on > timezone.localdate():
        errors["day"] = _("Le jour ne peut pas être dans le futur.")
    if errors:
        raise ValidationError(errors)
    rows = [row for row in locked_instruments(ids) if row.organization_id == organization.pk]
    if len(rows) != len(ids):
        raise ValidationError({"instruments": _("Effet inconnu.")})
    wrong = [row for row in rows if row.direction != direction or row.status not in statuses]
    if wrong:
        row = wrong[0]
        raise ValidationError(
            {
                "instruments": _("%(instrument)s (%(source)s) est « %(status)s » : il ne peut pas faire ce pas.")
                % {"instrument": row, "source": row.source_number, "status": row.get_status_display()}
            }
        )
    return rows


def _record(
    organization: Organization, actor: User | None, action: str, rows: Sequence[Instrument], **after: Any
) -> None:
    audit.record(
        organization=organization,
        actor=actor,
        action=action,
        target=rows[0],
        after={"instruments": [f"{row} ({row.source_number})" for row in rows], **after},
    )


@transaction.atomic
def deposit_instruments(
    *,
    organization: Organization,
    actor: User | None,
    instrument_ids: Sequence[int],
    bank: Bank | None,
    deposited_on: dt.date | None,
    notes: str = "",
    account: TreasuryAccount | None = None,
) -> Deposit:
    """Hand received effets in portfolio to one of our bank accounts on one day: a bordereau "RB-…" holding them,
    each effet "Remis en banque". Its PDF lists them for the bank. The `account` (D-219) gives its bank; without
    one, the bank's account (else the main bank account) is credited when the effets are cashed."""
    if account is not None:
        if account.organization_id != organization.pk or account.kind != AccountKind.BANK or not account.is_active:
            raise ValidationError({"account": _("Choisissez un de nos comptes bancaires.")})
        bank = account.bank or bank
    if bank is None or bank.organization_id != organization.pk or not bank.is_active:
        raise ValidationError({"bank": _("Choisissez la banque.")})
    rows = _batch(
        organization,
        instrument_ids,
        direction=InstrumentDirection.RECEIVED,
        statuses=frozenset({InstrumentStatus.PORTFOLIO}),
        happened_on=deposited_on,
    )
    assert deposited_on is not None  # checked by _batch
    deposit = Deposit.objects.create(
        organization=organization,
        number=numbering.next_number(organization, "deposit", year=deposited_on.year),
        bank=bank,
        account=account or bank_account_for(organization, bank),
        deposited_on=deposited_on,
        notes=notes.strip()[:255],
        created_by=actor,
    )
    for row in rows:
        _move(row, to_status=InstrumentStatus.DEPOSITED, happened_on=deposited_on, actor=actor, note=deposit.number)
        row.deposit = deposit
        row.save(update_fields=["deposit", "updated_at"])
    _record(organization, actor, "treasury.deposited", rows, deposit=deposit.number, bank=bank.code)
    return deposit


@transaction.atomic
def cash_instruments(
    *, organization: Organization, actor: User | None, instrument_ids: Sequence[int], cashed_on: dt.date | None
) -> list[Instrument]:
    """The bank credited these received effets (at the bank, or cashed at its counter straight from the portfolio)."""
    rows = _batch(
        organization,
        instrument_ids,
        direction=InstrumentDirection.RECEIVED,
        statuses=frozenset({InstrumentStatus.DEPOSITED, InstrumentStatus.PORTFOLIO}),
        happened_on=cashed_on,
    )
    assert cashed_on is not None
    for row in rows:
        _move(row, to_status=InstrumentStatus.CASHED, happened_on=cashed_on, actor=actor)
    _record(organization, actor, "treasury.cashed", rows, day=cashed_on.isoformat())
    return rows


@transaction.atomic
def withdraw_instruments(
    *,
    organization: Organization,
    actor: User | None,
    instrument_ids: Sequence[int],
    withdrawn_on: dt.date | None,
    note: str = "",
) -> list[Instrument]:
    """Take effets back from the bank before it cashed them: they are in portfolio again (their bordereau keeps them
    listed, with this step in their history)."""
    rows = _batch(
        organization,
        instrument_ids,
        direction=InstrumentDirection.RECEIVED,
        statuses=frozenset({InstrumentStatus.DEPOSITED}),
        happened_on=withdrawn_on,
    )
    assert withdrawn_on is not None
    for row in rows:
        _move(row, to_status=InstrumentStatus.PORTFOLIO, happened_on=withdrawn_on, actor=actor, note=note)
    _record(organization, actor, "treasury.withdrawn", rows, day=withdrawn_on.isoformat())
    return rows


@transaction.atomic
def debit_instruments(
    *, organization: Organization, actor: User | None, instrument_ids: Sequence[int], debited_on: dt.date | None
) -> list[Instrument]:
    """Our bank paid these cheques and traites we gave: they are done."""
    rows = _batch(
        organization,
        instrument_ids,
        direction=InstrumentDirection.ISSUED,
        statuses=frozenset({InstrumentStatus.ISSUED}),
        happened_on=debited_on,
    )
    assert debited_on is not None
    for row in rows:
        _move(row, to_status=InstrumentStatus.DEBITED, happened_on=debited_on, actor=actor)
    _record(organization, actor, "treasury.debited", rows, day=debited_on.isoformat())
    return rows


def mark_unpaid(
    *, organization: Organization, actor: User | None, instrument_id: int, unpaid_on: dt.date | None, note: str
) -> Instrument:
    """The bank refused a received effet (at the bank, or taken back after crediting it): "Impayé". Called by the
    règlement's app, which raises the customer's balance again in the same transaction (D-217)."""
    rows = _batch(
        organization,
        [instrument_id],
        direction=InstrumentDirection.RECEIVED,
        statuses=frozenset({InstrumentStatus.DEPOSITED, InstrumentStatus.CASHED}),
        happened_on=unpaid_on,
    )
    assert unpaid_on is not None
    _move(rows[0], to_status=InstrumentStatus.UNPAID, happened_on=unpaid_on, actor=actor, note=note)
    _record(organization, actor, "treasury.unpaid", rows, day=unpaid_on.isoformat(), reason=note)
    return rows[0]


@transaction.atomic
def return_instruments(
    *, organization: Organization, actor: User | None, instrument_ids: Sequence[int], returned_on: dt.date | None
) -> list[Instrument]:
    """Unpaid effets given back to the customer ("Restitué"): the paper leaves the portfolio for good."""
    rows = _batch(
        organization,
        instrument_ids,
        direction=InstrumentDirection.RECEIVED,
        statuses=frozenset({InstrumentStatus.UNPAID}),
        happened_on=returned_on,
    )
    assert returned_on is not None
    for row in rows:
        _move(row, to_status=InstrumentStatus.RETURNED, happened_on=returned_on, actor=actor)
    _record(organization, actor, "treasury.returned", rows, day=returned_on.isoformat())
    return rows


def mark_rejected(
    *, organization: Organization, actor: User | None, instrument_id: int, rejected_on: dt.date | None, note: str
) -> Instrument:
    """Our bank refused to pay one of our cheques or traites: "Rejeté". Called by the règlement's app, which owes the
    supplier again in the same transaction (D-218)."""
    rows = _batch(
        organization,
        [instrument_id],
        direction=InstrumentDirection.ISSUED,
        statuses=frozenset({InstrumentStatus.ISSUED}),
        happened_on=rejected_on,
    )
    assert rejected_on is not None
    _move(rows[0], to_status=InstrumentStatus.REJECTED, happened_on=rejected_on, actor=actor, note=note)
    _record(organization, actor, "treasury.rejected", rows, day=rejected_on.isoformat(), reason=note)
    return rows[0]


# ---- Accounts and movements (P9-T05, D-219) ----

# The accounts every organization starts with: provisional names the office renames (D-219).
DEFAULT_ACCOUNTS = ((AccountKind.CASH, "Caisse", 10), (AccountKind.BANK, "Banque principale", 20))
RIB_DIGITS = 20
# The role of a movement that undoes another one.
VOID = "void"
EFFET_EVENT_SOURCE = "treasury.effet_event"
TRANSFER_SOURCE = "treasury.transfer"
COUNT_SOURCE = "treasury.cash_count"
# Accounts that hold notes and coins.
CASH_KINDS = frozenset({AccountKind.CASH, AccountKind.DRIVER})


def _person(user: User) -> str:
    return f"{user.first_name} {user.last_name}".strip() or str(user.username)


def ensure_default_accounts(*, organization: Organization) -> None:
    """Create the Caisse and the main bank account when the organization has no default of that kind. Safe to call
    again."""
    for kind, name, position in DEFAULT_ACCOUNTS:
        if not TreasuryAccount.objects.filter(organization=organization, kind=kind, is_default=True).exists():
            TreasuryAccount.objects.create(
                organization=organization,
                kind=kind,
                name=name,
                cash_type=CashType.PRINCIPAL if kind == AccountKind.CASH else "",
                is_default=True,
                position=position,
            )


def default_account(organization: Organization, kind: str) -> TreasuryAccount:
    """The account money of `kind` goes to when nobody chose one (the Caisse, the main bank account)."""
    account = TreasuryAccount.objects.filter(organization=organization, kind=kind, is_default=True).first()
    if account is None:
        ensure_default_accounts(organization=organization)
        account = TreasuryAccount.objects.get(organization=organization, kind=kind, is_default=True)
    return account


def driver_account(organization: Organization, driver: User) -> TreasuryAccount:
    """The cash a driver holds on the road, made the first time it is needed."""
    account, _created = TreasuryAccount.objects.get_or_create(
        organization=organization,
        driver=driver,
        defaults={
            "kind": AccountKind.DRIVER,
            "name": (_("Caisse de %(name)s") % {"name": _person(driver)})[:100],
            "position": 100,
        },
    )
    return account


def bank_account_for(organization: Organization, bank: Bank | None) -> TreasuryAccount:
    """Our active account at `bank` (the first in the list), else the main bank account."""
    if bank is not None:
        found = (
            TreasuryAccount.objects.filter(organization=organization, kind=AccountKind.BANK, bank=bank, is_active=True)
            .order_by("position", "id")
            .first()
        )
        if found is not None:
            return found
    return default_account(organization, AccountKind.BANK)


def line_account_error(organization: Organization, method: str, account: TreasuryAccount | None) -> str:
    """What is wrong with the account chosen for a payment line paid by `method`; empty when fine or none chosen.
    Cash goes to a Caisse (or a driver's cash); a transfer, a card, our cheque or traite to a bank account."""
    if account is None:
        return ""
    if account.organization_id != organization.pk:
        return _("Compte inconnu.")
    if not account.is_active:
        return _("Ce compte n'est plus utilisé.")
    if method == "cash" and account.kind not in CASH_KINDS:
        return _("Des espèces vont dans une caisse.")
    if method != "cash" and account.kind != AccountKind.BANK:
        return _("Choisissez un compte bancaire.")
    return ""


def line_account(
    organization: Organization, method: str, account: TreasuryAccount | None = None, *, driver: User | None = None
) -> TreasuryAccount:
    """The account a payment line moves: the one chosen, else the driver's cash for cash a driver took, the Caisse
    for other cash, the main bank account for the rest."""
    if account is not None:
        return account
    if method == "cash":
        if driver is not None:
            return driver_account(organization, driver)
        return default_account(organization, AccountKind.CASH)
    return default_account(organization, AccountKind.BANK)


def post_movement(
    *,
    organization: Organization,
    account: TreasuryAccount,
    day: dt.date,
    amount: Number,
    kind: str,
    label: str,
    reference: str = "",
    source: str = "",
    source_id: int | None = None,
    role: str = "",
    actor: User | None = None,
) -> TreasuryMovement | None:
    """Write one movement (+ in, − out); None for a zero amount. A record's movement already written (same source,
    id and role) comes back as it is: writing a record's movements again never counts them twice."""
    value = money(amount)
    if value == 0:
        return None
    if source:
        existing = TreasuryMovement.objects.filter(
            organization=organization, source=source, source_id=source_id, role=role
        ).first()
        if existing is not None:
            return existing
    return TreasuryMovement.objects.create(
        organization=organization,
        account=account,
        day=day,
        amount=value,
        kind=kind,
        label=label[:255],
        reference=reference[:50],
        source=source,
        source_id=source_id,
        role=role,
        created_by=actor,
    )


def reverse_movements(
    *,
    organization: Organization,
    source: str,
    source_ids: Sequence[int],
    day: dt.date,
    actor: User | None,
    label: str,
) -> list[TreasuryMovement]:
    """Undo the movements records wrote (their règlement was voided): the opposite amount on the same account on
    `day`. Safe to call again."""
    originals = (
        TreasuryMovement.objects.filter(organization=organization, source=source, source_id__in=list(source_ids))
        .exclude(role__startswith=VOID)
        .select_related("account")
        .order_by("id")
    )
    written = []
    for original in originals:
        row = post_movement(
            organization=organization,
            account=original.account,
            day=day,
            amount=-original.amount,
            kind=original.kind,
            label=f"{label} · {original.label}",
            reference=original.reference,
            source=source,
            source_id=original.source_id,
            role=f"{VOID}_{original.role}" if original.role else VOID,
            actor=actor,
        )
        if row is not None:
            written.append(row)
    return written


def posted_source_ids(organization: Organization, source: str) -> set[int]:
    """The records of `source` that already wrote their movement (the backfill skips them)."""
    rows = TreasuryMovement.objects.filter(organization=organization, source=source).exclude(role__startswith=VOID)
    return {pk for pk in rows.values_list("source_id", flat=True) if pk is not None}


def _post_effet_movement(instrument: Instrument, event: InstrumentEvent) -> None:
    """The money an effet's move puts in or takes from our accounts: credited by the bank, or cashed at its counter
    into the Caisse (+); taken back by the bank after it credited it (−); our own cheque or traite debited (−).
    Other moves do not touch an account."""
    organization = instrument.organization
    deposit = instrument.deposit
    reference = instrument.source_number
    if event.to_status == InstrumentStatus.CASHED and event.from_status == InstrumentStatus.PORTFOLIO:
        # Cashed at the drawer's bank counter: notes, into the Caisse.
        account = default_account(organization, AccountKind.CASH)
        amount, kind = instrument.amount, MovementKind.EFFET_CASHED
    elif event.to_status == InstrumentStatus.CASHED:
        account = (
            deposit.account
            if deposit is not None and deposit.account is not None
            else bank_account_for(organization, deposit.bank if deposit is not None else None)
        )
        amount, kind = instrument.amount, MovementKind.EFFET_CASHED
        reference = deposit.number if deposit is not None else reference
    elif event.to_status == InstrumentStatus.UNPAID and event.from_status == InstrumentStatus.CASHED:
        cashed = (
            TreasuryMovement.objects.filter(
                organization=organization,
                source=EFFET_EVENT_SOURCE,
                source_id__in=instrument.events.filter(to_status=InstrumentStatus.CASHED).values("pk"),
            )
            .select_related("account")
            .order_by("-id")
            .first()
        )
        account = cashed.account if cashed is not None else bank_account_for(organization, None)
        amount, kind = -instrument.amount, MovementKind.EFFET_UNPAID
    elif event.to_status == InstrumentStatus.DEBITED:
        account = instrument.account or bank_account_for(organization, instrument.bank)
        amount, kind = -instrument.amount, MovementKind.EFFET_DEBITED
    else:
        return
    party = instrument.customer or instrument.supplier
    post_movement(
        organization=organization,
        account=account,
        day=event.happened_on,
        amount=amount,
        kind=kind,
        label=" · ".join(
            part for part in (str(instrument), instrument.source_number, party.name if party else "") if part
        ),
        reference=reference,
        source=EFFET_EVENT_SOURCE,
        source_id=event.pk,
        actor=event.actor,
    )


def post_effet_history(*, organization: Organization) -> None:
    """Write the movements of the effets cashed, taken back or debited before the accounts existed. Safe to run
    again."""
    done = posted_source_ids(organization, EFFET_EVENT_SOURCE)
    events = (
        InstrumentEvent.objects.filter(
            organization=organization,
            to_status__in=(InstrumentStatus.CASHED, InstrumentStatus.UNPAID, InstrumentStatus.DEBITED),
        )
        .exclude(pk__in=done)
        .select_related(
            "instrument__organization",
            "instrument__deposit__account",
            "instrument__deposit__bank",
            "instrument__account",
            "instrument__bank",
            "instrument__customer",
            "instrument__supplier",
        )
        .order_by("id")
    )
    for event in events:
        _post_effet_movement(event.instrument, event)


def _signed_amount(value: Number | None, field: str, errors: dict[str, str]) -> Decimal:
    """An amount that may be below zero (an opening overdraft)."""
    text = str(value if value is not None else "0").strip() or "0"
    negative = text.startswith("-")
    try:
        result = checked_amount(text.removeprefix("-"))
    except (ValueError, TypeError):
        errors[field] = _("Indiquez un montant en DT, au millime près.")
        return Decimal("0.000")
    return -result if negative else result


def _checked_account(
    organization: Organization,
    *,
    kind: str,
    name: str,
    bank: Bank | None,
    rib: str,
    iban: str = "",
    cash_type: str = "",
    opening_balance: Number | None,
    opening_on: dt.date | None,
    account: TreasuryAccount | None = None,
) -> dict[str, Any]:
    errors: dict[str, str] = {}
    name = " ".join(name.split())
    if not name:
        errors["name"] = _("Indiquez le nom du compte.")
    elif len(name) > 100:
        errors["name"] = _("100 caractères au plus.")
    else:
        same = TreasuryAccount.objects.filter(organization=organization, name__iexact=name)
        if account is not None:
            same = same.exclude(pk=account.pk)
        if same.exists():
            errors["name"] = _("Un compte porte déjà ce nom.")
    rib = "".join(rib.split())
    iban = "".join(iban.split()).upper()
    if kind == AccountKind.BANK:
        if bank is not None and (bank.organization_id != organization.pk or not bank.is_active):
            errors["bank"] = _("Banque inconnue.")
        if rib and (not rib.isdigit() or len(rib) != RIB_DIGITS):
            errors["rib"] = _("Le RIB compte %(count)s chiffres.") % {"count": RIB_DIGITS}
        elif rib and _taken(TreasuryAccount.objects.filter(organization=organization, rib=rib), account):
            errors["rib"] = _("Ce RIB appartient déjà à un autre compte.")
        if iban and not IBAN_RE.fullmatch(iban):
            errors["iban"] = _(
                "L'IBAN compte deux lettres, deux chiffres, quatre caractères, quatre et trois chiffres."
            )
        elif iban and _taken(TreasuryAccount.objects.filter(organization=organization, iban=iban), account):
            errors["iban"] = _("Cet IBAN appartient déjà à un autre compte.")
    else:
        bank, rib, iban = None, "", ""
    if kind == AccountKind.CASH:
        cash_type = cash_type or CashType.PRINCIPAL
        if cash_type not in CashType.values:
            errors["cash_type"] = _("Choisissez une caisse principale ou secondaire.")
    else:
        cash_type = ""
    balance = _signed_amount(opening_balance, "opening_balance", errors)
    if opening_on is not None and opening_on > timezone.localdate():
        errors["opening_on"] = _("Le jour d'ouverture ne peut pas être dans le futur.")
    if errors:
        raise ValidationError(errors)
    return {
        "name": name,
        "bank": bank,
        "rib": rib,
        "iban": iban,
        "cash_type": cash_type,
        "opening_balance": balance,
        "opening_on": opening_on,
    }


def _taken(others: QuerySet[TreasuryAccount], account: TreasuryAccount | None) -> bool:
    """True when another account (not `account` itself) already holds the RIB or IBAN."""
    if account is not None:
        others = others.exclude(pk=account.pk)
    return others.exists()


def _account_snapshot(account: TreasuryAccount) -> dict[str, Any]:
    return {
        "kind": account.kind,
        "name": account.name,
        "bank": account.bank.code if account.bank is not None else "",
        "rib": account.rib,
        "iban": account.iban,
        "cash_type": account.cash_type,
        "opening_balance": str(account.opening_balance),
        "opening_on": account.opening_on.isoformat() if account.opening_on else "",
        "is_default": account.is_default,
        "is_active": account.is_active,
    }


@transaction.atomic
def create_account(
    *,
    organization: Organization,
    actor: User | None,
    kind: str,
    name: str,
    bank: Bank | None = None,
    rib: str = "",
    iban: str = "",
    cash_type: str = "",
    opening_balance: Number | None = None,
    opening_on: dt.date | None = None,
) -> TreasuryAccount:
    """Add a Caisse or a bank account, with what it held on its opening day. A driver's cash is made by itself."""
    if kind not in (AccountKind.CASH, AccountKind.BANK):
        raise ValidationError({"kind": _("Choisissez une caisse ou un compte bancaire.")})
    fields = _checked_account(
        organization,
        kind=kind,
        name=name,
        bank=bank,
        rib=rib,
        iban=iban,
        cash_type=cash_type,
        opening_balance=opening_balance,
        opening_on=opening_on,
    )
    last = TreasuryAccount.objects.filter(organization=organization).aggregate(top=Max("position"))["top"] or 0
    account = TreasuryAccount.objects.create(organization=organization, kind=kind, position=last + 10, **fields)
    audit.record(
        organization=organization,
        actor=actor,
        action="treasury.account_created",
        target=account,
        after=_account_snapshot(account),
    )
    return account


@transaction.atomic
def update_account(
    *,
    account: TreasuryAccount,
    actor: User | None,
    name: str,
    bank: Bank | None,
    rib: str,
    iban: str = "",
    cash_type: str = "",
    opening_balance: Number | None,
    opening_on: dt.date | None,
    is_active: bool,
    is_default: bool,
) -> TreasuryAccount:
    """Rename an account, give its bank and RIB, its opening, take it off the lists, or make it the default of its
    kind. Its movements never change."""
    account = (
        TreasuryAccount.objects.select_for_update(of=("self",))
        .select_related("organization", "bank")
        .get(pk=account.pk)
    )
    before = _account_snapshot(account)
    fields = _checked_account(
        account.organization,
        kind=account.kind,
        name=name,
        bank=bank,
        rib=rib,
        iban=iban,
        cash_type=cash_type,
        opening_balance=opening_balance,
        opening_on=opening_on,
        account=account,
    )
    if account.kind == AccountKind.DRIVER:
        is_default = False
    if account.is_default and not is_default:
        raise ValidationError(
            {"is_default": _("Choisissez d'abord un autre compte par défaut : il en faut un par sorte.")}
        )
    if (is_default or account.is_default) and not is_active:
        raise ValidationError({"is_active": _("Le compte par défaut reste actif.")})
    if is_default and not account.is_default:
        TreasuryAccount.objects.filter(organization=account.organization, kind=account.kind, is_default=True).update(
            is_default=False
        )
    for field, value in fields.items():
        setattr(account, field, value)
    account.is_active = is_active
    account.is_default = is_default
    account.save()
    audit.record(
        organization=account.organization,
        actor=actor,
        action="treasury.account_updated",
        target=account,
        before=before,
        after=_account_snapshot(account),
    )
    return account


def _transfer_kind(source: TreasuryAccount, target: TreasuryAccount) -> str:
    if source.kind in CASH_KINDS and target.kind == AccountKind.BANK:
        return TransferKind.CASH_DEPOSIT
    if source.kind == AccountKind.BANK and target.kind in CASH_KINDS:
        return TransferKind.WITHDRAWAL
    return TransferKind.TRANSFER


def _account_error(organization: Organization, account: TreasuryAccount | None) -> str:
    if account is None:
        return _("Choisissez le compte.")
    if account.organization_id != organization.pk:
        return _("Compte inconnu.")
    if not account.is_active:
        return _("Ce compte n'est plus utilisé.")
    return ""


@transaction.atomic
def transfer_between(
    *,
    organization: Organization,
    actor: User | None,
    from_account: TreasuryAccount | None,
    to_account: TreasuryAccount | None,
    amount: Number | None,
    transferred_on: dt.date | None,
    reference: str = "",
    notes: str = "",
) -> AccountTransfer:
    """Move money from one of our accounts to another on a day: a versement (cash to the bank), a retrait (bank to
    cash) or a virement. "MT-2026-0001", one movement out and one in. Every problem comes back at once."""
    errors: dict[str, str] = {}
    for field, account in (("from_account", from_account), ("to_account", to_account)):
        message = _account_error(organization, account)
        if message:
            errors[field] = message
    if from_account is not None and to_account is not None and from_account.pk == to_account.pk:
        errors["to_account"] = _("Choisissez deux comptes différents.")
    try:
        value = checked_amount(amount if amount is not None else "")
        if value <= 0:
            errors["amount"] = _("Le montant doit être supérieur à zéro.")
    except (ValueError, TypeError):
        value = Decimal("0.000")
        errors["amount"] = _("Indiquez un montant en DT, au millime près.")
    if transferred_on is None:
        errors["transferred_on"] = _("Indiquez le jour.")
    elif transferred_on > timezone.localdate():
        errors["transferred_on"] = _("Le jour ne peut pas être dans le futur.")
    if errors:
        raise ValidationError(errors)
    assert from_account is not None
    assert to_account is not None
    assert transferred_on is not None
    kind = _transfer_kind(from_account, to_account)
    transfer = AccountTransfer.objects.create(
        organization=organization,
        number=numbering.next_number(organization, "account_transfer", year=transferred_on.year),
        kind=kind,
        from_account=from_account,
        to_account=to_account,
        amount=value,
        transferred_on=transferred_on,
        reference=reference.strip()[:50],
        notes=notes.strip()[:255],
        created_by=actor,
    )
    title = TransferKind(kind).label
    for account, signed, role, label in (
        (from_account, -value, "out", _("%(kind)s vers %(account)s") % {"kind": title, "account": to_account}),
        (to_account, value, "in", _("%(kind)s depuis %(account)s") % {"kind": title, "account": from_account}),
    ):
        post_movement(
            organization=organization,
            account=account,
            day=transferred_on,
            amount=signed,
            kind=MovementKind.TRANSFER,
            label=f"{transfer.number} · {label}",
            reference=transfer.reference or transfer.number,
            source=TRANSFER_SOURCE,
            source_id=transfer.pk,
            role=role,
            actor=actor,
        )
    audit.record(
        organization=organization,
        actor=actor,
        action="treasury.transferred",
        target=transfer,
        after={
            "kind": kind,
            "from": str(from_account),
            "to": str(to_account),
            "amount": str(value),
            "day": transferred_on.isoformat(),
        },
    )
    return transfer


@transaction.atomic
def void_transfer(*, transfer: AccountTransfer, actor: User | None, reason: str) -> AccountTransfer:
    """Cancel a transfer typed by mistake: it stays, marked annulé (who, when, why), and its two movements are undone
    by two opposite ones today."""
    transfer = AccountTransfer.objects.select_for_update().select_related("organization").get(pk=transfer.pk)
    if transfer.voided_at is not None:
        raise ValidationError(_("Ce mouvement est déjà annulé."))
    reason = reason.strip()[:255]
    if not reason:
        raise ValidationError({"reason": _("Indiquez la raison de l'annulation.")})
    reverse_movements(
        organization=transfer.organization,
        source=TRANSFER_SOURCE,
        source_ids=[transfer.pk],
        day=timezone.localdate(),
        actor=actor,
        label=_("Annulation"),
    )
    transfer.voided_at = timezone.now()
    transfer.voided_by = actor
    transfer.void_reason = reason
    transfer.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
    audit.record(
        organization=transfer.organization,
        actor=actor,
        action="treasury.transfer_voided",
        target=transfer,
        after={"reason": reason},
    )
    return transfer


@transaction.atomic
def count_cash(
    *,
    organization: Organization,
    actor: User | None,
    account: TreasuryAccount | None,
    counted_on: dt.date | None,
    counted: Number | None,
    reason: str = "",
) -> CashCount:
    """The arrêté de caisse: the cash counted at the end of `counted_on` against what the movements say. A gap is
    written as an "Écart de caisse" movement that day, with its reason (needed), so the balance is what was
    counted."""
    from . import selectors

    errors: dict[str, str] = {}
    message = _account_error(organization, account)
    if message:
        errors["account"] = message
    elif account is not None and account.kind not in CASH_KINDS:
        errors["account"] = _("Un arrêté se fait sur une caisse.")
    if counted_on is None:
        errors["counted_on"] = _("Indiquez le jour.")
    elif counted_on > timezone.localdate():
        errors["counted_on"] = _("Le jour ne peut pas être dans le futur.")
    elif account is not None and account.opening_on is not None and counted_on < account.opening_on:
        errors["counted_on"] = _("Ce jour précède l'ouverture du compte.")
    try:
        value = checked_amount(counted if counted is not None else "")
    except (ValueError, TypeError):
        value = Decimal("0.000")
        errors["counted"] = _("Indiquez un montant en DT, au millime près.")
    if errors:
        raise ValidationError(errors)
    assert account is not None
    assert counted_on is not None
    # One count at a time per account: the expected cash is read under the lock.
    account = TreasuryAccount.objects.select_for_update().get(pk=account.pk)
    expected = selectors.account_balance(account, on=counted_on)
    gap = value - expected
    reason = reason.strip()[:255]
    if gap != 0 and not reason:
        raise ValidationError({"reason": _("Expliquez l'écart de %(gap)s DT.") % {"gap": gap}})
    count = CashCount.objects.create(
        organization=organization,
        account=account,
        counted_on=counted_on,
        expected=expected,
        counted=value,
        gap=gap,
        reason=reason,
        created_by=actor,
    )
    post_movement(
        organization=organization,
        account=account,
        day=counted_on,
        amount=gap,
        kind=MovementKind.COUNT_GAP,
        label=_("Arrêté de caisse du %(day)s : %(reason)s")
        % {"day": counted_on.strftime("%d/%m/%Y"), "reason": reason},
        source=COUNT_SOURCE,
        source_id=count.pk,
        actor=actor,
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="treasury.cash_counted",
        target=count,
        after={
            "account": str(account),
            "day": counted_on.isoformat(),
            "expected": str(expected),
            "counted": str(value),
            "gap": str(gap),
            "reason": reason,
        },
    )
    return count
