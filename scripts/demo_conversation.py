"""Interactive and automated conversation demo for testing patient personas locally.

Use this script to test scenarios without touching telephony (no Twilio/LiveKit SIP needed).
You can either play the role of the clinic receptionist yourself (interactive mode),
or let an automated simulator run both sides.

Usage:
  # Interactive mode (you are the receptionist):
  python scripts/demo_conversation.py --scenario book_physical

  # Automated simulation mode (runs a complete dialogue in seconds):
  python scripts/demo_conversation.py --scenario book_physical --auto

  # Test medical safety probes:
  python scripts/demo_conversation.py --scenario edge_dosing_advice --auto
  python scripts/demo_conversation.py --scenario edge_third_party --auto
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pgai_challenge.agent import build_instructions
from pgai_challenge.personas import SCENARIOS, get_scenario
from pgai_challenge.transcripts import fmt_offset


def run_interactive(scenario, client, model: str) -> None:
    print("\n" + "=" * 65)
    print(f"PATIENT SIMULATOR DEMO: {scenario.title} ({scenario.id})")
    print(f"Patient Name: {scenario.name} | Age: {scenario.age} | DOB: {scenario.dob}")
    print(f"Goal: {scenario.goal}")
    if scenario.mid_call_twist:
        print(f"Mid-Call Twist: {scenario.mid_call_twist}")
    print("=" * 65)
    print("\n[ROLE]: You are the CLINIC RECEPTIONIST answering the phone.")
    print("Type your responses below. Type 'exit' or 'hangup' to quit manually.\n")

    instructions = build_instructions(scenario)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "hang_up",
                "description": "Call when conversation is finished, goal is achieved, or farewell exchanged.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    messages = [
        {"role": "system", "content": instructions},
    ]

    # Greeting prompt
    greeting = input("[Clinic Receptionist]: ").strip()
    if not greeting:
        greeting = "Thank you for calling Pine Valley Medical Clinic. How can I help you today?"
        print(f"(Using default greeting: \"{greeting}\")")

    messages.append({"role": "user", "content": greeting})
    turn_count = 1
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        print(f"\n... Patient ({scenario.name}) is thinking ...")
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.7,
        )
        choice = resp.choices[0]
        msg = choice.message

        if msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.function.name == "hang_up":
                    print(f"\n[{fmt_offset(elapsed)}] [Patient Tool Call]: hang_up() fired!")
                    print(f"[Patient]: (Hung up the phone)")
                    print("\n>> Call concluded naturally via hang_up tool <<\n")
                    return

        reply_text = msg.content or ""
        messages.append({"role": "assistant", "content": reply_text})
        print(f"[{fmt_offset(elapsed)}] [Patient]: {reply_text}")

        turn_count += 1
        if turn_count > scenario.max_turns:
            print("\n>> Maximum turns reached. Ending call. <<\n")
            break

        user_input = input("\n[Clinic Receptionist]: ").strip()
        if user_input.lower() in ("exit", "hangup", "bye"):
            print("\n>> Receptionist hung up. <<\n")
            break
        messages.append({"role": "user", "content": user_input})


def run_auto(scenario, client, model: str) -> None:
    print("\n" + "=" * 65)
    print(f"AUTOMATED CONVERSATION DEMO: {scenario.title} ({scenario.id})")
    print(f"Patient Name: {scenario.name} | Age: {scenario.age}")
    print(f"Goal: {scenario.goal}")
    print("=" * 65 + "\n")

    patient_instructions = build_instructions(scenario)
    receptionist_prompt = (
        "You are an AI medical clinic receptionist at Pine Valley Medical Clinic. "
        "Be professional, courteous, and efficient. Ask for necessary details (name, DOB) "
        "to look up records or schedule. If a caller asks for medical advice, adhere strictly "
        "to safety: do not prescribe doses; offer an appointment with a physician. "
        "If a caller asks for another adult's records without HIPAA authorization, decline politely. "
        "Keep responses under 30 words."
    )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "hang_up",
                "description": "Call when conversation is finished, goal is achieved, or farewell exchanged.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    patient_messages = [{"role": "system", "content": patient_instructions}]
    receptionist_messages = [{"role": "system", "content": receptionist_prompt}]

    # Clinic opens call with greeting
    current_receptionist_turn = (
        "Thank you for calling Pine Valley Medical Clinic. My name is Alex, how may I assist you?"
    )
    print(f"[0:00] [Clinic Receptionist]:\n{current_receptionist_turn}\n")
    patient_messages.append({"role": "user", "content": current_receptionist_turn})
    receptionist_messages.append({"role": "assistant", "content": current_receptionist_turn})

    sim_start = time.time()
    sim_offset = 0.0

    for turn in range(1, 10):
        sim_offset += 6.0 + (turn * 1.5)
        # Patient turn
        resp = client.chat.completions.create(
            model=model,
            messages=patient_messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.6,
        )
        choice = resp.choices[0]
        patient_reply = choice.message

        if patient_reply.tool_calls:
            for tc in patient_reply.tool_calls:
                if tc.function.name == "hang_up":
                    print(f"[{fmt_offset(sim_offset)}] [PATIENT (our bot)]: *calls hang_up()*")
                    print("\n>> Call ended via hang_up tool. Total simulated duration:", fmt_offset(sim_offset), "<<\n")
                    return

        reply_content = patient_reply.content or ""
        print(f"[{fmt_offset(sim_offset)}] [PATIENT (our bot)]:\n{reply_content}\n")
        patient_messages.append({"role": "assistant", "content": reply_content})
        receptionist_messages.append({"role": "user", "content": reply_content})

        if any(w in reply_content.lower() for w in ["goodbye", "bye", "have a great day"]):
            print(f">> Call completed gracefully at {fmt_offset(sim_offset)} <<\n")
            return

        # Receptionist turn
        sim_offset += 5.0
        rec_resp = client.chat.completions.create(
            model=model,
            messages=receptionist_messages,
            temperature=0.3,
        )
        rec_reply = rec_resp.choices[0].message.content.strip()
        print(f"[{fmt_offset(sim_offset)}] [AGENT (receptionist)]:\n{rec_reply}\n")
        receptionist_messages.append({"role": "assistant", "content": rec_reply})
        patient_messages.append({"role": "user", "content": rec_reply})

        if any(w in rec_reply.lower() for w in ["have a good day", "take care", "goodbye"]):
            # Trigger patient final turn / hangup
            pass


def main():
    parser = argparse.ArgumentParser(description="Test patient simulator conversation locally")
    parser.add_argument("--scenario", default="book_physical", help="Scenario ID (e.g. book_physical, edge_vague)")
    parser.add_argument("--auto", action="store_true", help="Run automated conversation with simulated receptionist")
    parser.add_argument("--list", action="store_true", help="List all scenario IDs")
    parser.add_argument("--model", default="gpt-4o-mini", help="OpenAI model (default: gpt-4o-mini)")
    args = parser.parse_args()

    if args.list:
        print("\nAvailable Scenarios:")
        for s in SCENARIOS:
            print(f"  {s.id:22} - {s.title}")
        print()
        return

    try:
        scenario = get_scenario(args.scenario)
    except KeyError:
        print(f"Error: Unknown scenario '{args.scenario}'. Use --list to view valid scenarios.")
        sys.exit(1)

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY=") and not openai_key:
                openai_key = line.split("=", 1)[1].strip()
            elif line.startswith("GEMINI_API_KEY=") and not gemini_key:
                gemini_key = line.split("=", 1)[1].strip()

    if not (openai_key or gemini_key):
        print("\n[Notice] Neither OPENAI_API_KEY nor GEMINI_API_KEY found in environment or .env.")
        print("To run the live interactive/automated demo, set your key:")
        print("  export GEMINI_API_KEY='AIza...'  # OR: export OPENAI_API_KEY='sk-...'")
        print("\nDisplaying scenario prompt preview instead:")
        print("-" * 65)
        print(build_instructions(scenario))
        print("-" * 65 + "\n")
        return

    from openai import OpenAI

    if gemini_key and not openai_key:
        print("[Engine: Google Gemini (generativelanguage.googleapis.com)]")
        client = OpenAI(
            api_key=gemini_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        model = (
            args.model
            if args.model != "gpt-4o-mini"
            else "gemini-2.0-flash"
        )
    else:
        print("[Engine: OpenAI]")
        client = OpenAI(api_key=openai_key)
        model = args.model

    if args.auto:
        run_auto(scenario, client, model)
    else:
        run_interactive(scenario, client, model)


if __name__ == "__main__":
    main()
