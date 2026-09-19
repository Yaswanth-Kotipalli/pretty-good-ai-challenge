"""Incremental, offset-based transcript persistence.

Turns are appended the moment they're observed (the worker runs a pump that
flushes new history items every 2 seconds), stamped with seconds since the
call started. Offsets -- not wall-clock time -- are what let a bug report
cite "transcript-07.txt at 1:23" against a recording. Nothing is trusted
until it's flushed to disk: a dead worker loses at most 2 seconds.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

TRANSCRIPT_DIR = Path("transcripts")


def new_transcript(scenario_id: str) -> Path:
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return TRANSCRIPT_DIR / f"{ts}_{scenario_id}.jsonl"


def fmt_offset(seconds: float) -> str:
    """83.0 -> '1:23'. Matches the citation style bug reports use."""
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


def append_turn(path: Path, role: str, text: str, t_s: float) -> None:
    """Append one turn. role is 'patient' (our bot) or 'agent' (their bot);
    t_s is seconds since the call started."""
    record = {"t_s": round(t_s, 1), "role": role, "text": text}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_turns(path: Path) -> list:
    turns = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                turns.append(json.loads(line))
    return turns


def to_text_file(jsonl_path: Path) -> Path:
    """Render a human-readable transcript-*.txt with [M:SS] offsets."""
    lines = []
    for t in load_turns(jsonl_path):
        speaker = "PATIENT (our bot)" if t["role"] == "patient" else "AGENT (their bot)"
        lines.append(f"[{fmt_offset(t['t_s'])}] {speaker}:\n{t['text']}\n")
    txt_path = jsonl_path.with_suffix(".txt")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return txt_path
