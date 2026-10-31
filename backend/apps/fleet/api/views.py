from datetime import date

from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Membership, Organization, Role
from apps.core.permissions import IsDriver, ReadOfficeWriteOwnerOrManager, membership_of
from apps.fleet import selectors, services
from apps.fleet.models import Truck, TruckAssignment, TruckCondition

from .permissions import AssignmentsOfficeOrOwnDriver, OwnTruckOrOffice
from .serializers import (
    DayFundRowSerializer,
    DayFundSerializer,
    DayFundWriteSerializer,
    DriverDaySerializer,
    LocationPingBatchSerializer,
    LocationPingSavedSerializer,
    PurchaseFloatSerializer,
    TruckAssignmentFilterSerializer,
    TruckAssignmentSerializer,
    TruckAssignmentWriteSerializer,
    TruckChoiceSerializer,
    TruckFilterSerializer,
    TruckSerializer,
    TruckWriteSerializer,
)


# Base of the truck views: rows of the user's organization only (D-022), a driver's own truck only.
# A comment, not a docstring: a docstring would become the description of every endpoint in the schema.
class TruckView(APIView):
    permission_classes = (OwnTruckOrOffice,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    @property
    def organization(self) -> Organization:
        return self.membership.organization

    def truck(self, truck_id: int) -> Truck:
        try:
            truck = selectors.truck_of(self.organization, truck_id)
        except Truck.DoesNotExist:
            raise Http404 from None
        self.check_object_permissions(self.request, truck)
        return truck

    def truck_answer(self, truck_id: int, status_code: int = status.HTTP_200_OK) -> Response:
        return Response(TruckSerializer(selectors.truck_of(self.organization, truck_id)).data, status=status_code)


class TruckListView(TruckView):
    @extend_schema(operation_id="listTrucks", parameters=[TruckFilterSerializer], responses=TruckSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Trucks sorted by name, with their driver. A driver sees only their own truck."""
        filters = TruckFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        trucks = selectors.trucks_of(self.organization, status=filters.validated_data["status"])
        if self.membership.role not in selectors.OFFICE_ROLES:
            own = selectors.truck_of_driver(self.membership)
            trucks = trucks.filter(pk=own.pk) if own else trucks.none()
        drivers = selectors.drivers_of_day(self.organization, timezone.localdate())
        return Response(TruckSerializer(trucks, many=True, context={"drivers_today": drivers}).data)

    @extend_schema(operation_id="createTruck", request=TruckWriteSerializer, responses={201: TruckSerializer})
    def post(self, request: Request) -> Response:
        """A new truck, with the stock location that holds its goods."""
        serializer = TruckWriteSerializer(data=request.data, context={"organization": self.organization})
        serializer.is_valid(raise_exception=True)
        truck = services.create_truck(
            organization=self.organization, actor=self.membership.user, **serializer.validated_data
        )
        return self.truck_answer(truck.pk, status.HTTP_201_CREATED)


class TruckDetailView(TruckView):
    @extend_schema(operation_id="getTruck", responses=TruckSerializer)
    def get(self, request: Request, truck_id: int) -> Response:
        return Response(TruckSerializer(self.truck(truck_id)).data)

    @extend_schema(operation_id="updateTruck", request=TruckWriteSerializer, responses=TruckSerializer)
    def patch(self, request: Request, truck_id: int) -> Response:
        """Rename a truck, change its plate or its driver (`driver: null` takes it back from its driver)."""
        truck = self.truck(truck_id)
        serializer = TruckWriteSerializer(data=request.data, partial=True, context={"organization": self.organization})
        serializer.is_valid(raise_exception=True)
        services.update_truck(truck=truck, actor=self.membership.user, **serializer.validated_data)
        return self.truck_answer(truck_id)


class TruckArchiveView(TruckView):
    @extend_schema(operation_id="archiveTruck", request=None, responses=TruckSerializer)
    def post(self, request: Request, truck_id: int) -> Response:
        """An archived truck keeps its history, receives no more stock and has no driver."""
        services.set_truck_active(truck=self.truck(truck_id), actor=self.membership.user, is_active=False)
        return self.truck_answer(truck_id)


class TruckRestoreView(TruckView):
    @extend_schema(operation_id="restoreTruck", request=None, responses=TruckSerializer)
    def post(self, request: Request, truck_id: int) -> Response:
        services.set_truck_active(truck=self.truck(truck_id), actor=self.membership.user, is_active=True)
        return self.truck_answer(truck_id)


# Base of the assignment views (a comment, not a docstring: see TruckView).
class TruckAssignmentView(APIView):
    permission_classes = (AssignmentsOfficeOrOwnDriver,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    @property
    def is_driver(self) -> bool:
        return self.membership.role == Role.DRIVER

    def refuse_past_day(self, day: date) -> None:
        # The office corrects any day; a driver only sets today or a day to come.
        if self.is_driver and day < timezone.localdate():
            raise exceptions.ValidationError({"date": _("Un chauffeur ne peut pas modifier un jour passé.")})

    def refuse_open_day(self, day: date, *, keeping: int | None = None) -> None:
        # Once the driver has opened the day, its cash, sales and closing are counted on that truck: only the
        # office may move it (D-108). Asking again for the same truck changes nothing, so it is allowed.
        if not self.is_driver or selectors.driver_day_of(self.membership, day) is None:
            return
        current = selectors.truck_of_driver(self.membership, day)
        if keeping is None or current is None or current.pk != keeping:
            raise exceptions.ValidationError(
                {"truck": _("Votre journée est ouverte : seul le bureau change le camion.")}
            )

    def refuse_truck_in_use(self, day: date, truck_id: int) -> None:
        # A truck another driver started their day on (usually their own truck, with no assignment that day) is
        # theirs for that date: their cash, sales and closing are counted on it. A driver taking it would lock
        # them out of their own truck and sell their stock (D-141). Only the office may move it.
        if not self.is_driver:
            return
        other = selectors.day_on_truck_of_another(
            self.membership.organization, truck_id=truck_id, day=day, driver_id=self.membership.user_id
        )
        if other is not None:
            raise exceptions.ValidationError(
                {"truck": _("Ce camion est déjà utilisé ce jour-là par un autre chauffeur : demandez au bureau.")}
            )


class TruckAssignmentListView(TruckAssignmentView):
    @extend_schema(
        operation_id="listTruckAssignments",
        parameters=[TruckAssignmentFilterSerializer],
        responses=TruckAssignmentSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Who drives which truck on a day (today by default). A driver sees only their own assignment."""
        filters = TruckAssignmentFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        day = filters.validated_data.get("date") or timezone.localdate()
        rows = selectors.assignments_on(self.membership.organization, day)
        if self.is_driver:
            rows = rows.filter(driver=self.membership.user)
        return Response(TruckAssignmentSerializer(rows, many=True).data)

    @extend_schema(
        operation_id="assignTruck", request=TruckAssignmentWriteSerializer, responses={201: TruckAssignmentSerializer}
    )
    def post(self, request: Request) -> Response:
        """Give a truck to a driver for a day. A driver can only take a truck for themselves; they may
        change their own mind, the office must remove the first assignment before giving another truck."""
        organization = self.membership.organization
        serializer = TruckAssignmentWriteSerializer(data=request.data, context={"organization": organization})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        day = data.get("date") or timezone.localdate()
        self.refuse_past_day(day)
        self.refuse_open_day(day, keeping=data["truck"])
        self.refuse_truck_in_use(day, data["truck"])
        driver = data.get("driver")
        free = data["free"]
        if free and self.is_driver:
            raise exceptions.PermissionDenied(_("Seul le bureau libère un camion."))
        if self.is_driver:
            if driver is not None and driver.pk != self.membership.user_id:
                raise exceptions.PermissionDenied(_("Un chauffeur ne choisit le camion que pour lui-même."))
            driver = self.membership.user
        elif free:
            driver = None
        elif driver is None:
            raise exceptions.ValidationError({"driver": _("Choisissez un chauffeur.")})
        try:
            truck = selectors.truck_of(organization, data["truck"])
        except Truck.DoesNotExist:
            raise exceptions.ValidationError({"truck": _("Camion introuvable.")}) from None
        assignment = services.assign_truck(
            organization=organization,
            actor=self.membership.user,
            truck=truck,
            driver=driver,
            date=day,
            replace=self.is_driver,
        )
        saved = selectors.assignment_of(organization, assignment.pk)
        return Response(TruckAssignmentSerializer(saved).data, status=status.HTTP_201_CREATED)


class TruckAssignmentDetailView(TruckAssignmentView):
    @extend_schema(operation_id="unassignTruck", request=None, responses={204: None})
    def delete(self, request: Request, assignment_id: int) -> Response:
        """Take an assignment back: the truck falls back to its usual driver for that day."""
        try:
            assignment = selectors.assignment_of(self.membership.organization, assignment_id)
        except TruckAssignment.DoesNotExist:
            raise Http404 from None
        if self.is_driver and assignment.driver_id != self.membership.user_id:
            raise Http404  # another driver's day does not exist for them
        self.refuse_past_day(assignment.date)
        self.refuse_open_day(assignment.date)
        services.unassign_truck(assignment=assignment, actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyTruckChoicesView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="listMyTruckChoices", responses=TruckChoiceSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The active trucks a driver may take today, each marked if another driver already has it."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        organization = membership.organization
        taken = set(
            selectors.assignments_on(organization, timezone.localdate())
            .exclude(driver_id=membership.user_id)
            .exclude(driver__isnull=True)
            .values_list("truck_id", flat=True)
        )
        trucks = [
            {"id": t.pk, "location": t.location, "plate": t.plate, "taken": t.pk in taken}
            for t in selectors.trucks_of(organization).filter(condition=TruckCondition.OK)
        ]
        return Response(TruckChoiceSerializer(trucks, many=True).data)


class MyDayView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="getMyDay", responses=DriverDaySerializer)
    def get(self, request: Request) -> Response:
        """The day the driver opened today. 404 when they have not started yet."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        day = selectors.driver_day_of(membership)
        if day is None:
            raise Http404
        return Response(DriverDaySerializer(day).data)

    @extend_schema(operation_id="openMyDay", request=None, responses={201: DriverDaySerializer})
    def post(self, request: Request) -> Response:
        """Accept the cash the office set for today and start the day with it (D-203), on the driver's truck of the
        day. Refused while the office has set nothing. One day per date: asking again returns it unchanged."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        truck = selectors.truck_of_driver(membership)
        if truck is None:
            raise exceptions.ValidationError(_("Choisissez d'abord votre camion."))
        day = services.accept_day_fund(
            organization=membership.organization, actor=membership.user, truck=truck, date=timezone.localdate()
        )
        return Response(DriverDaySerializer(day).data, status=status.HTTP_201_CREATED)


class MyDayFundView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="getMyDayFund", responses=DayFundSerializer)
    def get(self, request: Request) -> Response:
        """The cash the office set for the driver today, to accept before starting the day (D-203). 404: none yet."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        fund = selectors.day_fund_of(membership.organization, driver_id=membership.user_id)
        if fund is None:
            raise Http404
        return Response(DayFundSerializer(fund).data)


class DayFundListView(APIView):
    permission_classes = (ReadOfficeWriteOwnerOrManager,)

    @extend_schema(
        operation_id="listDayFunds",
        parameters=[TruckAssignmentFilterSerializer],
        responses=DayFundRowSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Every active driver with the cash set for them on a day (today by default) and whether they started."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        filters = TruckAssignmentFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        day = filters.validated_data.get("date") or timezone.localdate()
        return Response(DayFundRowSerializer(selectors.day_funds_on(membership.organization, day), many=True).data)

    @extend_schema(operation_id="setDayFund", request=DayFundWriteSerializer, responses=DayFundSerializer)
    def put(self, request: Request) -> Response:
        """Set the cash handed to a driver for a day (D-203); it changes until the driver accepts it."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        serializer = DayFundWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        driver = Membership.objects.filter(
            organization=membership.organization, user_id=data["driver"], role=Role.DRIVER
        ).first()
        if driver is None:
            raise exceptions.ValidationError({"driver": _("Chauffeur inconnu.")})
        fund = services.set_day_fund(
            organization=membership.organization,
            actor=membership.user,
            driver=driver.user,
            date=data["date"],
            opening_cash=data["opening_cash"],
            purchase_float=data["purchase_float"],
        )
        return Response(DayFundSerializer(fund).data)


class MyPurchaseFloatView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="setMyPurchaseFloat", request=PurchaseFloatSerializer, responses=DriverDaySerializer)
    def put(self, request: Request) -> Response:
        """The money the office gave for purchases at the port today, typed again when it gives more (D-158).
        404 before the day is started; refused once its closing is sent."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        day = selectors.driver_day_of(membership)
        if day is None:
            raise Http404
        serializer = PurchaseFloatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        day = services.set_purchase_float(
            driver_day=day, actor=membership.user, purchase_float=serializer.validated_data["purchase_float"]
        )
        return Response(DriverDaySerializer(day).data)


class MyLocationsView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(
        operation_id="recordMyLocations", request=LocationPingBatchSerializer, responses=LocationPingSavedSerializer
    )
    def post(self, request: Request) -> Response:
        """The GPS points of the driver's phone for today's day, up to 200 at a time (D-164). A resent point is
        stored once; points after the sent closing are dropped. 404 until the day is started."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        serializer = LocationPingBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        day = selectors.driver_day_of(membership)
        if day is None:
            raise Http404
        saved = services.record_location_pings(driver_day=day, points=serializer.validated_data["points"])
        return Response(LocationPingSavedSerializer({"saved": saved}).data)
