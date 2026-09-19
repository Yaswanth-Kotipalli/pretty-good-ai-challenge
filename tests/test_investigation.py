"""The cross-call investigation loop: reproduce before reporting.

The point of this layer is bug *quality*. A behaviour seen once is an anecdote;
the ledger only promotes it to CONFIRMED after an independent second sighting,
and the planner spends calls chasing that second sighting before exploring.
"""
from pgai_challenge.investigation import (
    CONFIRMED,
    MAX_ATTEMPTS,
    REFUTED,
    SUSPECTED,
    Ledger,
    Observation,
    plan_next_call,
)

SUNDAY_BUG = "books an appointment on Sunday without checking office hours"


def _obs(
    name="20260919-101530_book_physical.txt",
    offset=83.0,
    quote="I've booked you Sunday at 10am.",
):
    return Observation(transcript=name, offset_s=offset, quote=quote)


def test_first_sighting_is_only_suspected():
    # Arrange / Act
    ledger = Ledger()
    finding = ledger.record(
        "book_physical", SUNDAY_BUG, "high", "ask for a Sunday slot", _obs()
    )

    # Assert: one observation is not evidence
    assert finding.status == SUSPECTED
    assert finding.times_seen == 1


def test_second_independent_sighting_confirms_it():
    # Arrange
    ledger = Ledger()
    ledger.record("book_physical", SUNDAY_BUG, "high", "ask for a Sunday slot", _obs())

    # Act: same claim, different call
    finding = ledger.record(
        "reschedule",
        SUNDAY_BUG,
        "high",
        "ask for a Sunday slot",
        _obs("20260919-104500_reschedule.txt", 48.0),
    )

    # Assert
    assert finding.status == CONFIRMED
    assert finding.times_seen == 2
    assert [o.transcript for o in finding.observations] == [
        "20260919-101530_book_physical.txt",
        "20260919-104500_reschedule.txt",
    ]


def test_unreproducible_suspicion_is_refuted_not_reported():
    # Arrange
    ledger = Ledger()
    finding = ledger.record("book_physical", SUNDAY_BUG, "high", "probe", _obs())

    # Act: burn every retry without ever seeing it again
    for _ in range(MAX_ATTEMPTS):
        ledger.note_attempt(finding.id)

    # Assert: it drops out of the report rather than becoming a shaky claim
    assert ledger.by_status(REFUTED)[0].id == finding.id
    assert ledger.open_suspicions() == []


def test_planner_covers_new_scenarios_before_it_has_anything_to_chase():
    # Act
    plan = plan_next_call(Ledger(), ["a", "b", "c"], already_run=["a"])

    # Assert
    assert plan.scenario_id == "b"
    assert plan.probe_objectives == []


def test_planner_chases_the_highest_severity_open_suspicion():
    # Arrange: a low and a high suspicion outstanding
    ledger = Ledger()
    ledger.record("cancel", "minor phrasing wobble", "low", "probe low", _obs())
    ledger.record("book_physical", SUNDAY_BUG, "high", "ask for a Sunday slot", _obs())

    # Act: enough calls have run that confirming beats exploring
    plan = plan_next_call(ledger, ["a", "b", "c"], already_run=["a", "b"])

    # Assert: high severity first, and the probe rides along
    assert plan.scenario_id == "book_physical"
    assert plan.probe_objectives == ["ask for a Sunday slot"]
    assert "high" in plan.reason


def test_ledger_round_trips_through_disk(tmp_path):
    # Arrange
    path = tmp_path / "findings.json"
    ledger = Ledger()
    ledger.record("book_physical", SUNDAY_BUG, "high", "ask for a Sunday slot", _obs())
    ledger.save(path)

    # Act
    reloaded = Ledger.load(path)

    # Assert
    assert reloaded.findings[0] == ledger.findings[0]
    assert reloaded.findings[0].observations[0].offset_s == 83.0


def test_loading_a_missing_ledger_starts_empty(tmp_path):
    assert Ledger.load(tmp_path / "nope.json").findings == []
