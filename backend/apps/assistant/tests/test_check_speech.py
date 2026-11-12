"""`manage.py check_speech` (D-323): the Azure key checked by reading a sentence, then recognising it."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.assistant import speech


def test_without_the_key_it_says_what_is_missing(settings):
    settings.AZURE_SPEECH_KEY = ""
    with pytest.raises(CommandError, match="AZURE_SPEECH_KEY"):
        call_command("check_speech")


def test_the_voice_is_read_then_heard(settings, monkeypatch):
    settings.AZURE_SPEECH_KEY, settings.AZURE_SPEECH_REGION = "key", "francecentral"
    calls = []

    def synthesize(text, *, audio_format):
        calls.append(("voice", text, audio_format))
        return b"RIFF-wav"

    def transcribe(audio, language):
        calls.append(("heard", audio, language))
        return "شنوة عندي في الفريجيدار؟"

    monkeypatch.setattr(speech, "synthesize", synthesize)
    monkeypatch.setattr(speech, "transcribe", transcribe)
    out = StringIO()
    call_command("check_speech", stdout=out)
    assert calls[0][2] == speech.WAV_OUTPUT
    assert calls[1] == ("heard", b"RIFF-wav", "ar-TN")
    assert "ready" in out.getvalue()


def test_a_refused_key_is_a_clear_error(settings, monkeypatch):
    settings.AZURE_SPEECH_KEY, settings.AZURE_SPEECH_REGION = "bad", "francecentral"

    def refuse(text, *, audio_format):
        raise speech.SpeechError("401: denied")

    monkeypatch.setattr(speech, "synthesize", refuse)
    with pytest.raises(CommandError, match="401"):
        call_command("check_speech")


def test_silence_from_the_recognition_is_an_error(settings, monkeypatch):
    settings.AZURE_SPEECH_KEY, settings.AZURE_SPEECH_REGION = "key", "francecentral"
    monkeypatch.setattr(speech, "synthesize", lambda text, *, audio_format: b"RIFF-wav")
    monkeypatch.setattr(speech, "transcribe", lambda audio, language: "")
    with pytest.raises(CommandError, match="heard nothing"):
        call_command("check_speech")
