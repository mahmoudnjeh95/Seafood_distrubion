from typing import TYPE_CHECKING

from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Membership
from apps.core.permissions import IsDriver, ReadOfficeWriteOwnerOrManager, membership_of
from apps.dayclose import selectors, services
from apps.dayclose.models import DayClosing, SyncProblem
from apps.fleet import selectors as fleet

if TYPE_CHECKING:
    from apps.fleet.models import DriverDay

from .serializers import (
    DayClosingApproveSerializer,
    DayClosingCorrectSerializer,
    DayClosingCountSerializer,
    DayClosingDetailSerializer,
    DayClosingFilterSerializer,
    DayClosingRowSerializer,
    DayClosingWriteSerializer,
    DayExpenseDecisionSerializer,
    DayOverviewDetailSerializer,
    DayOverviewDriverSerializer,
    DayOverviewFilterSerializer,
    DayOverviewRowSerializer,
    DayReturnToStockSerializer,
    DayRouteSerializer,
    JustificationSerializer,
    MyDayRowSerializer,
    MyDaySummarySerializer,
    SyncProblemSerializer,
    SyncProblemWriteSerializer,
)


def _my_day_answer(membership: Membership) -> dict[str, object]:
    driver_day = fleet.driver_day_of(membership)
    if driver_day is None:
        raise Http404
    return selectors.day_answer(membership.organization, driver_day)


def _my_past_day(membership: Membership, day_id: int) -> "DriverDay":
    try:
        return fleet.driver_days_of(membership.organization, driver_id=membership.user_id).get(pk=day_id)
    except ObjectDoesNotExist:
        raise Http404 from None


class MyDaySummaryView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="getMyDaySummary", responses=MyDaySummarySerializer)
    def get(self, request: Request) -> Response:
        """The driver's day so far: sales, cash, expenses and the stock per product, and the closing if sent.
        404 until the day is started."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        return Response(MyDaySummarySerializer(_my_day_answer(membership)).data)


class MyDayClosingView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(
        operation_id="closeMyDay", request=DayClosingWriteSerializer, responses={201: MyDaySummarySerializer}
    )
    def post(self, request: Request) -> Response:
        """Send the end of the day with an optional note: the day is closed until a load validated that date opens
        it again. The driver sees what they should hold; the office counts the cash (D-213). Sent again after the
        office asked for a justification, after such a load, or when the day's records changed since the send."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        serializer = DayClosingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        driver_day = fleet.driver_day_of(membership)
        if driver_day is None:
            raise Http404
        services.submit_day_closing(
            driver_day=driver_day,
            actor=membership.user,
            note=serializer.validated_data["note"],
        )
        return Response(MyDaySummarySerializer(_my_day_answer(membership)).data, status=status.HTTP_201_CREATED)


class MyDayListView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="listMyDays", responses=MyDayRowSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The driver's own days, newest first (the last 60), each with its closing when sent (D-134)."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        rows = fleet.driver_days_of(membership.organization, driver_id=membership.user_id).select_related("closing")
        return Response(MyDayRowSerializer(rows[:60], many=True).data)


class MyDayDetailView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="getMyPastDay", responses=MyDaySummarySerializer)
    def get(self, request: Request, day_id: int) -> Response:
        """One of the driver's days: the figures as sent, or live while it runs."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        driver_day = _my_past_day(membership, day_id)
        return Response(MyDaySummarySerializer(selectors.day_answer(membership.organization, driver_day)).data)


class MyPastDayClosingView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(
        operation_id="closeMyPastDay", request=DayClosingWriteSerializer, responses={201: MyDaySummarySerializer}
    )
    def post(self, request: Request, day_id: int) -> Response:
        """Send the closing of one of the driver's days from the history: again after the office asked for a
        justification, or a day left open."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        serializer = DayClosingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        driver_day = _my_past_day(membership, day_id)
        services.submit_day_closing(
            driver_day=driver_day,
            actor=membership.user,
            note=serializer.validated_data["note"],
        )
        driver_day = _my_past_day(membership, day_id)
        return Response(
            MyDaySummarySerializer(selectors.day_answer(membership.organization, driver_day)).data,
            status=status.HTTP_201_CREATED,
        )


