from decimal import Decimal
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.models import Organization, User
from apps.fleet import selectors
from apps.fleet.models import DriverDay, Truck, TruckAssignment, TruckCondition


class DriverRefSerializer(serializers.ModelSerializer[User]):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "name")
        read_only_fields = fields

    def get_name(self, user: User) -> str:
        return f"{user.first_name} {user.last_name}".strip() or user.username


class TruckSerializer(serializers.ModelSerializer[Truck]):
    name = serializers.CharField(source="location.name", read_only=True)
    driver = DriverRefSerializer(read_only=True, allow_null=True)
    # Who has the truck today, not who usually drives it (see `selectors.drivers_of_day`).
    driver_today = serializers.SerializerMethodField()

    class Meta:
        model = Truck
        fields = (
            "id",
            "name",
            "plate",
            "driver",
            "driver_today",
            "location_id",
            "is_active",
            "condition",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(DriverRefSerializer(allow_null=True))
    def get_driver_today(self, truck: Truck) -> dict[str, Any] | None:
        drivers: dict[int, User] | None = self.context.get("drivers_today")
        if drivers is None:
            drivers = selectors.drivers_of_day(truck.organization, timezone.localdate())
        driver = drivers.get(truck.id) if truck.is_active else None
        return DriverRefSerializer(driver).data if driver else None


@extend_schema_field(OpenApiTypes.INT)
class OrganizationUserField(serializers.PrimaryKeyRelatedField[User]):
    """A user id, looked up only among members of the logged-in user's organization."""

    def get_queryset(self) -> QuerySet[User]:
        organization: Organization = self.context["organization"]
        return User.objects.filter(memberships__organization=organization).distinct()


class TruckWriteSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=100)
    plate = serializers.CharField(max_length=20)
    # A driver's user id; null leaves the truck without a driver.
    driver = OrganizationUserField(allow_null=True, required=False, default=None)
    # In service, in maintenance or broken down: a driver cannot take a truck that is not in service.
    condition = serializers.ChoiceField(choices=TruckCondition.choices, required=False)


class TruckAssignmentSerializer(serializers.ModelSerializer[TruckAssignment]):
    truck_id = serializers.IntegerField(read_only=True)
    truck_name = serializers.CharField(source="truck.location.name", read_only=True)
    plate = serializers.CharField(source="truck.plate", read_only=True)
    # Empty: the truck is left free that day.
    driver = DriverRefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = TruckAssignment
        fields = ("id", "date", "truck_id", "truck_name", "plate", "driver")
        read_only_fields = fields


class TruckAssignmentWriteSerializer(serializers.Serializer[Any]):
    truck = serializers.IntegerField()
    # Absent for a driver (always themselves); the office names the driver.
    driver = OrganizationUserField(required=False)
    # The office leaves the truck without any driver that day, whoever drives it usually.
    free = serializers.BooleanField(required=False, default=False)
    # Absent means today.
    date = serializers.DateField(required=False)


class TruckAssignmentFilterSerializer(serializers.Serializer[Any]):
    # Absent means today.
    date = serializers.DateField(required=False)


class TruckFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(
        choices=[("active", "active"), ("archived", "archived"), ("all", "all")], required=False, default="active"
    )


class TruckChoiceSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(source="location.name", read_only=True)
    plate = serializers.CharField(read_only=True)
    # Already given to another driver today.
    taken = serializers.BooleanField(read_only=True)


class DriverDaySerializer(serializers.ModelSerializer[DriverDay]):
    truck_name = serializers.CharField(source="truck.location.name", read_only=True)

    class Meta:
        model = DriverDay
        fields = ("id", "date", "truck_name", "opening_cash", "purchase_float", "ended_at")
        read_only_fields = fields


class DayFundSerializer(serializers.Serializer[Any]):
    """The cash the office set for a driver's day (D-203)."""

    opening_cash = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    purchase_float = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    set_at = serializers.DateTimeField(source="updated_at", read_only=True)
    # When the driver accepted it and started the day; null while it waits.
    accepted_at = serializers.DateTimeField(read_only=True, allow_null=True)


class DayFundDriverSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    name = serializers.SerializerMethodField()

    def get_name(self, user: Any) -> str:
        return f"{user.first_name} {user.last_name}".strip() or user.username


class DayFundRowSerializer(serializers.Serializer[Any]):
    """One driver on the office's "Fonds de caisse" list of a day."""

    driver = DayFundDriverSerializer(read_only=True)
    can_buy = serializers.BooleanField(read_only=True)
    fund = DayFundSerializer(read_only=True, allow_null=True)
    started = serializers.BooleanField(read_only=True)


class DayFundWriteSerializer(serializers.Serializer[Any]):
    driver = serializers.IntegerField(min_value=1)
    date = serializers.DateField()
    opening_cash = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=0)
    # Money for buying at the port (D-158); 0 for a driver who does not buy.
    purchase_float = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=0, required=False, default=Decimal("0.000")
    )


class PurchaseFloatSerializer(serializers.Serializer[Any]):
    purchase_float = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=0)


MAX_PINGS_PER_BATCH = 200


class LocationPingWriteSerializer(serializers.Serializer[Any]):
    # Makes a resent point store once.
    client_uuid = serializers.UUIDField()
    # The phone's clock at the fix.
    recorded_at = serializers.DateTimeField()
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180)
    accuracy = serializers.DecimalField(
        max_digits=8, decimal_places=1, min_value=0, required=False, allow_null=True, default=None
    )


class LocationPingBatchSerializer(serializers.Serializer[Any]):
    points = LocationPingWriteSerializer(many=True, allow_empty=False)

    def validate_points(self, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(points) > MAX_PINGS_PER_BATCH:
            raise serializers.ValidationError(f"{MAX_PINGS_PER_BATCH} points at most per request.")
        return points


class LocationPingSavedSerializer(serializers.Serializer[Any]):
    # How many points of the batch the server kept.
    saved = serializers.IntegerField(read_only=True)
