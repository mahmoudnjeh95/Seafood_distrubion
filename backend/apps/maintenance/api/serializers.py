from typing import Any

from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.maintenance.models import (
    MaintenanceRecord,
    MaintenanceSettings,
    MaintenanceType,
    OdometerReading,
)


def person_name(user: Any) -> str:
    if user is None:
        return ""
    return f"{user.first_name} {user.last_name}".strip() or user.username


@extend_schema_field(OpenApiTypes.BINARY)
class UploadedPhotoField(serializers.FileField):
    """A file sent in a multipart form: a Blob in the generated client, not a URL."""


class OdometerReadingSerializer(serializers.ModelSerializer[OdometerReading]):
    recorded_by = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()
    day_date = serializers.DateField(source="driver_day.date", read_only=True, allow_null=True)

    class Meta:
        model = OdometerReading
        fields = (
            "id",
            "truck_id",
            "km",
            "driven_km",
            "source",
            "warning",
            "note",
            "photo_url",
            "day_date",
            "recorded_by",
            "created_at",
        )
        read_only_fields = fields

    def get_recorded_by(self, reading: OdometerReading) -> str:
        return person_name(reading.recorded_by)

    def get_photo_url(self, reading: OdometerReading) -> str | None:
        if not reading.photo.name:
            return None
        return reverse("odometer-photo", args=[reading.pk])


class MyOdometerSerializer(serializers.Serializer[Any]):
    """The driver's truck's last compteur (the reference), and what was typed on today's day, if anything."""

    last_km = serializers.IntegerField(allow_null=True)
    last_at = serializers.DateTimeField(allow_null=True)
    today_km = serializers.IntegerField(allow_null=True)


class MyOdometerWriteSerializer(serializers.Serializer[Any]):
    km = serializers.IntegerField(min_value=0)
    photo = UploadedPhotoField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


class OdometerCorrectionSerializer(serializers.Serializer[Any]):
    km = serializers.IntegerField(min_value=0)
    note = serializers.CharField(max_length=300)
    photo = UploadedPhotoField(required=False)


class FleetOdometerRowSerializer(serializers.Serializer[Any]):
    """One `selectors.TruckOdometer`."""

    truck_id = serializers.IntegerField(source="truck.pk")
    name = serializers.CharField(source="truck.location.name")
    plate = serializers.CharField(source="truck.plate")
    condition = serializers.CharField(source="truck.condition")
    last = OdometerReadingSerializer(allow_null=True)
    warnings = serializers.IntegerField()


class MaintenanceSettingsSerializer(serializers.ModelSerializer[MaintenanceSettings]):
    class Meta:
        model = MaintenanceSettings
        fields = ("max_day_km",)
        # The model has a default, so a missing value would not be refused on its own.
        extra_kwargs = {"max_day_km": {"required": True}}


# ---- Maintenance types, plans and records (P10-T02, P10-T03) ----


class MaintenanceTypeSerializer(serializers.ModelSerializer[MaintenanceType]):
    class Meta:
        model = MaintenanceType
        fields = ("id", "name", "target", "every_km", "every_months", "warn_km", "warn_days", "is_active")
        read_only_fields = ("id",)


class MaintenanceTypeUpdateSerializer(serializers.ModelSerializer[MaintenanceType]):
    class Meta:
        model = MaintenanceType
        fields = ("name", "every_km", "every_months", "warn_km", "warn_days", "is_active")
        extra_kwargs = {name: {"required": False} for name in fields}


class AddedSerializer(serializers.Serializer[Any]):
    added = serializers.IntegerField()


class PlanSubjectSerializer(serializers.Serializer[Any]):
    """The truck or the cold room a plan is on."""

    id = serializers.IntegerField()
    name = serializers.CharField()


class MaintenancePlanSerializer(serializers.Serializer[Any]):
    """One `selectors.PlanStatus`: the plan and where it stands today."""

    id = serializers.IntegerField(source="plan.pk")
    type = MaintenanceTypeSerializer(source="plan.type")
    truck = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    own_every_km = serializers.IntegerField(source="plan.every_km", allow_null=True)
    own_every_months = serializers.IntegerField(source="plan.every_months", allow_null=True)
    last_done_on = serializers.DateField(source="plan.last_done_on", allow_null=True)
    last_done_km = serializers.IntegerField(source="plan.last_done_km", allow_null=True)
    every_km = serializers.IntegerField(allow_null=True)
    every_months = serializers.IntegerField(allow_null=True)
    current_km = serializers.IntegerField(allow_null=True)
    due_km = serializers.IntegerField(allow_null=True)
    km_left = serializers.IntegerField(allow_null=True)
    due_on = serializers.DateField(allow_null=True)
    days_left = serializers.IntegerField(allow_null=True)
    estimated_on = serializers.DateField(allow_null=True)
    state = serializers.ChoiceField(choices=["ok", "soon", "late", "unknown"])

    @extend_schema_field(PlanSubjectSerializer(allow_null=True))
    def get_truck(self, status: Any) -> dict[str, Any] | None:
        truck = status.plan.truck
        return None if truck is None else {"id": truck.pk, "name": truck.location.name}

    @extend_schema_field(PlanSubjectSerializer(allow_null=True))
    def get_location(self, status: Any) -> dict[str, Any] | None:
        location = status.plan.location
        return None if location is None else {"id": location.pk, "name": location.name}


class MaintenancePlanCreateSerializer(serializers.Serializer[Any]):
    type = serializers.IntegerField()
    truck = serializers.IntegerField(required=False, allow_null=True)
    location = serializers.IntegerField(required=False, allow_null=True)
    every_km = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    every_months = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=120)
    last_done_on = serializers.DateField(required=False, allow_null=True)
    last_done_km = serializers.IntegerField(required=False, allow_null=True, min_value=0)


class MaintenancePlanUpdateSerializer(serializers.Serializer[Any]):
    every_km = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    every_months = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=120)
    last_done_on = serializers.DateField(required=False, allow_null=True)
    last_done_km = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    is_active = serializers.BooleanField(required=False)


class MaintenanceRecordSerializer(serializers.ModelSerializer[MaintenanceRecord]):
    recorded_by = serializers.SerializerMethodField()
    expense_number = serializers.CharField(source="expense.number", read_only=True, allow_null=True)

    class Meta:
        model = MaintenanceRecord
        fields = (
            "id",
            "plan_id",
            "done_on",
            "km",
            "garage",
            "note",
            "cost",
            "expense_id",
            "expense_number",
            "recorded_by",
            "created_at",
        )
        read_only_fields = fields

    def get_recorded_by(self, record: MaintenanceRecord) -> str:
        return person_name(record.recorded_by)


class MaintenanceRecordWriteSerializer(serializers.Serializer[Any]):
    done_on = serializers.DateField()
    km = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    garage = serializers.CharField(required=False, allow_blank=True, max_length=150)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)
    # In DT as a string ("85.500"), checked by the service.
    cost = serializers.CharField(required=False, allow_blank=True)
    payment_method = serializers.ChoiceField(
        choices=["cash", "cheque", "transfer", "bill", "other"], required=False, default="cash"
    )
