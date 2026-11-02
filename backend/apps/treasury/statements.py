"""The lines of a bank's statement (P9-T09d, D-252): the import of the bank's Excel file, the third party of a line,
deleting a line. A copy of what the bank says: nothing here moves money or changes an account's balance."""

import datetime as dt
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import Organization, User

from .models import AccountKind, BankStatementLine, TreasuryAccount
from .statement_file import RowError, StatementFileError, read_statement

if TYPE_CHECKING:
    from apps.partners.models import Customer, Supplier


@dataclass(frozen=True)
class ImportReport:
    created: int
    # Lines already imported (the same day, label and amounts on this account).
    skipped: int
    # Rows that could not be read: when there is one, nothing is saved.
    errors: list[RowError]


@transaction.atomic
def import_statement(
    *, organization: Organization, actor: User | None, account: TreasuryAccount, content: bytes
) -> ImportReport:
    """Add the lines of the bank's file to a bank account. All or nothing: one unreadable row and nothing is saved.
    A line already on the account (same day, label, debit, credit and balance) is skipped, so sending the same file
    twice adds nothing; two identical lines inside one new file are both kept."""
    account = TreasuryAccount.objects.select_for_update(of=("self",)).get(pk=account.pk)
    if account.organization_id != organization.pk or account.kind != AccountKind.BANK:
        raise ValidationError({"account": _("Un relevé s'importe sur un compte bancaire.")})
    try:
        rows, errors = read_statement(content)
    except StatementFileError as error:
        raise ValidationError({"file": str(error)}) from error
    if errors:
        return ImportReport(created=0, skipped=0, errors=errors)

    known: Counter[tuple[dt.date, str, Decimal, Decimal, Decimal | None]] = Counter(
        (line.day, line.label, line.debit, line.credit, line.balance)
        for line in BankStatementLine.objects.filter(account=account)
    )
    new: list[BankStatementLine] = []
    skipped = 0
    for row in rows:
        key = (row.day, row.label, row.debit, row.credit, row.balance)
        if known[key] > 0:
            known[key] -= 1
            skipped += 1
            continue
        new.append(
            BankStatementLine(
                organization=organization,
                account=account,
                day=row.day,
                label=row.label,
                debit=row.debit,
                credit=row.credit,
                balance=row.balance,
                imported_by=actor,
            )
        )
    BankStatementLine.objects.bulk_create(new)
    audit.record(
        organization=organization,
        actor=actor,
        action="treasury.statement_imported",
        target=account,
        after={"created": len(new), "skipped": skipped},
    )
    return ImportReport(created=len(new), skipped=skipped, errors=[])


@transaction.atomic
def set_line_party(
    *, line: BankStatementLine, actor: User | None, customer: "Customer | None", supplier: "Supplier | None"
) -> BankStatementLine:
    """Say whose line it is: a customer for a debit, a supplier for a credit (neither clears it)."""
    line = BankStatementLine.objects.select_for_update(of=("self",)).select_related("organization").get(pk=line.pk)
    if customer is not None and supplier is not None:
        raise ValidationError(_("Une ligne est celle d'un client ou d'un fournisseur, pas des deux."))
    if customer is not None and line.debit <= 0:
        raise ValidationError({"customer": _("Un client se choisit sur une ligne au débit.")})
    if supplier is not None and line.credit <= 0:
        raise ValidationError({"supplier": _("Un fournisseur se choisit sur une ligne au crédit.")})
    for party in (customer, supplier):
        if party is not None and party.organization_id != line.organization_id:
            raise ValidationError(_("Tiers inconnu."))
    before = {"customer": line.customer_id, "supplier": line.supplier_id}
    line.customer, line.supplier = customer, supplier
    line.save(update_fields=["customer", "supplier", "updated_at"])
    audit.record(
        organization=line.organization,
        actor=actor,
        action="treasury.statement_line_party",
        target=line,
        before=before,
        after={"customer": line.customer_id, "supplier": line.supplier_id},
    )
    return line


@transaction.atomic
def delete_line(*, line: BankStatementLine, actor: User | None) -> None:
    """Take a line off the statement (a wrong import). It was only a copy of the bank's file."""
    line = BankStatementLine.objects.select_related("organization", "account").get(pk=line.pk)
    snapshot = {"account": line.account.name, "day": line.day.isoformat(), "label": line.label}
    organization = line.organization
    line.delete()
    audit.record(
        organization=organization,
        actor=actor,
        action="treasury.statement_line_deleted",
        target=None,
        before=snapshot,
    )
