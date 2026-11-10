"""The assistant's voice on the "Assistant IA" screen (D-314): an answer read aloud by Azure AI Speech.

Azure has Tunisian voices (`ar-TN-ReemNeural`, `ar-TN-HediNeural`); a browser other than Edge has none. Without
the Azure key the screen falls back to the browser's own voice.
"""

import re
from xml.sax.saxutils import escape

import httpx
from django.conf import settings

# An answer is a few lines; a long one is cut so one click never reads (and bills) a whole page.
MAX_CHARACTERS = 1500
AUDIO_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
AUDIO_TYPE = "audio/mpeg"
_ARABIC = re.compile(r"[؀-ۿ]")
# What a voice should not read out: emphasis marks and list bullets of a written answer.
_MARKS = re.compile(r"[*_`#]+|^\s*[-•]\s+", re.MULTILINE)


class SpeechError(Exception):
    """Azure refused the text or could not be reached."""


def is_configured() -> bool:
    return bool(settings.AZURE_SPEECH_KEY and settings.AZURE_SPEECH_REGION)


def voice_for(text: str) -> tuple[str, str]:
    """(language, voice) that reads `text`: the Tunisian voice for Arabic letters, the French one otherwise."""
    if _ARABIC.search(text):
        return "ar-TN", settings.ASSISTANT_VOICE_AR
    return "fr-FR", settings.ASSISTANT_VOICE_FR


def spoken_text(text: str) -> str:
    return _MARKS.sub("", text).strip()[:MAX_CHARACTERS]


def ssml(text: str) -> str:
    language, voice = voice_for(text)
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{language}">'
        f'<voice name="{escape(voice)}">{escape(spoken_text(text))}</voice></speak>'
    )


def synthesize(text: str, *, transport: httpx.BaseTransport | None = None) -> bytes:
    """`text` as MP3 audio."""
    url = f"https://{settings.AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": settings.AZURE_SPEECH_KEY,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": AUDIO_FORMAT,
        "User-Agent": "frutti-assistant",
    }
    try:
        with httpx.Client(transport=transport, timeout=20) as http:
            response = http.post(url, content=ssml(text).encode(), headers=headers)
    except httpx.HTTPError as error:
        raise SpeechError(repr(error)) from error
    if response.status_code >= 300:
        raise SpeechError(f"{response.status_code}: {response.text[:300]}")
    return response.content
