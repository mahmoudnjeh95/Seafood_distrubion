"""Treasury: the banks list and the effets (D-197, P9-T01); our accounts, their movements, transfers and
arrêtés de caisse (D-219, P9-T05).

Office data: the owner and the manager write, the accountant reads, drivers get 403.
"""

from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import QuerySet
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.pagination import PagedList
from apps.core.models import Membership, Organization
from apps.core.permissions import ReadOfficeWriteOwnerOrManager, membership_of
from apps.core.xlsx import XLSX_TYPE, workbook_bytes, xlsx_response
from apps.partners import selectors as partners
from apps.purchasing import selectors as purchasing
from apps.sales import selectors as sales

from .. import selectors, services, statements
from ..models import AccountTransfer, Bank, BankStatementLine, CashCount, Deposit, Instrument, TreasuryAccount
from .serializers import (
    AccountFilterSerializer,
    AccountStatementSerializer,
    AccountTransferSerializer,
    AccountTransferWriteSerializer,
    BankFilterSerializer,
    BankSerializer,
    BankStatementLineSerializer,
    BankWriteSerializer,
    CashCountSerializer,
    CashCountWriteSerializer,
    DepositSerializer,
    DepositWriteSerializer,
    InstrumentBatchSerializer,
    InstrumentFilterSerializer,
    InstrumentSerializer,
    InstrumentTotalsSerializer,
    MovementOfFilterSerializer,
    MovementOfSerializer,
    PartyDocumentsSerializer,
    StatementFilterSerializer,
    StatementImportReportSerializer,
    StatementImportSerializer,
    StatementLineFilterSerializer,
    StatementLinePartySerializer,
    TransferFilterSerializer,
    TreasuryAccountSerializer,
    TreasuryAccountWriteSerializer,
    VoidTransferSerializer,
)


