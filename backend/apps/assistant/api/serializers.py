from rest_framework import serializers

from ..models import AssistantMessage, Direction

MAX_QUESTION = 2000


class ChatMessageSerializer(serializers.ModelSerializer[AssistantMessage]):
    direction = serializers.ChoiceField(choices=Direction.choices)

    class Meta:
        model = AssistantMessage
        fields = ("id", "direction", "text", "spoken", "created_at")
        read_only_fields = fields


class ChatSerializer(serializers.Serializer[dict[str, object]]):
    """The "Assistant IA" screen: whether the assistant is on, and the conversation of the last 24 hours."""

    enabled = serializers.BooleanField()
    # The server can read an answer aloud with a Tunisian voice (Azure); otherwise the browser's own voice.
    server_voice = serializers.BooleanField()
    messages = ChatMessageSerializer(many=True)


class ChatQuestionSerializer(serializers.Serializer[dict[str, object]]):
    text = serializers.CharField(max_length=MAX_QUESTION, trim_whitespace=True)
    # Dictated, or the answer will be read aloud: the answer is then written to be spoken.
    spoken = serializers.BooleanField(default=False)


class ChatDictationSerializer(serializers.Serializer[dict[str, object]]):
    """The question as Azure heard it; empty when no speech was heard."""

    text = serializers.CharField(allow_blank=True)
