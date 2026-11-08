from typing import TYPE_CHECKING

from django.core.exceptions import ObjectDoesNotExist
from django.http import FileResponse, Http404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Membership, Organization
from apps.core.permissions import IsDriver, ReadOfficeWriteOwnerOrManager, membership_of
from apps.fleet import selectors as fleet
from apps.maintenance import selectors, services

if TYPE_CHECKING:
    from apps.fleet.models import DriverDay

from .serializers import (
    FleetOdometerRowSerializer,
    MaintenanceSettingsSerializer,
    MyOdometerSerializer,
    MyOdometerWriteSerializer,
    OdometerCorrectionSerializer,
    OdometerReadingSerializer,
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
        serializer = MaintenanceSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        found = services.update_settings(
            organization=self.organization,
            actor=self.membership.user,
            max_day_km=serializer.validated_data["max_day_km"],
        )
        return Response(MaintenanceSettingsSerializer(found).data)
