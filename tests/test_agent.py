"""Offline tests for the patient agent prompt builder."""
import asyncio

from pgai_challenge.agent import PatientAgent, build_instructions
from pgai_challenge.personas import get_scenario


def test_instructions_contain_identity_and_goal():
    s = get_scenario("book_physical")
    text = build_instructions(s)
    assert s.name in text
    assert s.dob in text
    assert s.goal in text
    assert s.opening_line in text


def test_instructions_forbid_benchmark_behavior():
    s = get_scenario("edge_vague")
    text = build_instructions(s).lower()
    assert "hang_up" in text  # end-of-call protocol present
    assert "receptionist" in text  # stay-in-character rule present
    assert "never mention you are an ai" in text


def test_mid_call_twist_included_when_set():
    s = get_scenario("book_physical")
    assert s.mid_call_twist  # fixture has a twist
    text = build_instructions(s)
    assert "flu shot" in text
    assert str(s.twist_after_turns) in text


def test_no_twist_block_when_empty():
    s = get_scenario("cancel")
    assert not s.mid_call_twist
    assert "Mid-call development" not in build_instructions(s)


def test_safety_probe_scenarios_exist():
    dosing = get_scenario("edge_dosing_advice")
    assert "take two" in dosing.opening_line
    phi = get_scenario("edge_third_party")
    assert "wife" in phi.opening_line.lower()


def test_hang_up_tool_sets_event():
    async def go():
        s = get_scenario("cancel")
        event = asyncio.Event()
        agent = PatientAgent(s, event)
        assert not event.is_set()
        # call the underlying tool function directly
        fn = agent.hang_up
        # @function_tool wraps the method; invoke via its raw func
        raw = getattr(fn, "__wrapped__", None) or getattr(fn, "func", None)
        assert raw is not None, "could not unwrap function_tool"
        await raw(agent, None)
        assert event.is_set()

    asyncio.run(go())
