"""Treasury: the banks list and the effets (D-197, P9-T01).

Office data: the owner and the manager write, the accountant reads, drivers get 403.
"""

from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import QuerySet
from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.pagination import PagedList
from apps.core.models import Membership, Organization
from apps.core.permissions import ReadOfficeWriteOwnerOrManager, membership_of

from .. import selectors, services
from ..models import Deposit, Instrument
from .serializers import (
    BankFilterSerializer,
    BankSerializer,
    BankWriteSerializer,
    DepositSerializer,
    DepositWriteSerializer,
    InstrumentBatchSerializer,
    InstrumentFilterSerializer,
    InstrumentSerializer,
    InstrumentTotalsSerializer,
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
        )
        return Response(BankSerializer(bank).data, status=status.HTTP_201_CREATED)


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
        """Hand received effets in portfolio to one of our banks (owner or manager): a bordereau RB-... holding
        them; each one becomes "Remis en banque". Its PDF is the document kind `bank_deposit`."""
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
