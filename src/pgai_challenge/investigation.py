"""Cross-call investigation state: what we suspect, what we've proven, what to test next.

The design decision this module exists to serve: **reason between calls, not
inside the turn loop.** The assessment grades latency and conversational pacing
before it grades anything else, so the in-call agent stays a single LLM
round-trip per turn. Every bit of deliberation -- reviewing what the clinic
agent said, forming a hypothesis, deciding what to probe next -- happens here,
in the gap between calls, where latency is free.

The payoff is bug quality. A finding observed once is an anecdote; a finding
re-tested on a later call and reproduced is evidence. The planner below spends
calls preferentially on confirming open suspicions before exploring new ground.
"""
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

LEDGER_PATH = Path("reports/findings.json")

SUSPECTED = "suspected"
CONFIRMED = "confirmed"
REFUTED = "refuted"

# A suspicion needs this many independent observations before we call it real.
CONFIRMATIONS_REQUIRED = 2
# Give up re-testing a suspicion that keeps failing to reproduce.
MAX_ATTEMPTS = 3

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Observation:
    """One sighting of a behaviour, anchored so a reader can go verify it."""

    transcript: str  # e.g. "20260919-101530_book_physical.txt"
    offset_s: float  # seconds from call start, matches transcripts.fmt_offset
    quote: str  # verbatim line from the clinic agent


@dataclass
class Finding:
    id: str
    scenario_id: str  # where we first saw it
    claim: str  # one line: what the agent did wrong
    severity: str  # high | medium | low
    probe: str  # how to re-test it on a later call
    status: str = SUSPECTED
    attempts: int = 0  # how many times we've tried to reproduce it
    observations: list = field(default_factory=list)

    @property
    def times_seen(self) -> int:
        return len(self.observations)


@dataclass
class CallPlan:
    """What the next call should do: a scenario, plus what to dig at."""

    scenario_id: str
    probe_objectives: list = field(default_factory=list)
    reason: str = ""  # why the planner chose this, for the changelog/Loom


class Ledger:
    """Persistent findings state across calls."""

    def __init__(self, findings: list = None) -> None:
        self._findings = list(findings or [])

    # --- persistence -----------------------------------------------------
    @classmethod
    def load(cls, path: Path = LEDGER_PATH) -> "Ledger":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        findings = []
        for item in raw.get("findings", []):
            item = dict(item)  # don't mutate the parsed payload
            observations = [Observation(**o) for o in item.pop("observations", [])]
            findings.append(Finding(observations=observations, **item))
        return cls(findings)

    def save(self, path: Path = LEDGER_PATH) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"findings": [asdict(f) for f in self._findings]}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    # --- reads -----------------------------------------------------------
    @property
    def findings(self) -> list:
        return list(self._findings)

    def by_status(self, status: str) -> list:
        return [f for f in self._findings if f.status == status]

    def open_suspicions(self) -> list:
        """Suspicions still worth spending a call on, worst severity first."""
        candidates = [
            f
            for f in self._findings
            if f.status == SUSPECTED and f.attempts < MAX_ATTEMPTS
        ]
        return sorted(candidates, key=lambda f: (SEVERITY_RANK.get(f.severity, 3), f.id))

    # --- writes (a Finding is never mutated in place; we swap in a copy) --
    def _replace(self, finding: Finding, **changes) -> Finding:
        updated = asdict(finding)
        updated.update(changes)
        updated["observations"] = changes.get("observations", finding.observations)
        replacement = Finding(**updated)
        self._findings[self._findings.index(finding)] = replacement
        return replacement

    def record(
        self, scenario_id: str, claim: str, severity: str, probe: str,
        observation: Observation,
    ) -> Finding:
        """Log a sighting. Re-observing the same claim is what confirms it."""
        existing = next((f for f in self._findings if f.claim == claim), None)
        if existing is None:
            finding = Finding(
                id=f"f{len(self._findings) + 1:03d}",
                scenario_id=scenario_id,
                claim=claim,
                severity=severity,
                probe=probe,
                observations=[observation],
            )
            self._findings.append(finding)
            return finding

        observations = existing.observations + [observation]
        status = (
            CONFIRMED if len(observations) >= CONFIRMATIONS_REQUIRED else existing.status
        )
        return self._replace(existing, observations=observations, status=status)

    def note_attempt(self, finding_id: str) -> Finding:
        """Record that we spent a call trying to reproduce this finding."""
        finding = next(f for f in self._findings if f.id == finding_id)
        attempts = finding.attempts + 1
        status = finding.status
        # Tried enough times without a second sighting -- stop reporting it.
        if attempts >= MAX_ATTEMPTS and finding.times_seen < CONFIRMATIONS_REQUIRED:
            status = REFUTED
        return self._replace(finding, attempts=attempts, status=status)


def plan_next_call(
    ledger: Ledger, all_scenario_ids: list, already_run: list
) -> CallPlan:
    """Choose the next call.

    Priority order, and the reasoning behind it:

    1. **Reproduce an open suspicion.** A bug we can cite twice is worth far
       more than two bugs we saw once. The probe rides along on the scenario
       that surfaced it, so the call is still a natural patient conversation.
    2. **Cover untested scenarios.** The assessment asks for breadth across
       scheduling, refills, hours/insurance and edge cases.
    3. **Re-run where we already found something.** Once coverage is done,
       spend leftover calls on the richest ground.
    """
    unrun = [s for s in all_scenario_ids if s not in already_run]
    suspicions = ledger.open_suspicions()

    # Confirm before exploring -- but let the first couple of calls spread out
    # first, so we aren't chasing a single early suspicion with no breadth.
    if suspicions and len(already_run) >= 2:
        target = suspicions[0]
        return CallPlan(
            scenario_id=target.scenario_id,
            probe_objectives=[target.probe],
            reason=(
                f"re-test {target.id} ({target.severity}): seen "
                f"{target.times_seen}x, need {CONFIRMATIONS_REQUIRED} to confirm"
            ),
        )

    if unrun:
        return CallPlan(
            scenario_id=unrun[0], reason="new scenario: coverage not yet complete"
        )

    if suspicions:
        target = suspicions[0]
        return CallPlan(
            scenario_id=target.scenario_id,
            probe_objectives=[target.probe],
            reason=f"re-test {target.id}: coverage complete, confirming findings",
        )
    return CallPlan(
        scenario_id=all_scenario_ids[0], reason="coverage complete, no open suspicions"
    )
