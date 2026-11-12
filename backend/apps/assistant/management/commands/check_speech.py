"""Check the Azure AI Speech key of the "Assistant IA" screen (D-314, D-323) once it is in `.env`.

The Tunisian voice reads a sentence, then the recognition listens to that recording: both halves of the screen's
voice, for a few characters and seconds of the free tier.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.assistant import speech

SENTENCE = "شنوة عندي في الفريجيدار؟"


class Command(BaseCommand):
    help = "Check the Azure Speech key: the Tunisian voice reads a sentence, then the recognition hears it."

    def handle(self, *args: object, **options: object) -> None:
        if not speech.is_configured():
            raise CommandError("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION are not set in .env.")
        region = settings.AZURE_SPEECH_REGION
        try:
            audio = speech.synthesize(SENTENCE, audio_format=speech.WAV_OUTPUT)
        except speech.SpeechError as error:
            raise CommandError(f"The voice failed (key, region {region}?): {error}") from error
        self.stdout.write(f"Voice ({settings.ASSISTANT_VOICE_AR}): OK, {len(audio)} bytes.")
        try:
            heard = speech.transcribe(audio, "ar-TN")
        except speech.SpeechError as error:
            raise CommandError(f"The recognition failed: {error}") from error
        if not heard:
            raise CommandError("The recognition heard nothing in the voice's own recording.")
        self.stdout.write(f"Recognition (ar-TN): OK, heard « {heard} ».")
        self.stdout.write(self.style.SUCCESS("Azure Speech is ready: the screen uses it on the next page load."))
