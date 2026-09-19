# Changelog

The challenge rewards evidence of iteration — log every meaningful change here,
with what you heard/saw that motivated it.

## v0.2 — 2026-09-19 — review fixes (pipeline correctness)
- **Turn detection:** raw VAD endpointing → semantic `TurnDetector`. VAD talked
  over the clinic agent's mid-sentence pauses; the semantic model waits for a
  completed thought.
- **Interruptions:** removed the inverted `allow_interruptions` flag. The flag
  controls whether the remote party may interrupt *our* playback -- setting it
  False caused talk-over on 11 of 12 calls. Now `InterruptionOptions(enabled=True)`
  for every scenario.
- **SIP host:** `sip.livekit.cloud` doesn't resolve; each project gets its own
  endpoint. New required `SIP_HOST` setting (e.g. `abc123.sip.livekit.cloud`).
- **Transcripts:** wall-clock ISO timestamps → seconds-since-call-start offsets
  (`[1:23]`), written incrementally by a 2s pump instead of once at session end.
  Fixed the docstring that claimed incremental writes it didn't do.
- **New scenarios:** `edge_dosing_advice` (must not give dosing instructions) and
  `edge_third_party` (must not disclose another patient's PHI) -- the two
  highest-severity bug classes in healthcare voice. Analyzer rubric updated.
- **Mid-call twists:** scenarios can now carry a `mid_call_twist` the patient
  introduces naturally after a few exchanges, so calls don't run on rails.
- Known limitation documented: the Twilio-bridge greeting race (~2-3s of the
  opening greeting can be lost); full fix needs the outbound-SIP topology.

## v0.1 — 2026-09-19 — initial build
- LiveKit Agents pipeline worker (Deepgram STT → gpt-4o-mini → OpenAI TTS,
  Silero VAD) with 12 original patient scenarios and a `hang_up` function tool.
- Twilio carrier + SIP bridge into the LiveKit room; `record-from-answer` on
  every call; safety guardrail hardcoded to the assessment number.
- Runner (dispatch → dial → wait → manifest), recording downloader with
  retry-on-404, transcript saver, LLM bug-report analyzer.
- Offline pytest suite: dial guardrail, TwiML bridge, agent prompt (11 tests).
