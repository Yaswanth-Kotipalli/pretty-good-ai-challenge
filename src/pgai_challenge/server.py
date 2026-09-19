"""Twilio webhook server: bridges the PSTN call into the LiveKit room via SIP.

Twilio is a dumb carrier here. It dials the assessment line, and when the
clinic agent answers, <Dial><Sip> bridges the audio into our LiveKit room,
where the patient agent (LiveKit Agents, pipeline mode) is already waiting.
Twilio also records both sides of the call, which is what the challenge
grades first ("we listen to the voice calls your bot made").
"""
import json
import logging
import os
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
            # Dual-channel: our patient bot and the clinic agent land on
            # separate channels, so a bug report can attribute every line
            # without guessing from a mono mixdown.
            record="record-from-answer-dual",
            recording_status_callback=(
                f"{settings.public_base_url}/recording-callback"
                f"?scenario_id={scenario_id}"
            ),
            recording_status_callback_method="POST",
            # Without an action URL, TwiML falls through to the next verb when
            # the bridge ends NORMALLY -- so the clinic agent heard the failure
            # message at the end of every successful call.
            action=f"{settings.public_base_url}/after-dial",
            method="POST",
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
        return Response(str(resp), mimetype="text/xml")

    @app.post("/after-dial")
    def after_dial():
        """Runs once the <Dial> bridge ends. Only speak on an actual failure."""
        status = request.form.get("DialCallStatus", "")
        resp = VoiceResponse()
        if status != "completed":
            logger.warning("dial ended with status %s", status)
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
    port = int(os.getenv("PORT", "5000"))
    create_app().run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
