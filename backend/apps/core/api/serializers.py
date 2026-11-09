from typing import Any

from django.conf import settings
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field, inline_serializer
from rest_framework import serializers

from apps.core import access
from apps.core.models import CustomRole, Membership, Organization, Role, User
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


LEVEL_CHOICES = [(level.value, level.value) for level in access.ALL_LEVELS]


class AccessLevelsField(serializers.DictField):
    """{section key: level} (D-306)."""

    child = serializers.ChoiceField(choices=LEVEL_CHOICES)


def role_label(membership: Membership) -> str:
    if membership.role == Role.CUSTOM and membership.custom_role is not None:
        return membership.custom_role.name
    return str(membership.get_role_display())


class SessionSerializer(serializers.Serializer[Membership]):
    """Who is logged in and what they may do: the answer of `/me` and of a successful login."""

    user = UserSerializer(read_only=True)
    organization = OrganizationSerializer(read_only=True)
    role = serializers.ChoiceField(choices=Role.choices, read_only=True)
    # The role's name to show: a custom role's own name (D-306).
    role_label = serializers.SerializerMethodField()
    # The person's level in each section (D-306): the admin app hides what is "none" and the buttons below "write".
    access = serializers.SerializerMethodField()
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

    def get_role_label(self, membership: Membership) -> str:
        return role_label(membership)

    @extend_schema_field(AccessLevelsField())
    def get_access(self, membership: Membership) -> dict[str, str]:
        return {key: str(level) for key, level in access.access_of(membership).items()}


class CustomRoleRefSerializer(serializers.ModelSerializer[CustomRole]):
    class Meta:
        model = CustomRole
        fields = ("id", "name")
        read_only_fields = fields


class MemberSerializer(serializers.ModelSerializer[Membership]):
    user = UserSerializer(read_only=True)
    custom_role = CustomRoleRefSerializer(read_only=True, allow_null=True)
    # The person's own levels, over their role's (D-306).
    access_overrides = AccessLevelsField(read_only=True)

    class Meta:
        model = Membership
        # `can_buy`: the driver may buy at the port from the phone (D-158).
        fields = ("id", "user", "role", "custom_role", "access_overrides", "is_active", "can_buy")
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
    # The role the owner made, when `role` is "custom" (D-306).
    custom_role = serializers.IntegerField(required=False, allow_null=True, default=None)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")


class MemberProfileSerializer(serializers.Serializer[Any]):
    username = serializers.CharField(max_length=150)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")


class MemberRoleSerializer(serializers.Serializer[Any]):
    role = serializers.ChoiceField(choices=Role.choices)
    # The role the owner made, when `role` is "custom" (D-306).
    custom_role = serializers.IntegerField(required=False, allow_null=True, default=None)


# ---- Custom roles and each person's own levels (D-306) ----


class AccessSectionSerializer(serializers.Serializer[Any]):
    key = serializers.CharField()
    title = serializers.CharField()
    group = serializers.CharField()
    # The levels this section offers, lowest first.
    levels = serializers.ListField(child=serializers.ChoiceField(choices=LEVEL_CHOICES))
    # The level of each built-in role there.
    defaults = AccessLevelsField()


class CustomRoleSerializer(serializers.ModelSerializer[CustomRole]):
    access = AccessLevelsField(read_only=True)
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = CustomRole
        fields = ("id", "name", "access", "member_count")
        read_only_fields = fields

    def get_member_count(self, role: CustomRole) -> int:
        return role.memberships.count()


class CustomRoleWriteSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=60)
    access = AccessLevelsField()


class MemberAccessSerializer(serializers.Serializer[Any]):
    # The sections where this person has their own level; the others follow their role.
    overrides = AccessLevelsField()


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
    # D-283: the documents with a draft step have a draft prefix (empty: none) and a next provisional reference.
    has_draft = serializers.BooleanField()
    draft_prefix = serializers.CharField(allow_blank=True)
    next_draft_number = serializers.CharField(allow_blank=True)


class NumberPrefixRowSerializer(serializers.Serializer[Any]):
    kind = serializers.CharField(max_length=30)
    # Checked by the service (1 to 6 capitals or digits, unique), so the errors name the row.
    prefix = serializers.CharField(max_length=6, allow_blank=True)
    # Only for the kinds with a draft step (D-283); empty: drafts read "BROUILLON-…". Absent: unchanged.
    draft_prefix = serializers.CharField(max_length=6, allow_blank=True, required=False)


class NumberingWriteSerializer(serializers.Serializer[Any]):
    prefixes = NumberPrefixRowSerializer(many=True)
