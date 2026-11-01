"""Cold-room cost and general costs endpoints (P5-T02, P5-T05, D-058, D-059)."""

from decimal import Decimal
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.models import Membership, Organization, Role
from apps.expenses import cost_selectors, selectors, services
from apps.expenses.costing import first_of_month
from apps.expenses.models import ElectricityBill, GeneralCostPeriod, RecurringCost
from apps.inventory import selectors as inventory

from .cost_serializers import (
    ColdRoomEstimateWriteSerializer,
    ColdRoomMonthFilterSerializer,
    ColdRoomMonthSerializer,
    ColdRoomSharesWriteSerializer,
    ColdRoomWeightSerializer,
    ColdRoomWeightWriteSerializer,
    ElectricityBillSerializer,
    ElectricityBillWriteSerializer,
    GeneralCostFilterSerializer,
    GeneralCostSerializer,
    GeneralCostWriteSerializer,
    GenerateRecurringSerializer,
    RecurringCostFilterSerializer,
    RecurringCostSerializer,
    RecurringCostWriteSerializer,
)
from .views import OfficeView


def _require_owner(membership: Membership) -> None:
    """The owner alone sets the weights of the cold rooms and the recurring costs (D-058, D-059)."""
    if membership.role != Role.OWNER:
        raise PermissionDenied(_("Seul le propriétaire gère les poids des chambres froides et les frais récurrents."))


def _category(organization: Organization, category_id: int) -> Any:
    try:
        return selectors.category_of(organization, category_id)
    except ObjectDoesNotExist:
        raise DjangoValidationError({"category": _("Catégorie inconnue.")}) from None


# ---- Weights of the cold rooms ----


def _weight_rows(organization: Organization) -> list[dict[str, Any]]:
    weights = cost_selectors.room_weights(organization)
    names = {room.pk: room.name for room in cost_selectors.cold_rooms(organization)}
    total = sum(weights.values(), Decimal("0"))
    return [
        {
            "location_id": room_id,
            "location_name": names[room_id],
            "weight": weight,
            "share_percent": (weight * 100 / total).quantize(Decimal("0.01")) if total else Decimal("0.00"),
        }
        for room_id, weight in weights.items()
    ]