# Base of the office views: rows of the user's organization only. Owner and manager decide, the accountant reads.
class DayClosingView(APIView):
    permission_classes = (ReadOfficeWriteOwnerOrManager,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    def closing(self, closing_id: int) -> DayClosing:
        try:
            return selectors.closing_by_id(self.membership.organization, closing_id)
        except ObjectDoesNotExist:
            raise Http404 from None

    def answer(self, closing_id: int) -> Response:
        return Response(DayClosingDetailSerializer(self.closing(closing_id)).data)


class DayClosingListView(DayClosingView):
    @extend_schema(
        operation_id="listDayClosings",
        parameters=[DayClosingFilterSerializer],
        responses=DayClosingRowSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Days sent by the drivers, newest first (the last 200 matching): to check, and their history. Filter by
        status, driver or truck, and dates."""
        filters = DayClosingFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        rows = selectors.closings_of(
            self.membership.organization,
            status=data.get("status"),
            search=data["search"],
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
        )
        return Response(DayClosingRowSerializer(rows[:200], many=True).data)


class DayOverviewListView(DayClosingView):
    @extend_schema(
        operation_id="listDayOverview",
        parameters=[DayOverviewFilterSerializer],
        responses=DayOverviewRowSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """The drivers' days as they stand, running or sent (the last 100 matching): money, sales and deliveries.
        Filter by driver, truck and dates."""
        filters = DayOverviewFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        days = fleet.driver_days_between(
            self.membership.organization,
            driver_id=data.get("driver_id"),
            truck_id=data.get("truck_id"),
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
        )
        rows = [selectors.day_row(self.membership.organization, day) for day in days[:100]]
        return Response(DayOverviewRowSerializer(rows, many=True).data)


class DayOverviewDriversView(DayClosingView):
    @extend_schema(operation_id="listDayOverviewDrivers", responses=DayOverviewDriverSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The drivers who opened at least one day, by name: the choices of the driver filter."""
        rows = fleet.drivers_with_days(self.membership.organization)
        return Response(DayOverviewDriverSerializer(rows, many=True).data)


class DayOverviewDetailView(DayClosingView):
    @extend_schema(operation_id="getDayOverview", responses=DayOverviewDetailSerializer)
    def get(self, request: Request, day_id: int) -> Response:
        """One driver's day: figures, sales, deliveries to do and done, payments collected and expenses."""
        try:
            day = fleet.driver_day_by_id(self.membership.organization, day_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        return Response(DayOverviewDetailSerializer(selectors.day_activity(self.membership.organization, day)).data)


class DayOverviewActionView(DayClosingView):
    """Base of the office's decisions on a driver's day (D-239): each one answers with the day as it stands."""

    def day(self, day_id: int) -> "DriverDay":
        try:
            return fleet.driver_day_by_id(self.membership.organization, day_id)
        except ObjectDoesNotExist:
            raise Http404 from None

    def answer_day(self, day: "DriverDay") -> Response:
        return Response(DayOverviewDetailSerializer(selectors.day_activity(self.membership.organization, day)).data)


class DayOverviewExpenseDecisionView(DayOverviewActionView):
    @extend_schema(
        operation_id="decideDayOverviewExpense",
        request=DayExpenseDecisionSerializer,
        responses=DayOverviewDetailSerializer,
    )
    def post(self, request: Request, day_id: int, expense_id: int) -> Response:
        """Approve or refuse one expense the driver typed on the day (owner or manager). A refusal needs its `reason`.
        A sent day whose figures move is corrected with a revision."""
        serializer = DayExpenseDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        day = self.day(day_id)
        try:
            expense = selectors.expense_of_day(self.membership.organization, day, expense_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        services.decide_driver_expense(
            driver_day=day,
            expense=expense,
            actor=self.membership.user,
            approve=serializer.validated_data["decision"] == "approve",
            reason=serializer.validated_data["reason"],
        )
        return self.answer_day(day)


class DayOverviewPurchaseValidateView(DayOverviewActionView):
    @extend_schema(operation_id="validateDayOverviewPurchase", request=None, responses=DayOverviewDetailSerializer)
    def post(self, request: Request, day_id: int, purchase_id: int) -> Response:
        """Validate a purchase the driver made on the day (owner or manager): its kilos enter the truck's stock. Refused
        while the purchase is not complete (supplier, products, place)."""
        day = self.day(day_id)
        try:
            purchase = selectors.purchase_of_day(self.membership.organization, day, purchase_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        services.validate_driver_purchase(driver_day=day, purchase=purchase, actor=self.membership.user)
        return self.answer_day(day)


class DayOverviewReturnToStockView(DayOverviewActionView):
    @extend_schema(
        operation_id="returnDayOverviewToStock",
        request=DayReturnToStockSerializer,
        responses=DayOverviewDetailSerializer,
    )
    def post(self, request: Request, day_id: int) -> Response:
        """Give back what the truck still holds, kilos and boxes, to the cold room the office chooses (owner or
        manager; `to_location_id` may be left out only when there is one active cold room). Works whether or not the
        driver sent the day; only on the truck's latest day."""
        serializer = DayReturnToStockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        day = self.day(day_id)
        services.return_truck_to_stock(
            driver_day=day,
            actor=self.membership.user,
            to_location_id=serializer.validated_data["to_location_id"],
        )
        return self.answer_day(day)


class DayOverviewRouteView(DayClosingView):
    @extend_schema(operation_id="getDayRoute", responses=DayRouteSerializer)
    def get(self, request: Request, day_id: int) -> Response:
        """The GPS route of one driver's day for the map: the points in time order and the last one (D-167)."""
        try:
            day = fleet.driver_day_by_id(self.membership.organization, day_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        return Response(DayRouteSerializer(selectors.day_route(self.membership.organization, day)).data)


class DayClosingDetailView(DayClosingView):
    @extend_schema(operation_id="getDayClosing", responses=DayClosingDetailSerializer)
    def get(self, request: Request, closing_id: int) -> Response:
        """One day with its figures as the driver sent them."""
        return self.answer(closing_id)


class DayClosingApproveView(DayClosingView):
    @extend_schema(
        operation_id="approveDayClosing", request=DayClosingApproveSerializer, responses=DayClosingDetailSerializer
    )
    def post(self, request: Request, closing_id: int) -> Response:
        """Approve the day (owner or manager): it is locked. The cash the office counted (D-213) is kept by the count
        endpoint, or sent here; a gap with what the driver should hold needs a `note`. Refused for a day a new load
        reopened, or whose records changed since the send: the driver sends it again first."""
        serializer = DayClosingApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.approve_day_closing(
            closing=self.closing(closing_id), actor=self.membership.user, **serializer.validated_data
        )
        return self.answer(closing_id)


class DayClosingCountView(DayClosingView):
    @extend_schema(
        operation_id="countDayClosing", request=DayClosingCountSerializer, responses=DayClosingDetailSerializer
    )
    def post(self, request: Request, closing_id: int) -> Response:
        """The office counts the cash the driver hands over (owner or manager, D-213), before the approval: the gap
        with what the driver should hold shows at once. Refused once approved, or while the records changed since
        the send."""
        serializer = DayClosingCountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.record_office_count(
            closing=self.closing(closing_id), actor=self.membership.user, **serializer.validated_data
        )
        return self.answer(closing_id)


class DayClosingCorrectView(DayClosingView):
    @extend_schema(
        operation_id="correctDayClosing", request=DayClosingCorrectSerializer, responses=DayClosingDetailSerializer
    )
    def post(self, request: Request, closing_id: int) -> Response:
        """The office corrects a driver's day (owner or manager, D-220): the driver never changes a sent day. The
        day's figures are taken as the records say now, and the counts are changed when given. Needs a `reason`;
        the correction is kept as a revision with the figures before and after. Refused for a day a new load
        reopened."""
        serializer = DayClosingCorrectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.correct_day_closing(
            closing=self.closing(closing_id), actor=self.membership.user, **serializer.validated_data
        )
        return self.answer(closing_id)


class DayClosingJustificationView(DayClosingView):
    @extend_schema(
        operation_id="requestDayJustification", request=JustificationSerializer, responses=DayClosingDetailSerializer
    )
    def post(self, request: Request, closing_id: int) -> Response:
        """Ask the driver to explain, saying what; they send the day again with a note."""
        serializer = JustificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_justification(
            closing=self.closing(closing_id), actor=self.membership.user, reason=serializer.validated_data["reason"]
        )
        return self.answer(closing_id)


class MySyncProblemsView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(
        operation_id="reportSyncProblem", request=SyncProblemWriteSerializer, responses={201: SyncProblemSerializer}
    )
    def post(self, request: Request) -> Response:
        """The phone tells the office that the server refused something it tried to send (kept on the phone
        until then). The same item reported twice makes one problem."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        serializer = SyncProblemWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        problem = services.report_sync_problem(
            organization=membership.organization,
            actor=membership.user,
            kind=data["kind"],
            label=data["what"],
            reason=data["reason"],
            client_uuid=data["client_uuid"],
        )
        return Response(SyncProblemSerializer(problem).data, status=status.HTTP_201_CREATED)


class SyncProblemListView(DayClosingView):
    @extend_schema(operation_id="listSyncProblems", responses=SyncProblemSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Sends the server refused, reported by the drivers' phones and not dealt with yet."""
        rows = selectors.sync_problems_of(self.membership.organization)
        return Response(SyncProblemSerializer(rows[:100], many=True).data)


class SyncProblemResolveView(DayClosingView):
    @extend_schema(operation_id="resolveSyncProblem", request=None, responses=SyncProblemSerializer)
    def post(self, request: Request, problem_id: int) -> Response:
        """Mark a refused send as dealt with (owner or manager)."""
        try:
            problem: SyncProblem = selectors.sync_problem_by_id(self.membership.organization, problem_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        services.resolve_sync_problem(problem=problem, actor=self.membership.user)
        return Response(
            SyncProblemSerializer(selectors.sync_problem_by_id(self.membership.organization, problem_id)).data
        )
