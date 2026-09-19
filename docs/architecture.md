# Architecture

## How it works

The patient simulator is a **LiveKit Agents pipeline-mode** voice agent: Deepgram `nova-3`
for speech-to-text, `gpt-4o-mini` as the patient brain, and OpenAI TTS for speech,
with a semantic end-of-turn model (not raw voice-activity endpointing) deciding when
the clinic agent has finished speaking. No realtime/speech-to-speech models,
no hosted voice platforms — just three separate stages, as the challenge requires.

Twilio is used purely as a dumb PSTN carrier. The runner dials Pretty Good AI's assessment
line (`+1-805-439-8008`) from a single Twilio number; when the clinic agent answers,
`<Dial><Sip>` bridges the audio into a fixed LiveKit room (`pgai-test`) where the patient
agent is already waiting. Twilio records both sides of every call with `record-from-answer`
— the artifact the challenge grades first ("we listen to the voice calls your bot made").
The worker saves the transcript incrementally (a pump flushes new turns to disk
every 2 seconds, stamped with seconds since call start, so bug reports can cite
"transcript-07.txt at 1:23" against the recording), a downloader fetches the MP3s
(tolerating Twilio's recording-ready race with retry-on-404), and an LLM analyzer pass
turns transcripts into `docs/bug_report.md`.

Each call runs one of 14 scenarios (scheduling, rescheduling, cancellation, refills,
hours/location, insurance, plus edge cases: vague caller, impatient interrupter, record
dispute, out-of-scope request, dosing-advice safety probe, third-party PHI probe).
Several scenarios include a mid-call twist the patient introduces naturally after a few
exchanges, so calls don't run on rails. The patient persona — identity, goal, conversational
quirks — lives in the LLM instructions, not a script, so it steers toward the test outcome
while reacting naturally. A `hang_up` function tool lets the patient end the call when its
goal is done; a 4-minute cap and 12-turn cap bound every call. A guardrail hardcoded to the
assessment number is checked before every outbound dial, so the bot can never call any
other number.

## Key decisions and tradeoffs

- **LiveKit pipeline, not realtime:** required by the challenge (realtime models are
  banned). Pipeline also gives per-stage control and a transcript for free.
- **Deepgram nova-3 for STT:** tuned for phone audio; materially better than generic
  models on the compressed, sometimes noisy audio of a phone call.
- **gpt-4o-mini for the patient LLM:** follows persona/goal/quirks instructions reliably
  at a fraction of a cent per call. A larger model wasn't needed for roleplay.
- **OpenAI TTS instead of Cartesia:** Cartesia is lower-latency, but OpenAI TTS needs no
  second API key and ~1s of TTS latency is fine for a *patient* caller — real patients
  pause too. One-line swap in `worker.py` if latency becomes the bottleneck.
- **Twilio as carrier instead of LiveKit-native SIP trunking:** Twilio gives
  `record-from-answer` with zero extra infrastructure. Both-sides audio is the #1 graded
  artifact, so recording reliability beat the elegance of an all-LiveKit setup. Twilio
  holds no conversational logic whatsoever.
- **Semantic turn detection, not raw VAD endpointing:** a turn-detector model waits
  for a completed thought instead of just silence. Raw VAD talks over the clinic
  agent's mid-sentence pauses ("let me check that for you..."), which reads as
  glitchy turn-taking -- the exact thing the challenge grades first.
- **Interruptions enabled for every scenario:** `InterruptionOptions(enabled=True)`
  lets the clinic agent interrupt our bot's playback, which is what produces
  natural turn-taking. (The flag controls whether the *remote party* may interrupt
  *our* playback -- disabling it is what causes talk-over, not the reverse.)
- **Function-tool hangup vs. fixed turn count:** the patient decides when it's done, so
  calls end naturally instead of on a rigid script length.
- **Known limitation -- greeting race:** Twilio fetches the TwiML bridge only after
  the clinic agent answers, so ~2-3s of the opening greeting can be lost from the
  transcript/recording (the agent hears ringback, then re-greets). The patient's
  opening line is robust to a missed greeting, and the full outbound-SIP topology
  that eliminates the race is documented as a v2 -- it trades the Flask server and
  ngrok for worker-side audio capture and an outbound SIP trunk.
