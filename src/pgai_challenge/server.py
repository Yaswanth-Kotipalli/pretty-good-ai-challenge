"""Twilio webhook server: bridges the PSTN call into the LiveKit room via SIP.

Twilio is a dumb carrier here. It dials the assessment line, and when the
clinic agent answers, <Dial><Sip> bridges the audio into our LiveKit room,
where the patient agent (LiveKit Agents, pipeline mode) is already waiting.
Twilio also records both sides of the call, which is what the challenge
grades first ("we listen to the voice calls your bot made").
"""
import json
import logging
from pathlib import Path

from flask import Flask, Response, request
from twilio.twiml.voice_response import Dial, VoiceResponse

from .config import ROOM_NAME, load_settings
from .recording import RECORDING_DIR

logger = logging.getLogger("pgai-server")


def create_app(settings=None):
    settings = settings or load_settings()
    app = Flask(__name__)

    @app.post("/twiml/<scenario_id>")
    def twiml(scenario_id):
        """TwiML for the outbound leg: answer -> bridge into LiveKit via SIP."""
        resp = VoiceResponse()
        dial = Dial(
            record="record-from-answer",
            recording_status_callback=(
                f"{settings.public_base_url}/recording-callback"
                f"?scenario_id={scenario_id}"
            ),
            recording_status_callback_method="POST",
        )
        sip_uri = f"sip:{ROOM_NAME}@{settings.sip_host}"
        if settings.sip_trunk_user:
            dial.sip(
                sip_uri,
                username=settings.sip_trunk_user,
                password=settings.sip_trunk_password,
            )
        else:
            dial.sip(sip_uri)
        resp.append(dial)
        # If the SIP leg fails, don't leave dead air.
        resp.say("Sorry, the test system is unavailable. Goodbye.")
        resp.hangup()
        return Response(str(resp), mimetype="text/xml")

    @app.post("/recording-callback")
    def recording_callback():
        """Queue the finished recording for download (see recording.py)."""
        RECORDING_DIR.mkdir(exist_ok=True)
        item = {
            "scenario_id": request.args.get("scenario_id", "unknown"),
            "call_sid": request.form.get("CallSid"),
            "recording_sid": request.form.get("RecordingSid"),
            "recording_url": request.form.get("RecordingUrl"),
        }
        with open(RECORDING_DIR / "pending.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(item) + "\n")
        logger.info("queued recording %s", item["recording_sid"])
        return ("", 204)

    @app.post("/status-callback")
    def status_callback():
        logger.info(
            "call %s -> %s",
            request.form.get("CallSid"),
            request.form.get("CallStatus"),
        )
        return ("", 204)

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


def main():
    logging.basicConfig(level=logging.INFO)
    create_app().run(host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
