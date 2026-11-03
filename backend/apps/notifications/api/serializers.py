from typing import Any

from rest_framework import serializers

from ..models import Notification


class NotificationSerializer(serializers.ModelSerializer[Notification]):
    params = serializers.DictField(child=serializers.CharField(allow_blank=True))
    read = serializers.BooleanField()

    class Meta:
        model = Notification
        fields = ("id", "kind", "params", "link", "created_at", "read")


class NotificationListSerializer(serializers.Serializer[Any]):
    unread = serializers.IntegerField()
    results = NotificationSerializer(many=True)


class MarkReadSerializer(serializers.Serializer[Any]):
    """Either the ids seen, or `all` for everything shown."""

    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, max_length=200)
    all = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("all") and not attrs.get("ids"):
            raise serializers.ValidationError("Indiquez les notifications lues, ou toutes.")
        return attrs


class UnreadSerializer(serializers.Serializer[Any]):
    unread = serializers.IntegerField()


class RecipientSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(source="user_id", read_only=True)
    name = serializers.SerializerMethodField()

    def get_name(self, membership: Any) -> str:
        user = membership.user
        return f"{user.first_name} {user.last_name}".strip() or str(user.username)


class PaymentOrderNoticeSerializer(serializers.Serializer[Any]):
    # The person told: an owner or a manager (the people `listNoticeRecipients` gives).
    recipient = serializers.IntegerField(min_value=1)
