"""Tests asserting TTS configuration requirements and failure modes."""
import pytest

from pgai_challenge.config import Settings
from pgai_challenge.personas import get_scenario
from pgai_challenge.worker import build_tts


def _make_settings(**overrides):
    base = dict(
        twilio_account_sid="ACxxx",
        twilio_auth_token="tok",
        caller_number="+13334445555",
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="key",
        livekit_api_secret="sec",
        sip_host="test.sip.livekit.cloud",
        deepgram_api_key="dg",
        public_base_url="https://example.ngrok-free.app",
    )
    base.update(overrides)
    return Settings(**base)


def test_gemini_only_raises_runtime_error_for_tts():
    scenario = get_scenario("book_physical")
    settings = _make_settings(gemini_api_key="AIzaSyTestKey")
    with pytest.raises(RuntimeError) as exc_info:
        build_tts(settings, scenario)
    msg = str(exc_info.value)
    assert "No TTS provider configured" in msg
    assert "CARTESIA_API_KEY" in msg
    assert "GEMINI_API_KEY does NOT provide TTS" in msg


def test_cartesia_configured_builds_cartesia_tts():
    scenario = get_scenario("book_physical")
    settings = _make_settings(
        gemini_api_key="AIzaSyTestKey", cartesia_api_key="cart_test_key"
    )
    tts = build_tts(settings, scenario)
    assert tts is not None
    assert "cartesia" in tts.__class__.__module__


def test_openai_configured_builds_openai_tts():
    scenario = get_scenario("book_physical")
    settings = _make_settings(
        gemini_api_key="AIzaSyTestKey", openai_api_key="sk-test-key"
    )
    tts = build_tts(settings, scenario)
    assert tts is not None
    assert "openai" in tts.__class__.__module__