class OfficeView(APIView):
    permission_classes = (ReadOfficeWriteOwnerOrManager,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    @property
    def organization(self) -> Organization:
        return self.membership.organization


class BankListView(OfficeView):
    @extend_schema(operation_id="listBanks", parameters=[BankFilterSerializer], responses=BankSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The banks an effet may be drawn on, in the list's order; `active_only=false` adds those taken off."""
        filters = BankFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        banks = selectors.banks_of(self.organization, active_only=filters.validated_data["active_only"])
        return Response(BankSerializer(banks, many=True).data)

    @extend_schema(operation_id="createBank", request=BankWriteSerializer, responses={201: BankSerializer})
    def post(self, request: Request) -> Response:
        """Add a bank to the list (owner or manager): its short name (sigle) and its name."""
        serializer = BankWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bank = services.create_bank(
            organization=self.organization,
            actor=self.membership.user,
            code=serializer.validated_data["code"],
            name=serializer.validated_data["name"],
            swift=serializer.validated_data["swift"],
            address=serializer.validated_data["address"],
        )
        return Response(BankSerializer(bank).data, status=status.HTTP_201_CREATED)


class PartyDocumentsView(OfficeView):
    @extend_schema(operation_id="listPartyDocuments", responses=PartyDocumentsSerializer)
    def get(self, request: Request) -> Response:
        """What each customer and supplier has on paper, for the lists of the règlement forms (D-211): a customer's
        confirmed BL and issued invoices with their net to pay, a supplier's goods receipts (BR) and invoices (not
        drafts) with their total. A party with no such document is not listed."""
        answer = {
            "customers": list(sales.customer_documents(self.organization).values()),
            "suppliers": list(purchasing.supplier_documents(self.organization).values()),
        }
        return Response(PartyDocumentsSerializer(answer).data)


class BankDetailView(OfficeView):
    @extend_schema(operation_id="updateBank", request=BankWriteSerializer, responses=BankSerializer)
    def put(self, request: Request, bank_id: int) -> Response:
        """Rename a bank, or take it off the lists (`is_active` false); effets already drawn on it keep it."""
        try:
            bank = selectors.bank_of(self.organization, bank_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        serializer = BankWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bank = services.update_bank(
            bank=bank,
            actor=self.membership.user,
            code=serializer.validated_data["code"],
            name=serializer.validated_data["name"],
            is_active=serializer.validated_data["is_active"],
            swift=serializer.validated_data["swift"],
            address=serializer.validated_data["address"],
        )
        return Response(BankSerializer(bank).data)


def _filtered_instruments(organization: Organization, request: Request) -> QuerySet[Instrument]:
    filters = InstrumentFilterSerializer(data=request.query_params)
    filters.is_valid(raise_exception=True)
    data: dict[str, Any] = filters.validated_data
    return selectors.instruments_of(
        organization,
        direction=data.get("direction"),
        kind=data.get("kind"),
        statuses=data["status"],
        customer_id=data.get("customer"),
        supplier_id=data.get("supplier"),
        due_from=data.get("due_from"),
        due_to=data.get("due_to"),
        search=data["search"],
        bank_id=data.get("bank"),
        deposit_id=data.get("deposit"),
    )


class InstrumentTotalsView(OfficeView):
    @extend_schema(
        operation_id="getInstrumentTotals",
        parameters=[InstrumentFilterSerializer],
        responses=InstrumentTotalsSerializer,
    )
    def get(self, request: Request) -> Response:
        """The count and amount of the effets of the same filters as the list, by status, and those late (échéance
        passed while still in portfolio, at the bank or issued)."""
        totals = selectors.instrument_totals(
            _filtered_instruments(self.organization, request), today=timezone.localdate()
        )
        return Response(InstrumentTotalsSerializer(totals).data)


class InstrumentBatchView(OfficeView):
    """One step for several effets at once, on one day (owner or manager)."""

    step = ""

    def post(self, request: Request) -> Response:
        serializer = InstrumentBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        organization, actor, ids = self.organization, self.membership.user, data["instruments"]
        if self.step == "cash":
            rows = services.cash_instruments(
                organization=organization, actor=actor, instrument_ids=ids, cashed_on=data["day"]
            )
        elif self.step == "return":
            rows = services.return_instruments(
                organization=organization, actor=actor, instrument_ids=ids, returned_on=data["day"]
            )
        elif self.step == "debit":
            rows = services.debit_instruments(
                organization=organization, actor=actor, instrument_ids=ids, debited_on=data["day"]
            )
        else:
            rows = services.withdraw_instruments(
                organization=organization, actor=actor, instrument_ids=ids, withdrawn_on=data["day"], note=data["note"]
            )
        fresh = selectors.instruments_of(self.organization).filter(pk__in=[row.pk for row in rows])
        return Response(InstrumentSerializer(fresh, many=True).data)


class InstrumentCashView(InstrumentBatchView):
    step = "cash"

    @extend_schema(
        operation_id="cashInstruments", request=InstrumentBatchSerializer, responses=InstrumentSerializer(many=True)
    )
    def post(self, request: Request) -> Response:
        """Received effets the bank credited on `day`: at the bank, or cashed at its counter from the portfolio."""
        return super().post(request)


class InstrumentWithdrawView(InstrumentBatchView):
    step = "withdraw"

    @extend_schema(
        operation_id="withdrawInstruments", request=InstrumentBatchSerializer, responses=InstrumentSerializer(many=True)
    )
    def post(self, request: Request) -> Response:
        """Effets taken back from the bank before it cashed them: in portfolio again."""
        return super().post(request)


class InstrumentReturnView(InstrumentBatchView):
    step = "return"

    @extend_schema(
        operation_id="returnInstruments", request=InstrumentBatchSerializer, responses=InstrumentSerializer(many=True)
    )
    def post(self, request: Request) -> Response:
        """Unpaid effets given back to the customer on `day` ("Restitué")."""
        return super().post(request)


class InstrumentDebitView(InstrumentBatchView):
    step = "debit"

    @extend_schema(
        operation_id="debitInstruments", request=InstrumentBatchSerializer, responses=InstrumentSerializer(many=True)
    )
    def post(self, request: Request) -> Response:
        """Our cheques and traites the bank paid on `day`."""
        return super().post(request)


class DepositListView(OfficeView, ListAPIView[Deposit]):
    serializer_class = DepositSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[Deposit]:
        return selectors.deposits_of(self.organization)

    @extend_schema(operation_id="listDeposits")
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Bordereaux de remise en banque, newest first, paginated, each with its effets."""
        return super().get(request, *args, **kwargs)

    @extend_schema(operation_id="createDeposit", request=DepositWriteSerializer, responses={201: DepositSerializer})
    def post(self, request: Request) -> Response:
        """Hand received effets in portfolio to one of our bank accounts (owner or manager): a bordereau RB-...
        holding them; each one becomes "Remis en banque", and the account is credited when they are cashed. Its PDF
        is the document kind `bank_deposit`."""
        serializer = DepositWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        bank = None
        if data["bank"] is not None:
            try:
                bank = selectors.bank_of(self.organization, data["bank"])
            except ObjectDoesNotExist:
                raise ValidationError({"bank": _("Banque inconnue.")}) from None
        deposit = services.deposit_instruments(
            organization=self.organization,
            actor=self.membership.user,
            instrument_ids=data["instruments"],
            bank=bank,
            deposited_on=data["deposited_on"],
            notes=data["notes"],
            account=_account_or_none(self.organization, data["account"], "account"),
        )
        return Response(
            DepositSerializer(selectors.deposit_of(self.organization, deposit.pk)).data, status=status.HTTP_201_CREATED
        )


class DepositDetailView(OfficeView):
    @extend_schema(operation_id="getDeposit", responses=DepositSerializer)
    def get(self, request: Request, deposit_id: int) -> Response:
        """One bordereau with its effets."""
        try:
            deposit = selectors.deposit_of(self.organization, deposit_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        return Response(DepositSerializer(deposit).data)


class InstrumentListView(OfficeView, ListAPIView[Instrument]):
    serializer_class = InstrumentSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[Instrument]:
        return _filtered_instruments(self.organization, self.request)

    @extend_schema(operation_id="listInstruments", parameters=[InstrumentFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Cheques and traites, received and issued, soonest due first, paginated. Filter by direction, kind,
        status (comma separated), customer, supplier, bank, bordereau, due days (inclusive) or `search` (number,
        drawer, règlement, party)."""
        return super().get(request, *args, **kwargs)


def _account_or_none(organization: Organization, account_id: int | None, field: str) -> TreasuryAccount | None:
    """The account of the organization named on `field`; an unknown one is an error on that field."""
    if account_id is None:
        return None
    try:
        return selectors.account_of(organization, account_id)
    except ObjectDoesNotExist:
        raise ValidationError({field: _("Compte inconnu.")}) from None


def _account(organization: Organization, account_id: int) -> TreasuryAccount:
    try:
        return selectors.account_of(organization, account_id)
    except ObjectDoesNotExist:
        raise Http404 from None


def _bank_or_none(organization: Organization, bank_id: int | None) -> Bank | None:
    if bank_id is None:
        return None
    try:
        return selectors.bank_of(organization, bank_id)
    except ObjectDoesNotExist:
        raise ValidationError({"bank": _("Banque inconnue.")}) from None


class AccountListView(OfficeView):
    @extend_schema(
        operation_id="listTreasuryAccounts",
        parameters=[AccountFilterSerializer],
        responses=TreasuryAccountSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Our accounts (Caisses, bank accounts, drivers' cash), each with its balance at the end of today or `on`;
        `active_only` leaves out those taken off the lists."""
        filters = AccountFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        accounts = selectors.accounts_of(
            self.organization, active_only=filters.validated_data["active_only"], on=filters.validated_data.get("on")
        )
        return Response(TreasuryAccountSerializer(accounts, many=True).data)

    @extend_schema(
        operation_id="createTreasuryAccount",
        request=TreasuryAccountWriteSerializer,
        responses={201: TreasuryAccountSerializer},
    )
    def post(self, request: Request) -> Response:
        """Add a Caisse or a bank account (owner or manager), with its bank, RIB and what it held on its opening
        day."""
        serializer = TreasuryAccountWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        account = services.create_account(
            organization=self.organization,
            actor=self.membership.user,
            kind=data["kind"],
            name=data["name"],
            bank=_bank_or_none(self.organization, data["bank"]),
            rib=data["rib"],
            iban=data["iban"],
            cash_type=data["cash_type"],
            opening_balance=data["opening_balance"],
            opening_on=data["opening_on"],
        )
        return Response(
            TreasuryAccountSerializer(selectors.account_of(self.organization, account.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class AccountDetailView(OfficeView):
    @extend_schema(operation_id="getTreasuryAccount", responses=TreasuryAccountSerializer)
    def get(self, request: Request, account_id: int) -> Response:
        """One account with its balance today."""
        return Response(TreasuryAccountSerializer(_account(self.organization, account_id)).data)

    @extend_schema(
        operation_id="updateTreasuryAccount",
        request=TreasuryAccountWriteSerializer,
        responses=TreasuryAccountSerializer,
    )
    def put(self, request: Request, account_id: int) -> Response:
        """Rename an account, give its bank, RIB and opening, take it off the lists or make it the default of its
        kind (owner or manager). Its kind and its movements never change."""
        account = _account(self.organization, account_id)
        serializer = TreasuryAccountWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.update_account(
            account=account,
            actor=self.membership.user,
            name=data["name"],
            bank=_bank_or_none(self.organization, data["bank"]),
            rib=data["rib"],
            iban=data["iban"],
            cash_type=data["cash_type"],
            opening_balance=data["opening_balance"],
            opening_on=data["opening_on"],
            is_active=data["is_active"],
            is_default=data["is_default"],
        )
        return Response(TreasuryAccountSerializer(selectors.account_of(self.organization, account.pk)).data)


def _statement(organization: Organization, account_id: int, request: Request) -> selectors.AccountStatement:
    account = _account(organization, account_id)
    filters = StatementFilterSerializer(data=request.query_params)
    filters.is_valid(raise_exception=True)
    data: dict[str, Any] = filters.validated_data
    return selectors.account_statement(
        account,
        date_from=data.get("date_from"),
        date_to=data.get("date_to"),
        kind=data.get("kind"),
        search=data["search"],
    )


class AccountMovementsView(OfficeView):
    @extend_schema(
        operation_id="getAccountStatement", parameters=[StatementFilterSerializer], responses=AccountStatementSerializer
    )
    def get(self, request: Request, account_id: int) -> Response:
        """The account's movements between two days (inclusive), oldest first, each with the balance after it; the
        balance at the start and the end, the money in and out. `kind` and `search` narrow the rows shown."""
        return Response(AccountStatementSerializer(_statement(self.organization, account_id, request)).data)


class AccountMovementsExportView(OfficeView):
    @extend_schema(
        operation_id="exportAccountStatement",
        parameters=[StatementFilterSerializer],
        responses={(200, XLSX_TYPE): OpenApiTypes.BINARY},
    )
    def get(self, request: Request, account_id: int) -> HttpResponse:
        """The same movements as an Excel file: the opening balance, one row each with the balance after it, the
        totals."""
        statement = _statement(self.organization, account_id, request)
        rows: list[list[Any]] = [["", _("Solde au début"), "", "", "", "", statement.opening]]
        for row in statement.rows:
            movement = row.movement
            rows.append(
                [
                    movement.day,
                    movement.label,
                    movement.get_kind_display(),
                    movement.reference,
                    movement.amount if movement.amount > 0 else None,
                    -movement.amount if movement.amount < 0 else None,
                    row.balance,
                ]
            )
        content = workbook_bytes(
            title=str(statement.account),
            headers=[_("Date"), _("Libellé"), _("Nature"), _("Référence"), _("Entrée"), _("Sortie"), _("Solde")],
            rows=rows,
            totals=["", _("Total"), "", "", statement.total_in, statement.total_out, statement.closing],
        )
        return xlsx_response(f"compte-{statement.account.pk}", content)


class TransferListView(OfficeView, ListAPIView[AccountTransfer]):
    serializer_class = AccountTransferSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[AccountTransfer]:
        filters = TransferFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.transfers_of(self.organization, account_id=filters.validated_data.get("account"))

    @extend_schema(operation_id="listAccountTransfers", parameters=[TransferFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Versements, retraits and virements between our accounts, newest first, paginated; `account` keeps those
        of one account."""
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="createAccountTransfer",
        request=AccountTransferWriteSerializer,
        responses={201: AccountTransferSerializer},
    )
    def post(self, request: Request) -> Response:
        """Move money between two of our accounts on a day (owner or manager): a versement (cash to the bank), a
        retrait (bank to cash) or a virement. One movement out, one in."""
        serializer = AccountTransferWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        transfer = services.transfer_between(
            organization=self.organization,
            actor=self.membership.user,
            from_account=_account_or_none(self.organization, data["from_account"], "from_account"),
            to_account=_account_or_none(self.organization, data["to_account"], "to_account"),
            amount=data["amount"],
            transferred_on=data["transferred_on"],
            reference=data["reference"],
            notes=data["notes"],
        )
        return Response(
            AccountTransferSerializer(selectors.transfer_of(self.organization, transfer.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class TransferVoidView(OfficeView):
    @extend_schema(
        operation_id="voidAccountTransfer", request=VoidTransferSerializer, responses=AccountTransferSerializer
    )
    def post(self, request: Request, transfer_id: int) -> Response:
        """Cancel a transfer typed by mistake (owner or manager, with a reason): two opposite movements today."""
        try:
            transfer = selectors.transfer_of(self.organization, transfer_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        serializer = VoidTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.void_transfer(
            transfer=transfer, actor=self.membership.user, reason=serializer.validated_data["reason"]
        )
        return Response(AccountTransferSerializer(selectors.transfer_of(self.organization, transfer.pk)).data)


class CashCountListView(OfficeView, ListAPIView[CashCount]):
    serializer_class = CashCountSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[CashCount]:
        filters = TransferFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.counts_of(self.organization, account_id=filters.validated_data.get("account"))

    @extend_schema(operation_id="listCashCounts", parameters=[TransferFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Arrêtés de caisse, newest first, paginated; `account` keeps those of one Caisse."""
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="createCashCount", request=CashCountWriteSerializer, responses={201: CashCountSerializer}
    )
    def post(self, request: Request) -> Response:
        """Arrêté de caisse (owner or manager): the cash counted at the end of a day. A gap from what the movements
        say needs its reason and is written as an "Écart de caisse" movement."""
        serializer = CashCountWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        count = services.count_cash(
            organization=self.organization,
            actor=self.membership.user,
            account=_account_or_none(self.organization, data["account"], "account"),
            counted_on=data["counted_on"],
            counted=data["counted"],
            reason=data["reason"],
        )
        return Response(CashCountSerializer(count).data, status=status.HTTP_201_CREATED)


class MovementsOfView(OfficeView):
    @extend_schema(
        operation_id="listMovementsOf",
        parameters=[MovementOfFilterSerializer],
        responses=MovementOfSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """The treasury movements written by the given records of one source, each with the account it went through
        (a règlement's lines, a sale, an expense, a partner's payout). Empty for a record with no money."""
        filters = MovementOfFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        raw = filters.validated_data["source_ids"].split(",")
        try:
            ids = [int(value) for value in raw if value.strip()]
        except ValueError:
            raise ValidationError({"source_ids": _("Des numéros de pièce sont attendus.")}) from None
        if len(ids) > 200:
            raise ValidationError({"source_ids": _("200 pièces au plus.")})
        movements = selectors.movements_of(
            self.organization, source=filters.validated_data["from_source"], source_ids=ids
        )
        return Response(MovementOfSerializer(movements, many=True).data)


# The bank's statement file is read in memory: a few thousand lines at most (the reader refuses more).
MAX_STATEMENT_BYTES = 5 * 1024 * 1024


def _statement_line(organization: Organization, line_id: int) -> BankStatementLine:
    try:
        return selectors.statement_line_of(organization, line_id)
    except ObjectDoesNotExist:
        raise Http404 from None


class StatementImportView(OfficeView):
    parser_classes = (MultiPartParser,)

    @extend_schema(
        operation_id="importBankStatement",
        request={"multipart/form-data": StatementImportSerializer},
        responses=StatementImportReportSerializer,
    )
    def post(self, request: Request, account_id: int) -> Response:
        """Add the lines of the bank's Excel statement (DATE, LIBELLE, DEBIT, CREDIT, SOLDE) to a bank account (owner
        or manager). All or nothing: one unreadable row (listed with its row number) and nothing is saved. A line
        already on the account is skipped, so the same file twice adds nothing."""
        account = _account(self.organization, account_id)
        serializer = StatementImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        if upload.size > MAX_STATEMENT_BYTES:
            raise ValidationError({"file": _("Fichier trop gros (5 Mo au plus).")})
        report = statements.import_statement(
            organization=self.organization, actor=self.membership.user, account=account, content=upload.read()
        )
        return Response(StatementImportReportSerializer(report).data)


class StatementLineListView(OfficeView, ListAPIView[BankStatementLine]):
    serializer_class = BankStatementLineSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[BankStatementLine]:
        filters = StatementLineFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        account = _account(self.organization, self.kwargs["account_id"])
        return selectors.statement_lines_of(
            self.organization,
            account,
            date_from=filters.validated_data.get("date_from"),
            date_to=filters.validated_data.get("date_to"),
        )

    @extend_schema(operation_id="listStatementLines", parameters=[StatementLineFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """The lines imported on a bank account between two days (inclusive), oldest first, paginated."""
        return super().get(request, *args, **kwargs)


class StatementLineDetailView(OfficeView):
    @extend_schema(
        operation_id="setStatementLineParty",
        request=StatementLinePartySerializer,
        responses=BankStatementLineSerializer,
    )
    def put(self, request: Request, line_id: int) -> Response:
        """Say whose line it is (owner or manager): a customer for a line at the debit, a supplier for one at the
        credit. Both left empty clears it."""
        line = _statement_line(self.organization, line_id)
        serializer = StatementLinePartySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            customer = partners.customer_of(self.organization, data["customer"]) if data["customer"] else None
        except ObjectDoesNotExist:
            raise ValidationError({"customer": _("Client inconnu.")}) from None
        try:
            supplier = partners.supplier_of(self.organization, data["supplier"]) if data["supplier"] else None
        except ObjectDoesNotExist:
            raise ValidationError({"supplier": _("Fournisseur inconnu.")}) from None
        statements.set_line_party(line=line, actor=self.membership.user, customer=customer, supplier=supplier)
        return Response(BankStatementLineSerializer(_statement_line(self.organization, line_id)).data)

    @extend_schema(operation_id="deleteStatementLine", responses={204: None})
    def delete(self, request: Request, line_id: int) -> Response:
        """Take a line off the statement (owner or manager): a wrong import. It was only a copy of the bank's file."""
        line = _statement_line(self.organization, line_id)
        statements.delete_line(line=line, actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
