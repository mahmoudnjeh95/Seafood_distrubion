from collections.abc import Sequence
from typing import TYPE_CHECKING

from django.core.exceptions import ObjectDoesNotExist
from django.http import FileResponse, Http404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import exceptions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Membership, Organization
from apps.core.permissions import IsDriver, IsOwner, ReadOfficeWriteOwnerOrManager, membership_of
from apps.fleet import selectors as fleet
from apps.hr import selectors as hr
from apps.inventory import selectors as inventory
from apps.maintenance import selectors, services

if TYPE_CHECKING:
    from apps.fleet.models import DriverDay, Truck
    from apps.maintenance.models import MaintenancePlan

from .serializers import (
    AddedSerializer,
    AlertSerializer,
    FleetOdometerRowSerializer,
    MaintenancePlanCreateSerializer,
    MaintenancePlanSerializer,
    MaintenancePlanUpdateSerializer,
    MaintenanceRecordSerializer,
    MaintenanceRecordWriteSerializer,
    MaintenanceSettingsSerializer,
    MaintenanceTypeSerializer,
    MaintenanceTypeUpdateSerializer,
    MyOdometerSerializer,
    MyOdometerWriteSerializer,
    OdometerCorrectionSerializer,
    OdometerReadingSerializer,
    PaperSerializer,
    PaperStatusSerializer,
    PaperWriteSerializer,
    TruckDayAllowanceSerializer,
)

# The last readings of a truck shown on its screen.
TRUCK_READINGS_SHOWN = 100


# Base of the office's maintenance views: everyone in the office reads, owners and managers write (D-295).
# A comment, not a docstring: a docstring would become the description of every endpoint in the schema.
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


class MyOdometerView(APIView):
    permission_classes = (IsDriver,)
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def _day(self) -> tuple[Membership, "DriverDay"]:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        day = fleet.driver_day_of(membership)
        if day is None:
            raise Http404
        return membership, day

    @extend_schema(operation_id="getMyOdometer", responses=MyOdometerSerializer)
    def get(self, request: Request) -> Response:
        """The compteur of the driver's truck: its last reading, and the one typed on today's day. 404: no day."""
        membership, day = self._day()
        last = selectors.last_reading(membership.organization, truck_id=day.truck_id)
        today = selectors.reading_of_day(day)
        data = {
            "last_km": last.km if last is not None else None,
            "last_at": last.created_at if last is not None else None,
            "today_km": today.km if today is not None else None,
        }
        return Response(MyOdometerSerializer(data).data)

    @extend_schema(
        operation_id="recordMyOdometer",
        request={"multipart/form-data": MyOdometerWriteSerializer},
        responses={201: OdometerReadingSerializer},
    )
    def post(self, request: Request) -> Response:
        """Record the compteur when sending the day (P10-T01), with an optional photo of the dashboard. Refused below
        the truck's last reading and on a day already sent. 404: no day today."""
        serializer = MyOdometerWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership, day = self._day()
        reading = services.record_driver_reading(
            driver_day=day,
            actor=membership.user,
            km=serializer.validated_data["km"],
            photo=serializer.validated_data.get("photo"),
            note=serializer.validated_data.get("note", ""),
        )
        return Response(OdometerReadingSerializer(reading).data, status=status.HTTP_201_CREATED)


