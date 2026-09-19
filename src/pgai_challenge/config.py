"""Configuration and safety guardrails.

The single most important rule of this project: we ONLY ever dial
Pretty Good AI's assessment line. The guardrail is checked immediately
before every outbound call, independent of any environment values.
"""
import os
from dataclasses import dataclass, field

ASSESSMENT_NUMBER = "+18054398008"
"""Pretty Good AI's assessment line. The ONLY number this project will ever dial."""

ROOM_NAME = "pgai-test"
"""Fixed LiveKit room every test call is routed into (sequential calls)."""

MAX_TURNS_DEFAULT = 12
MAX_CALL_SECONDS = 240  # hard stop per call: 4 minutes


class UnsafeDialError(ValueError):
    """Raised when code attempts to dial anything other than the assessment line."""


def assert_safe_to_dial(number: str) -> None:
    """Hard guardrail: only the assessment line may ever be dialed."""
    if number != ASSESSMENT_NUMBER:
        raise UnsafeDialError(
            f"Refusing to dial {number!r}: this project may only call "
            f"the assessment line {ASSESSMENT_NUMBER}."
        )


@dataclass
class Settings:
    # Twilio: PSTN carrier + call recording (dumb pipe, no conversational logic)
    twilio_account_sid: str
    twilio_auth_token: str
    caller_number: str  # your single Twilio number, E.164, used for ALL test calls
    # LiveKit Cloud: runs the actual voice agent (pipeline mode)
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    # Per-project SIP endpoint host, e.g. abc123.sip.livekit.cloud
    # (LiveKit Cloud -> Telephony -> SIP). Required for the Twilio bridge.
    sip_host: str
    sip_trunk_user: str = ""  # inbound SIP trunk auth (dashboard), if required
    sip_trunk_password: str = ""
    # Pipeline providers (separate STT / LLM / TTS - no realtime models)
    deepgram_api_key: str = ""
    openai_api_key: str = ""
    cartesia_api_key: str = ""  # optional; falls back to OpenAI TTS if empty
    # Public HTTPS base URL of the Twilio webhook server (ngrok), no trailing slash
    public_base_url: str = ""
    # Model choices
    llm_model: str = "gpt-4o-mini"
    analyzer_model: str = "gpt-4o-mini"
    tts_voice: str = ""  # provider-specific voice id; empty = plugin default
    max_turns: int = MAX_TURNS_DEFAULT
    max_call_seconds: int = MAX_CALL_SECONDS


def load_settings() -> Settings:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass  # dotenv is optional; env vars can be exported directly

    def req(name: str) -> str:
        value = os.environ.get(name, "").strip()
        if not value:
            raise RuntimeError(
                f"Missing required environment variable {name}. "
                "Copy .env.example to .env and fill it in."
            )
        return value

    def opt(name: str, default: str = "") -> str:
        return os.environ.get(name, default).strip()

    return Settings(
        twilio_account_sid=req("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=req("TWILIO_AUTH_TOKEN"),
        caller_number=req("TWILIO_CALLER_NUMBER"),
        livekit_url=req("LIVEKIT_URL"),
        livekit_api_key=req("LIVEKIT_API_KEY"),
        livekit_api_secret=req("LIVEKIT_API_SECRET"),
        sip_host=req("SIP_HOST"),
        sip_trunk_user=opt("SIP_TRUNK_USER"),
        sip_trunk_password=opt("SIP_TRUNK_PASSWORD"),
        deepgram_api_key=req("DEEPGRAM_API_KEY"),
        openai_api_key=req("OPENAI_API_KEY"),
        cartesia_api_key=opt("CARTESIA_API_KEY"),
        public_base_url=req("PUBLIC_BASE_URL").rstrip("/"),
        llm_model=opt("LLM_MODEL", "gpt-4o-mini"),
        analyzer_model=opt("ANALYZER_MODEL", "gpt-4o-mini"),
        tts_voice=opt("TTS_VOICE"),
    )
