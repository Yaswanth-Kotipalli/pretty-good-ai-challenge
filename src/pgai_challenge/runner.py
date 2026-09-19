"""Orchestrate test calls: dispatch worker -> dial via Twilio -> wait -> next.

One scenario per run: the worker is explicitly dispatched into the fixed
room, then Twilio dials the assessment line and bridges the answered call
into that room over SIP. Calls run sequentially with a cooldown between
them. A manifest is written to reports/run_manifest.json.
"""
import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from twilio.rest import Client as TwilioClient

from livekit import api as lk_api

from .config import ASSESSMENT_NUMBER, ROOM_NAME, assert_safe_to_dial, load_settings
from .personas import SCENARIOS


def lk_client(settings):
    return lk_api.LiveKitAPI(
        settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret
    )


async def ensure_room(lk):
    try:
        await lk.room.create_room(lk_api.CreateRoomRequest(name=ROOM_NAME))
    except Exception as e:  # noqa: BLE001 - room may already exist
        if "already exists" not in str(e).lower():
            raise


async def dispatch_worker(lk, scenario_id: str):
    await lk.agent_dispatch.create_dispatch(
        lk_api.CreateAgentDispatchRequest(
            agent_name="patient-bot",
            room=ROOM_NAME,
            metadata=json.dumps({"scenario_id": scenario_id}),
        )
    )


def place_call(
    twilio: TwilioClient, settings, scenario_id: str, target_number: str = ""
) -> str:
    target = target_number or settings.test_phone_number or ASSESSMENT_NUMBER
    assert_safe_to_dial(
        target, allowed_test_number=settings.test_phone_number or target_number
    )
    call = twilio.calls.create(
        to=target,
        from_=settings.caller_number,
        url=f"{settings.public_base_url}/twiml/{scenario_id}",
        method="POST",
        status_callback=f"{settings.public_base_url}/status-callback",
        status_callback_method="POST",
        timeout=30,
    )
    return call.sid


def wait_for_call(twilio: TwilioClient, call_sid: str, timeout_s: int = 420) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = twilio.calls(call_sid).fetch().status
        if status in ("completed", "failed", "busy", "no-answer", "canceled"):
            return status
        time.sleep(5)
    return "timeout"


async def run_scenario(
    settings, twilio, lk, scenario_id: str, target_number: str = ""
) -> dict:
    await ensure_room(lk)
    await dispatch_worker(lk, scenario_id)
    await asyncio.sleep(8)  # let the worker join the room first
    call_sid = place_call(twilio, settings, scenario_id, target_number=target_number)
    target_display = target_number or settings.test_phone_number or ASSESSMENT_NUMBER
    print(f"[{scenario_id}] call {call_sid} placed to {target_display}, waiting for completion...")
    final = await asyncio.to_thread(wait_for_call, twilio, call_sid)
    print(f"[{scenario_id}] ended: {final}")
    return {
        "scenario_id": scenario_id,
        "call_sid": call_sid,
        "target_number": target_display,
        "final_status": final,
        "at": datetime.now(timezone.utc).isoformat(),
    }


async def amain(args) -> None:
    settings = load_settings()
    if args.test_number:
        settings.test_phone_number = args.test_number.strip()
    twilio = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    lk = lk_client(settings)
    try:
        ids = [s.id for s in SCENARIOS] if args.all else [args.scenario]
        manifest = []
        for i, sid in enumerate(ids):
            manifest.append(
                await run_scenario(
                    settings, twilio, lk, sid, target_number=settings.test_phone_number
                )
            )
            if i < len(ids) - 1:
                print(f"cooling down {args.delay}s before next call...")
                await asyncio.sleep(args.delay)
        Path("reports").mkdir(exist_ok=True)
        Path("reports/run_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        print("manifest written to reports/run_manifest.json")
    finally:
        await lk.aclose()


def main() -> None:
    ap = argparse.ArgumentParser(description="Run patient-simulator test calls")
    ap.add_argument("--list", action="store_true", help="list scenario ids")
    ap.add_argument("--scenario", help="run a single scenario id")
    ap.add_argument("--all", action="store_true", help="run all scenarios sequentially")
    ap.add_argument("--delay", type=int, default=20, help="cooldown seconds between calls")
    ap.add_argument(
        "--test-number",
        help="dial an approved personal/test phone number (E.164, e.g. +13334445555)",
    )
    args = ap.parse_args()
    if args.list:
        for s in SCENARIOS:
            print(f"{s.id:22} {s.title}")
        return
    if not args.all and not args.scenario:
        ap.error("pass --scenario ID or --all")
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