class FleetOdometerView(OfficeView):
    @extend_schema(operation_id="listFleetOdometer", responses=FleetOdometerRowSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Each active truck with its last compteur and how many of its readings carry a warning."""
        rows = selectors.fleet_odometer(self.organization)
        return Response(FleetOdometerRowSerializer(rows, many=True).data)


class TruckOdometerView(OfficeView):
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def _truck_id(self, truck_id: int) -> int:
        try:
            return fleet.truck_of(self.organization, truck_id).pk
        except ObjectDoesNotExist:
            raise Http404 from None

    @extend_schema(operation_id="listTruckOdometer", responses=OdometerReadingSerializer(many=True))
    def get(self, request: Request, truck_id: int) -> Response:
        """The truck's compteur readings, the latest first (the last 100)."""
        readings = selectors.readings_of_truck(self.organization, truck_id=self._truck_id(truck_id))
        return Response(OdometerReadingSerializer(readings[:TRUCK_READINGS_SHOWN], many=True).data)

    @extend_schema(
        operation_id="correctTruckOdometer",
        request={"multipart/form-data": OdometerCorrectionSerializer},
        responses={201: OdometerReadingSerializer},
    )
    def post(self, request: Request, truck_id: int) -> Response:
        """The office sets the truck's compteur, with a reason; it may be lower than the last reading."""
        serializer = OdometerCorrectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        truck = fleet.truck_of(self.organization, self._truck_id(truck_id))
        reading = services.correct_reading(
            organization=self.organization,
            truck=truck,
            actor=self.membership.user,
            km=serializer.validated_data["km"],
            note=serializer.validated_data["note"],
            photo=serializer.validated_data.get("photo"),
        )
        return Response(OdometerReadingSerializer(reading).data, status=status.HTTP_201_CREATED)


class OdometerPhotoView(OfficeView):
    # Read by an <img> tag, not by the generated client: kept out of the API contract.
    @extend_schema(exclude=True)
    def get(self, request: Request, reading_id: int) -> FileResponse:
        try:
            reading = selectors.reading_of(self.organization, reading_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        if not reading.photo:
            raise Http404
        response = FileResponse(reading.photo.open("rb"), content_type="image/webp")
        # A reading's photo never changes.
        response["Cache-Control"] = "private, max-age=31536000, immutable"
        return response


class MaintenanceSettingsView(OfficeView):
    @extend_schema(operation_id="getMaintenanceSettings", responses=MaintenanceSettingsSerializer)
    def get(self, request: Request) -> Response:
        """The maintenance settings (Paramètres entretien)."""
        return Response(MaintenanceSettingsSerializer(selectors.settings_of(self.organization)).data)

    @extend_schema(
        operation_id="updateMaintenanceSettings",
        request=MaintenanceSettingsSerializer,
        responses={200: MaintenanceSettingsSerializer, 400: OpenApiResponse(description="Out of range")},
    )
    def patch(self, request: Request) -> Response:
        """Change the maintenance settings. Owners and managers."""
        serializer = MaintenanceSettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "max_day_km" in data:
            services.update_settings(
                organization=self.organization, actor=self.membership.user, max_day_km=data["max_day_km"]
            )
        if "paper_warn_days" in data:
            services.update_paper_warnings(
                organization=self.organization, actor=self.membership.user, days=data["paper_warn_days"]
            )
        return Response(MaintenanceSettingsSerializer(selectors.settings_of(self.organization)).data)


# ---- Maintenance types, plans and records (P10-T02, P10-T03) ----


class MaintenanceTypeListView(OfficeView):
    @extend_schema(
        operation_id="listMaintenanceTypes",
        parameters=[OpenApiParameter("target", str, required=False, enum=["truck", "frigo", "cold_room"])],
        responses=MaintenanceTypeSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """The kinds of maintenance with their intervals (Paramètres entretien), archived ones included."""
        target = request.query_params.get("target") or None
        return Response(MaintenanceTypeSerializer(selectors.types_of(self.organization, target=target), many=True).data)

    @extend_schema(
        operation_id="createMaintenanceType",
        request=MaintenanceTypeSerializer,
        responses={201: MaintenanceTypeSerializer},
    )
    def post(self, request: Request) -> Response:
        """A new kind of maintenance: every X km and/or Y months, warned so many km or days before."""
        serializer = MaintenanceTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        kind = services.create_type(
            organization=self.organization,
            actor=self.membership.user,
            name=data["name"],
            target=data.get("target", "truck"),
            every_km=data.get("every_km"),
            every_months=data.get("every_months"),
            warn_km=data.get("warn_km", 1000),
            warn_days=data.get("warn_days", 15),
        )
        return Response(MaintenanceTypeSerializer(kind).data, status=status.HTTP_201_CREATED)


class MaintenanceTypeDefaultsView(OfficeView):
    @extend_schema(operation_id="addDefaultMaintenanceTypes", request=None, responses=AddedSerializer)
    def post(self, request: Request) -> Response:
        """Add the suggested kinds of maintenance the organization does not have yet."""
        added = services.add_default_types(organization=self.organization, actor=self.membership.user)
        return Response(AddedSerializer({"added": added}).data)


class MaintenanceTypeDetailView(OfficeView):
    @extend_schema(
        operation_id="updateMaintenanceType",
        request=MaintenanceTypeUpdateSerializer,
        responses=MaintenanceTypeSerializer,
    )
    def patch(self, request: Request, type_id: int) -> Response:
        """Change a kind of maintenance, or archive it (`is_active` false). Its target never changes."""
        try:
            kind = selectors.type_of(self.organization, type_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        serializer = MaintenanceTypeUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        kind = services.update_type(kind=kind, actor=self.membership.user, **serializer.validated_data)
        return Response(MaintenanceTypeSerializer(kind).data)


def _plan_answer(organization: Organization, plan_id: int, status_code: int = status.HTTP_200_OK) -> Response:
    plan = selectors.plan_of(organization, plan_id)
    found = selectors.plan_statuses(organization, truck_id=plan.truck_id, location_id=plan.location_id)
    current = next((row for row in found if row.plan.pk == plan_id), None)
    if current is None:  # a stopped plan is not in the list: worked out on its own
        current = selectors.plan_status(plan, current_km=None, pace=None)
    return Response(MaintenancePlanSerializer(current).data, status=status_code)


class MaintenancePlanListView(OfficeView):
    @extend_schema(
        operation_id="listMaintenancePlans",
        parameters=[
            OpenApiParameter("truck", int, required=False),
            OpenApiParameter("location", int, required=False),
        ],
        responses=MaintenancePlanSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """The maintenance followed, with where each one stands today (ok, bientôt, en retard, à renseigner)."""
        truck = request.query_params.get("truck")
        location = request.query_params.get("location")
        rows = selectors.plan_statuses(
            self.organization,
            truck_id=int(truck) if truck and truck.isdigit() else None,
            location_id=int(location) if location and location.isdigit() else None,
        )
        return Response(MaintenancePlanSerializer(rows, many=True).data)

    @extend_schema(
        operation_id="createMaintenancePlan",
        request=MaintenancePlanCreateSerializer,
        responses={201: MaintenancePlanSerializer},
    )
    def post(self, request: Request) -> Response:
        """Follow a kind of maintenance on a truck (or its frigo unit) or a cold room."""
        serializer = MaintenancePlanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            kind = selectors.type_of(self.organization, data["type"])
            truck = fleet.truck_of(self.organization, data["truck"]) if data.get("truck") else None
            location = inventory.location_of(self.organization, data["location"]) if data.get("location") else None
        except ObjectDoesNotExist:
            raise exceptions.ValidationError({"type": _("Entretien, camion ou chambre froide inconnu.")}) from None
        plan = services.create_plan(
            organization=self.organization,
            actor=self.membership.user,
            kind=kind,
            truck=truck,
            location=location,
            every_km=data.get("every_km"),
            every_months=data.get("every_months"),
            last_done_on=data.get("last_done_on"),
            last_done_km=data.get("last_done_km"),
        )
        return _plan_answer(self.organization, plan.pk, status.HTTP_201_CREATED)


class MaintenancePlanView(OfficeView):
    def plan(self, plan_id: int) -> "MaintenancePlan":
        try:
            return selectors.plan_of(self.organization, plan_id)
        except ObjectDoesNotExist:
            raise Http404 from None


class MaintenancePlanDetailView(MaintenancePlanView):
    @extend_schema(
        operation_id="updateMaintenancePlan",
        request=MaintenancePlanUpdateSerializer,
        responses=MaintenancePlanSerializer,
    )
    def patch(self, request: Request, plan_id: int) -> Response:
        """Change the plan's own interval or when it was last done, or stop following it (`is_active` false)."""
        serializer = MaintenancePlanUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_plan(plan=self.plan(plan_id), actor=self.membership.user, **serializer.validated_data)
        return _plan_answer(self.organization, plan_id)


class MaintenanceRecordListView(MaintenancePlanView):
    @extend_schema(operation_id="listMaintenanceRecords", responses=MaintenanceRecordSerializer(many=True))
    def get(self, request: Request, plan_id: int) -> Response:
        """The jobs done on the plan, the latest first."""
        records = selectors.records_of_plan(self.organization, plan_id=self.plan(plan_id).pk)
        return Response(MaintenanceRecordSerializer(records, many=True).data)

    @extend_schema(
        operation_id="recordMaintenance",
        request=MaintenanceRecordWriteSerializer,
        responses={201: MaintenanceRecordSerializer},
    )
    def post(self, request: Request, plan_id: int) -> Response:
        """ "Entretien effectué": the next one is due from here. A cost becomes an approved expense of the general
        overhead (not charged to the lots)."""
        serializer = MaintenanceRecordWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        record = services.record_maintenance(
            plan=self.plan(plan_id),
            actor=self.membership.user,
            done_on=data["done_on"],
            km=data.get("km"),
            garage=data.get("garage", ""),
            note=data.get("note", ""),
            cost=data.get("cost") or "0",
            payment_method=data.get("payment_method", "cash"),
        )
        return Response(MaintenanceRecordSerializer(record).data, status=status.HTTP_201_CREATED)


# ---- Papers with expiry dates (P10-T04) ----


class PaperBoardView(OfficeView):
    @extend_schema(operation_id="listPaperBoard", responses=PaperStatusSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Each active truck's and person's papers, the current one of each kind and where it stands."""
        return Response(PaperStatusSerializer(selectors.paper_board(self.organization), many=True).data)


class PaperListView(OfficeView):
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    @extend_schema(
        operation_id="listPapers",
        parameters=[OpenApiParameter("truck", int, required=False), OpenApiParameter("employee", int, required=False)],
        responses=PaperSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Every paper typed for a truck or a person (renewals included), the one valid the longest first."""
        truck = request.query_params.get("truck", "")
        employee = request.query_params.get("employee", "")
        papers = selectors.papers_of(
            self.organization,
            truck_id=int(truck) if truck.isdigit() else None,
            employee_id=int(employee) if employee.isdigit() else None,
        )
        return Response(PaperSerializer(papers[:100], many=True).data)

    @extend_schema(
        operation_id="recordPaper",
        request={"multipart/form-data": PaperWriteSerializer},
        responses={201: PaperSerializer},
    )
    def post(self, request: Request) -> Response:
        """A paper issued or renewed, with its scan (photo or PDF) and its cost (an approved expense)."""
        serializer = PaperWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            truck = fleet.truck_of(self.organization, data["truck"]) if data.get("truck") else None
            employee = hr.employee_of(self.organization, data["employee"]) if data.get("employee") else None
        except ObjectDoesNotExist:
            raise exceptions.ValidationError({"truck": _("Camion ou personne inconnu.")}) from None
        paper = services.record_paper(
            organization=self.organization,
            actor=self.membership.user,
            kind=data["kind"],
            expires_on=data["expires_on"],
            truck=truck,
            employee=employee,
            number=data.get("number", ""),
            issuer=data.get("issuer", ""),
            issued_on=data.get("issued_on"),
            cost=data.get("cost") or "0",
            payment_method=data.get("payment_method", "cash"),
            note=data.get("note", ""),
            scan=data.get("scan"),
        )
        return Response(PaperSerializer(paper).data, status=status.HTTP_201_CREATED)


class PaperScanView(OfficeView):
    # Read by a link, not by the generated client: kept out of the API contract.
    @extend_schema(exclude=True)
    def get(self, request: Request, paper_id: int) -> FileResponse:
        try:
            paper = selectors.paper_of(self.organization, paper_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        if not paper.scan:
            raise Http404
        kind = "application/pdf" if (paper.scan.name or "").endswith(".pdf") else "image/webp"
        response = FileResponse(paper.scan.open("rb"), content_type=kind)
        response["Cache-Control"] = "private, max-age=31536000, immutable"
        return response


class TruckDayAllowanceView(OfficeView):
    def get_permissions(self) -> Sequence[BasePermission]:
        # Only the owner lets a truck out with an expired paper (owner answer 5b).
        if self.request.method == "POST":
            return [IsOwner()]
        return [ReadOfficeWriteOwnerOrManager()]

    def _truck(self, truck_id: int) -> "Truck":
        try:
            return fleet.truck_of(self.organization, truck_id)
        except ObjectDoesNotExist:
            raise Http404 from None

    @extend_schema(operation_id="listTruckDayAllowances", responses=TruckDayAllowanceSerializer(many=True))
    def get(self, request: Request, truck_id: int) -> Response:
        """The days the owner let the truck out although its assurance or visite technique had expired."""
        rows = selectors.allowances_of(self.organization, truck_id=self._truck(truck_id).pk)
        return Response(TruckDayAllowanceSerializer(rows, many=True).data)

    @extend_schema(
        operation_id="allowTruckDay",
        request=TruckDayAllowanceSerializer,
        responses={201: TruckDayAllowanceSerializer},
    )
    def post(self, request: Request, truck_id: int) -> Response:
        """The owner lets the truck out that day, with the reason. Owner only."""
        serializer = TruckDayAllowanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allowance = services.allow_truck_day(
            organization=self.organization,
            actor=self.membership.user,
            truck=self._truck(truck_id),
            date=serializer.validated_data["date"],
            reason=serializer.validated_data["reason"],
        )
        return Response(TruckDayAllowanceSerializer(allowance).data, status=status.HTTP_201_CREATED)


# ---- Warnings everywhere (P10-T05) ----


class FleetAlertsView(OfficeView):
    @extend_schema(operation_id="listFleetAlerts", responses=AlertSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Every maintenance and paper soon (orange) or late (red), the red ones first: the badges on the trucks and
        the "Flotte & conformité" overview."""
        return Response(AlertSerializer(selectors.alerts_of(self.organization), many=True).data)


class MyAlertsView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="listMyAlerts", responses=AlertSerializer(many=True))
    def get(self, request: Request) -> Response:
        """What the driver sees on the phone: his truck's maintenance and papers due, and his own papers."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        truck = fleet.truck_of_driver(membership)
        rows = selectors.driver_alerts(
            membership.organization, user_id=membership.user_id, truck_id=truck.pk if truck is not None else None
        )
        return Response(AlertSerializer(rows, many=True).data)
