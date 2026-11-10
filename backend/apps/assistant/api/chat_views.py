"""The "Assistant IA" screen of the admin app (D-310): the same assistant as on WhatsApp, typed or spoken.

A question is stored and answered by the worker, as a WhatsApp message is; the screen reads the conversation again
until the answer is there. Nothing here depends on Meta.
"""

from django.conf import settings
from django.http import Http404, HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Membership
from apps.core.permissions import IsOwner, membership_of

from .. import services, speech, tasks
from ..models import Direction
from ..selectors import recent_messages, web_conversation
from .serializers import ChatMessageSerializer, ChatQuestionSerializer, ChatSerializer


class ChatView(APIView):
    # The owner only, as on WhatsApp (`access.may_use`), until the section "assistant" of the roles matrix (P12-T05).
    permission_classes = (IsOwner,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership


class ChatDetailView(ChatView):
    @extend_schema(operation_id="getAssistantChat", responses=ChatSerializer)
    def get(self, request: Request) -> Response:
        """The person's conversation with the assistant on the screen: the last 20 messages of the last 24 hours,
        oldest first. A question still waiting for its answer is the last message."""
        return Response(
            ChatSerializer(
                {
                    "enabled": settings.ASSISTANT_ENABLED,
                    "server_voice": speech.is_configured(),
                    "messages": recent_messages(web_conversation(self.membership)),
                }
            ).data
        )


class ChatQuestionView(ChatView):
    @extend_schema(operation_id="askAssistant", request=ChatQuestionSerializer, responses={201: ChatMessageSerializer})
    def post(self, request: Request) -> Response:
        """Ask the assistant a question. The answer comes a few seconds later in the conversation
        (`getAssistantChat`)."""
        serializer = ChatQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stored = services.record_web_incoming(
            membership=self.membership,
            text=serializer.validated_data["text"],
            spoken=serializer.validated_data["spoken"],
        )
        tasks.handle_message.delay(stored.pk)
        return Response(ChatMessageSerializer(stored).data, status=status.HTTP_201_CREATED)


class ChatSpeechView(ChatView):
    @extend_schema(
        operation_id="getAssistantSpeech",
        responses={(200, speech.AUDIO_TYPE): OpenApiTypes.BINARY, 404: None, 502: None},
    )
    def get(self, request: Request, message_id: int) -> HttpResponse:
        """One answer of the person's own conversation, read aloud (MP3): a Tunisian voice for an answer in Arabic
        letters, a French one otherwise. 404 when the server has no voice (the screen then uses the browser's)."""
        answer = web_conversation(self.membership).filter(pk=message_id, direction=Direction.OUT).first()
        if answer is None or not speech.is_configured() or not speech.spoken_text(answer.text):
            raise Http404
        try:
            audio = speech.synthesize(answer.text)
        except speech.SpeechError:
            return HttpResponse(status=status.HTTP_502_BAD_GATEWAY)
        response = HttpResponse(audio, content_type=speech.AUDIO_TYPE)
        # An answer never changes: the browser keeps its audio, a second listen costs nothing.
        response["Cache-Control"] = "private, max-age=86400"
        return response
