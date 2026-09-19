"""Offline tests for offset-based transcript persistence."""
from pgai_challenge import transcripts
from pgai_challenge.transcripts import fmt_offset


def test_fmt_offset():
    assert fmt_offset(83) == "1:23"
    assert fmt_offset(5) == "0:05"
    assert fmt_offset(0) == "0:00"
    assert fmt_offset(600) == "10:00"


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "t.jsonl"
    transcripts.append_turn(path, "agent", "Hello?", 12.5)
    transcripts.append_turn(path, "patient", "Hi, I'd like to book.", 18.0)
    turns = transcripts.load_turns(path)
    assert len(turns) == 2
    assert turns[0]["t_s"] == 12.5
    assert turns[1]["role"] == "patient"


def test_text_file_uses_offsets(tmp_path):
    path = tmp_path / "t.jsonl"
    transcripts.append_turn(path, "agent", "Hello?", 83)
    txt = transcripts.to_text_file(path)
    content = txt.read_text(encoding="utf-8")
    assert "[1:23]" in content
    assert "2026" not in content  # no wall-clock timestamps