class ColdRoomWeightListView(OfficeView):
    @extend_schema(operation_id="listColdRoomWeights", responses=ColdRoomWeightSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The active cold rooms with their weight in the split of the electricity bill (equal, 1, unless
        the owner set another) and the share it gives."""
        return Response(ColdRoomWeightSerializer(_weight_rows(self.organization), many=True).data)


class ColdRoomSharesView(OfficeView):
    @extend_schema(
        operation_id="updateColdRoomShares",
        request=ColdRoomSharesWriteSerializer,
        responses=ColdRoomWeightSerializer(many=True),
    )
    def put(self, request: Request) -> Response:
        """Set every active cold room's share of the electricity bill in %, adding up to 100 (owner only):
        used by the bills approved from now on."""
        _require_owner(self.membership)
        serializer = ColdRoomSharesWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rows = serializer.validated_data["shares"]
        shares = {row["location_id"]: row["percent"] for row in rows}
        if len(shares) != len(rows):
            raise DjangoValidationError({"shares": _("Une chambre froide n'apparaît qu'une fois.")})
        services.set_cold_room_shares(organization=self.organization, actor=self.membership.user, shares=shares)
        return Response(ColdRoomWeightSerializer(_weight_rows(self.organization), many=True).data)


class ColdRoomWeightDetailView(OfficeView):
    @extend_schema(
        operation_id="updateColdRoomWeight",
        request=ColdRoomWeightWriteSerializer,
        responses=ColdRoomWeightSerializer(many=True),
    )
    def put(self, request: Request, location_id: int) -> Response:
        """Set a cold room's weight (owner only): used by the bills approved from now on."""
        _require_owner(self.membership)
        try:
            location = inventory.location_of(self.organization, location_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        serializer = ColdRoomWeightWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_cold_room_weight(
            organization=self.organization,
            actor=self.membership.user,
            location=location,
            weight=serializer.validated_data["weight"],
        )
        return Response(ColdRoomWeightSerializer(_weight_rows(self.organization), many=True).data)


# ---- Electricity bills and the month view ----


class ColdRoomMonthView(OfficeView):
    @extend_schema(
        operation_id="getColdRoomMonth",
        parameters=[ColdRoomMonthFilterSerializer],
        responses=ColdRoomMonthSerializer,
    )
    def get(self, request: Request) -> Response:
        """One month of cold-room costs: the bill if any, and per room its weight and cost for the month
        and per day, estimated (the estimate typed for the month, else the previous month's daily rate) until the
        bill is approved; the estimate and the difference with the real bill come with it."""
        filters = ColdRoomMonthFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        month = filters.validated_data.get("month") or timezone.localdate()
        return Response(
            ColdRoomMonthSerializer(cost_selectors.cold_room_month(self.organization, month=first_of_month(month))).data
        )


class ColdRoomEstimateView(OfficeView):
    @extend_schema(
        operation_id="updateColdRoomEstimate",
        request=ColdRoomEstimateWriteSerializer,
        responses=ColdRoomMonthSerializer,
    )
    def put(self, request: Request) -> Response:
        """Type the electricity estimate of a month for all the cold rooms (owner or manager), until the month's
        bill is approved: the rooms share it by weight, as the bill is shared (D-227)."""
        serializer = ColdRoomEstimateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.set_cold_room_estimate(
            organization=self.organization,
            actor=self.membership.user,
            month=data["month"],
            amount=data["amount"],
            reason=data["reason"],
        )
        month = first_of_month(data["month"])
        return Response(ColdRoomMonthSerializer(cost_selectors.cold_room_month(self.organization, month=month)).data)


class ElectricityBillView(OfficeView):
    def bill(self, bill_id: int) -> ElectricityBill:
        try:
            return cost_selectors.bill_of(self.organization, bill_id)
        except ElectricityBill.DoesNotExist:
            raise Http404 from None


class ElectricityBillListView(ElectricityBillView):
    @extend_schema(operation_id="listElectricityBills", responses=ElectricityBillSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Electricity bills, newest month first."""
        return Response(ElectricityBillSerializer(cost_selectors.bills_of(self.organization), many=True).data)

    @extend_schema(
        operation_id="createElectricityBill",
        request=ElectricityBillWriteSerializer,
        responses={201: ElectricityBillSerializer},
    )
    def post(self, request: Request) -> Response:
        """Type the electricity bill of a finished month (one expense of category cold storage). A draft
        until approved; `approve_now` approves it at once, which fixes the rooms' shares and corrects the
        lots' estimates."""
        serializer = ElectricityBillWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        approve = data.pop("approve_now")
        bill = services.create_electricity_bill(
            organization=self.organization, actor=self.membership.user, approve=approve, **data
        )
        return Response(ElectricityBillSerializer(bill).data, status=status.HTTP_201_CREATED)


class ElectricityBillDetailView(ElectricityBillView):
    @extend_schema(
        operation_id="updateElectricityBill",
        request=ElectricityBillWriteSerializer,
        responses=ElectricityBillSerializer,
    )
    def put(self, request: Request, bill_id: int) -> Response:
        """Correct a bill not approved yet (the month cannot change); with `approve_now`, approve it too."""
        bill = self.bill(bill_id)
        serializer = ElectricityBillWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = {key: value for key, value in serializer.validated_data.items() if key != "month"}
        approve = data.pop("approve_now")
        updated = services.update_electricity_bill(bill=bill, actor=self.membership.user, approve=approve, **data)
        return Response(ElectricityBillSerializer(updated).data)

    @extend_schema(operation_id="deleteElectricityBill", responses={204: None})
    def delete(self, request: Request, bill_id: int) -> Response:
        """Delete a bill typed by mistake while it is a draft."""
        services.delete_electricity_bill(bill=self.bill(bill_id), actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ElectricityBillApproveView(ElectricityBillView):
    @extend_schema(operation_id="approveElectricityBill", request=None, responses=ElectricityBillSerializer)
    def post(self, request: Request, bill_id: int) -> Response:
        """Approve a draft bill: fixes the rooms' shares and books the difference with the estimate on
        each lot, dated today."""

        bill = self.bill(bill_id)
        services.approve_expense(expense=bill.expense, actor=self.membership.user)
        return Response(ElectricityBillSerializer(self.bill(bill_id)).data)


# ---- Recurring costs ----


class RecurringCostListView(OfficeView):
    @extend_schema(
        operation_id="listRecurringCosts",
        parameters=[RecurringCostFilterSerializer],
        responses=RecurringCostSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Monthly costs (rent, accountant, insurance), by name."""
        filters = RecurringCostFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        costs = cost_selectors.recurring_costs_of(self.organization, active_only=filters.validated_data["active_only"])
        return Response(RecurringCostSerializer(costs, many=True).data)

    @extend_schema(
        operation_id="createRecurringCost",
        request=RecurringCostWriteSerializer,
        responses={201: RecurringCostSerializer},
    )
    def post(self, request: Request) -> Response:
        """Add a monthly cost (owner only): a template that generates the month's expense."""
        _require_owner(self.membership)
        serializer = RecurringCostWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = {key: value for key, value in serializer.validated_data.items() if key != "is_active"}
        data["category"] = _category(self.organization, data["category"])
        cost = services.create_recurring_cost(organization=self.organization, actor=self.membership.user, **data)
        return Response(RecurringCostSerializer(cost).data, status=status.HTTP_201_CREATED)


class RecurringCostDetailView(OfficeView):
    @extend_schema(
        operation_id="updateRecurringCost", request=RecurringCostWriteSerializer, responses=RecurringCostSerializer
    )
    def put(self, request: Request, cost_id: int) -> Response:
        """Change a monthly cost or stop it (`is_active` false), owner only. Months already generated keep
        their amount."""
        _require_owner(self.membership)
        try:
            cost = cost_selectors.recurring_cost_of(self.organization, cost_id)
        except RecurringCost.DoesNotExist:
            raise Http404 from None
        serializer = RecurringCostWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data["category"] = _category(self.organization, data["category"])
        updated = services.update_recurring_cost(cost=cost, actor=self.membership.user, **data)
        return Response(RecurringCostSerializer(updated).data)


class RecurringCostGenerateView(OfficeView):
    @extend_schema(
        operation_id="generateRecurringCosts",
        request=GenerateRecurringSerializer,
        responses=GeneralCostSerializer(many=True),
    )
    def post(self, request: Request) -> Response:
        """Generate the month's expense of every active monthly cost that has none yet (safe to repeat):
        drafts, or approved with `approve_now`. Returns the ones created."""
        serializer = GenerateRecurringSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created = services.generate_recurring_costs(
            organization=self.organization,
            actor=self.membership.user,
            month=serializer.validated_data["month"],
            approve=serializer.validated_data["approve_now"],
        )
        periods = cost_selectors.general_periods_of(self.organization).filter(pk__in=[p.pk for p in created])
        return Response(GeneralCostSerializer(periods, many=True).data)


# ---- General costs (a month of a template, or a bill over several months) ----


class GeneralCostListView(OfficeView):
    @extend_schema(
        operation_id="listGeneralCosts",
        parameters=[GeneralCostFilterSerializer],
        responses=GeneralCostSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """General costs spread over the lots, newest first; with `month`, those covering that month."""
        filters = GeneralCostFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        periods = cost_selectors.general_periods_of(self.organization, month=filters.validated_data.get("month"))
        return Response(GeneralCostSerializer(periods, many=True).data)

    @extend_schema(
        operation_id="createGeneralCost", request=GeneralCostWriteSerializer, responses={201: GeneralCostSerializer}
    )
    def post(self, request: Request) -> Response:
        """Type a bill covering one or several months (an insurance for a year): one expense spread
        equally over the months, each month charged to the lots "like a salary" (monthly / 26 per day by
        kg held). A draft until approved (`approve_now` approves it at once)."""
        serializer = GeneralCostWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        approve = data.pop("approve_now")
        data["category"] = _category(self.organization, data["category"])
        period = services.create_general_cost(
            organization=self.organization, actor=self.membership.user, approve=approve, **data
        )
        return Response(GeneralCostSerializer(period).data, status=status.HTTP_201_CREATED)


class GeneralCostDetailView(OfficeView):
    @extend_schema(operation_id="deleteGeneralCost", responses={204: None})
    def delete(self, request: Request, period_id: int) -> Response:
        """Delete a general cost typed by mistake while it is a draft (with its expense)."""
        try:
            period = cost_selectors.general_period_of(self.organization, period_id)
        except GeneralCostPeriod.DoesNotExist:
            raise Http404 from None
        services.delete_general_cost(period=period, actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
