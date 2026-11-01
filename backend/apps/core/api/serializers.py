from typing import Any

from django.conf import settings
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field, inline_serializer
from rest_framework import serializers

from apps.core.models import Membership, Organization, Role, User
from apps.core.session import TruckRef, truck_of


class LoginSerializer(serializers.Serializer[Any]):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)


class LanguageSerializer(serializers.Serializer[Any]):
    language = serializers.ChoiceField(choices=settings.LANGUAGES)


class UserSerializer(serializers.ModelSerializer[User]):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name", "email", "language", "avatar_url")
        read_only_fields = fields

    def get_avatar_url(self, user: User) -> str | None:
        if not user.avatar.name:
            return None
        version = user.avatar.name.rsplit("/", 1)[-1].split(".", 1)[0]
        return f"{reverse('user-avatar', args=[user.pk])}?v={version}"


class OrganizationSerializer(serializers.ModelSerializer[Organization]):
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ("id", "name", "logo_url")
        read_only_fields = fields

    def get_logo_url(self, organization: Organization) -> str | None:
        if not organization.logo.name:
            return None
        version = organization.logo.name.rsplit("/", 1)[-1].split(".", 1)[0]
        return f"{reverse('organization-logo', args=[organization.pk])}?v={version}"


class SessionSerializer(serializers.Serializer[Membership]):
    """Who is logged in and what they may do: the answer of `/me` and of a successful login."""

    user = UserSerializer(read_only=True)
    organization = OrganizationSerializer(read_only=True)
    role = serializers.ChoiceField(choices=Role.choices, read_only=True)
    # The owner lets this driver buy at the port from the phone (D-158).
    can_buy = serializers.BooleanField(read_only=True)
    # The driver's own truck; null for other roles and for a driver without a truck.
    truck = serializers.SerializerMethodField()

    @extend_schema_field(
        inline_serializer(
            "TruckRef",
            fields={
                "id": serializers.IntegerField(),
                "name": serializers.CharField(),
                "plate": serializers.CharField(),
                "location_id": serializers.IntegerField(),
            },
            allow_null=True,
        )
    )
    def get_truck(self, membership: Membership) -> TruckRef | None:
        return truck_of(membership)


class MemberSerializer(serializers.ModelSerializer[Membership]):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Membership
        # `can_buy`: the driver may buy at the port from the phone (D-158).
        fields = ("id", "user", "role", "is_active", "can_buy")
        read_only_fields = fields


# ---- Paramètres: company profile and user management (owner request, D-123) ----


@extend_schema_field(OpenApiTypes.BINARY)
class UploadedPhotoField(serializers.FileField):
    """A file sent in a multipart form: a Blob in the generated client, not a URL."""


class ProfilePhotoUploadSerializer(serializers.Serializer[Any]):
    photo = UploadedPhotoField()


class MemberCreateSerializer(serializers.Serializer[Any]):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    role = serializers.ChoiceField(choices=Role.choices)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")


class MemberProfileSerializer(serializers.Serializer[Any]):
    username = serializers.CharField(max_length=150)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")


class MemberRoleSerializer(serializers.Serializer[Any]):
    role = serializers.ChoiceField(choices=Role.choices)


class MemberCanBuySerializer(serializers.Serializer[Any]):
    can_buy = serializers.BooleanField()


class MemberPasswordResetSerializer(serializers.Serializer[Any]):
    new_password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)


class ChangePasswordSerializer(serializers.Serializer[Any]):
    old_password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)


class UpdateProfileSerializer(serializers.Serializer[Any]):
    first_name = serializers.CharField(max_length=150, allow_blank=True)
    last_name = serializers.CharField(max_length=150, allow_blank=True)


class NumberLineSerializer(serializers.Serializer[Any]):
    kind = serializers.CharField()
    # "title" rather than "label": DRF fields already have a label.
    title = serializers.CharField()
    group = serializers.CharField()
    prefix = serializers.CharField()
    default_prefix = serializers.CharField()
    yearly = serializers.BooleanField()
    # The number the next record of this kind will get, e.g. "FA-2026-0008".
    next_number = serializers.CharField()


class NumberPrefixRowSerializer(serializers.Serializer[Any]):
    kind = serializers.CharField(max_length=30)
    # Checked by the service (1 to 6 capitals or digits, unique), so the errors name the row.
    prefix = serializers.CharField(max_length=6, allow_blank=True)


class NumberingWriteSerializer(serializers.Serializer[Any]):
    prefixes = NumberPrefixRowSerializer(many=True)
