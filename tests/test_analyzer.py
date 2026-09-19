"""Regression tests for the transcript -> scenario-id mapping.

This parse was silently wrong: it truncated every underscored scenario id, so
12 of 14 calls were dropped from the bug report with no error raised.
"""
from pathlib import Path

import pytest

from pgai_challenge.analyzer import scenario_id_from_transcript
from pgai_challenge.personas import SCENARIOS, get_scenario
from pgai_challenge.transcripts import new_transcript


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_every_scenario_id_survives_a_filename_round_trip(scenario, tmp_path, monkeypatch):
    """A real transcript filename must map back to a resolvable scenario."""
    # Arrange: build the filename exactly as the worker does
    monkeypatch.setattr("pgai_challenge.transcripts.TRANSCRIPT_DIR", tmp_path)
    jsonl = new_transcript(scenario.id)

    # Act
    recovered = scenario_id_from_transcript(jsonl.with_suffix(".txt"))

    # Assert: round-trips, and the id actually resolves
    assert recovered == scenario.id
    assert get_scenario(recovered).id == scenario.id


def test_underscored_ids_are_not_truncated():
    """The specific failure mode: rsplit chopped the trailing segment."""
    assert (
        scenario_id_from_transcript(Path("20260919-101530_edge_dosing_advice.txt"))
        == "edge_dosing_advice"
    )
    assert (
        scenario_id_from_transcript(Path("20260919-101530_refill_urgent.txt"))
        == "refill_urgent"
    )
