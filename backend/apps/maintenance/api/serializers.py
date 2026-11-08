from typing import Any

from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.maintenance.models import MaintenanceSettings, OdometerReading


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
