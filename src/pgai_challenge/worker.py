"""LiveKit worker entrypoint: runs one patient call per dispatched job.

Each job carries {"scenario_id": ...} in its metadata (set by runner.py via
explicit agent dispatch). The worker joins the fixed room, runs the patient
agent in pipeline mode until the hang_up tool fires or the time cap hits,
then exits so the next dispatch gets a fresh job.

Turn-taking: a semantic end-of-turn model (not raw voice-activity
endpointing) decides when the clinic agent has finished speaking, so the
patient doesn't talk over mid-sentence pauses. Interruptions are ENABLED:
when the clinic agent starts speaking over our bot, our bot yields -- that
flag controls whether the remote party may interrupt our playback, and
disabling it is what causes talk-over.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from livekit.agents import (
    AgentSession,
    JobContext,
    TurnHandlingOptions,
    WorkerOptions,
    cli,
)
from livekit.agents.inference import TurnDetector
from livekit.agents.voice.turn import InterruptionOptions
from livekit.plugins import deepgram, openai, silero
try:
    from livekit.plugins import google
except ImportError:
    google = None

from . import transcripts
from .agent import PatientAgent
from .config import load_settings
from .personas import get_scenario

logger = logging.getLogger("pgai-worker")

# user = the remote clinic agent speaking; assistant = our patient bot
ROLE_LABELS = {"user": "agent", "assistant": "patient", "system": "system"}

PUMP_INTERVAL_S = 2.0  # worst-case transcript loss on worker crash


def _item_text(item) -> str:
    content = getattr(item, "content", "")
    if isinstance(content, str):
        return content.strip()
    parts = []
    for chunk in content or []:
        if isinstance(chunk, str):
            parts.append(chunk)
        else:
            text = getattr(chunk, "text", None)
            if text:
                parts.append(text)
    return " ".join(parts).strip()


def _flush_new_turns(session: AgentSession, path, call_start, seen: int) -> int:
    """Append newly appeared history items to the transcript. Returns new count."""
    items = session.history.items[seen:]
    now = datetime.now(timezone.utc)
    for item in items:
        role = ROLE_LABELS.get(getattr(item, "role", ""), "other")
        text = _item_text(item)
        if role == "system" or not text:
            continue
        t_s = (now - call_start).total_seconds()
        transcripts.append_turn(path, role, text, t_s)
    return len(session.history.items)


async def _transcript_pump(session, path, call_start, stop_event: asyncio.Event):
    """Flush new turns to disk every PUMP_INTERVAL_S until told to stop."""
    seen = 0
    while not stop_event.is_set():
        await asyncio.sleep(PUMP_INTERVAL_S)
        seen = _flush_new_turns(session, path, call_start, seen)
    seen = _flush_new_turns(session, path, call_start, seen)  # final flush
    transcripts.to_text_file(path)
    logger.info("transcript finalized: %s", path.with_suffix(".txt"))


async def entrypoint(ctx: JobContext):
    metadata = json.loads(ctx.job.metadata or "{}")
    scenario_id = metadata.get("scenario_id")
    if not scenario_id:
        raise RuntimeError("job metadata must include scenario_id")
    scenario = get_scenario(scenario_id)
    # Probes planned between calls by investigation.plan_next_call, carried in
    # the dispatch metadata. Absent on a plain exploratory call.
    probe_objectives = metadata.get("probe_objectives") or []
    settings = load_settings()

    await ctx.connect()
    logger.info(
        "joined room for scenario %s (%d planned probe(s))",
        scenario_id,
        len(probe_objectives),
    )

    hangup = asyncio.Event()
    agent = PatientAgent(scenario, hangup, probe_objectives)

    if settings.llm_provider == "google":
        if google is None:
            raise RuntimeError(
                "livekit-plugins-google is required for Gemini LLM. "
                "Run 'pip install livekit-plugins-google'."
            )
        llm_instance = google.LLM(
            model=settings.llm_model, api_key=settings.gemini_api_key
        )
    else:
        llm_instance = openai.LLM(
            model=settings.llm_model, api_key=settings.openai_api_key
        )

    tts_voice = settings.tts_voice or ("nova" if scenario.voice == "female" else "onyx")
    if settings.openai_api_key:
        tts_instance = openai.TTS(api_key=settings.openai_api_key, voice=tts_voice)
    elif settings.gemini_api_key and google is not None:
        tts_instance = google.TTS()
    else:
        tts_instance = openai.TTS(api_key=settings.openai_api_key, voice=tts_voice)

    session = AgentSession(
        stt=deepgram.STT(
            api_key=settings.deepgram_api_key, model="nova-3", language="en-US"
        ),
        llm=llm_instance,
        tts=tts_instance,
        vad=silero.VAD.load(),
        # Semantic end-of-turn: waits for a completed thought, not just
        # silence. Raw VAD endpointing talks over the clinic agent's
        # mid-sentence pauses ("let me check that for you...").
        turn_handling=TurnHandlingOptions(
            turn_detection=TurnDetector(),
            # The remote party may interrupt our bot's playback. This is what
            # produces natural turn-taking; disabling it causes talk-over.
            interruption=InterruptionOptions(enabled=True),
        ),
    )

    call_start = datetime.now(timezone.utc)
    transcript_path = transcripts.new_transcript(scenario_id)
    pump_stop = asyncio.Event()
    pump = asyncio.create_task(
        _transcript_pump(session, transcript_path, call_start, pump_stop)
    )

    await session.start(agent=agent, room=ctx.room)
    logger.info("patient agent started, waiting for clinic greeting")
    try:
        await asyncio.wait_for(hangup.wait(), timeout=settings.max_call_seconds)
        logger.info("hang_up tool fired")
    except asyncio.TimeoutError:
        logger.info("max call time (%ss) reached, ending", settings.max_call_seconds)
    finally:
        pump_stop.set()
        await pump
        await session.aclose()

    logger.info("job done for scenario %s", scenario_id)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="patient-bot"))
