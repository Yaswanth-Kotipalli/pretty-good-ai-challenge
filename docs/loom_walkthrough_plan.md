# Loom walkthrough plan — max 3 minutes, webcam ON, your voice

Rehearse with a timer. Energy and clarity beat perfection; this is the most
important deliverable after the calls themselves.

**0:00–0:20 — The pitch.** Who you are, what you built: "a patient simulator
that calls Pretty Good AI's test line and stress-tests their voice agent like
a real patient — 12 scenarios, from routine scheduling to edge cases."

**0:20–1:00 — Architecture, one screen.** LiveKit Agents pipeline
(Deepgram → gpt-4o-mini → OpenAI TTS), Twilio as the dumb phone carrier and
recorder, SIP bridge into the LiveKit room. Say *why*: the challenge requires
pipeline mode; Twilio's record-from-answer made both-sides audio bulletproof,
and the calls are what's graded first.

**1:00–2:00 — Play a real call.** 30–45 seconds of your best recording
(the impatient/interrupter one is the most fun). Show the transcript
scrolling alongside. Point out one natural moment ("it pushed back here
instead of reading a script").

**2:00–2:40 — Best bug.** Show the bug report entry, play the 15-second audio
clip. Explain why it matters for a real patient.

**2:40–3:00 — Close.** What you'd do next (Cartesia for latency, more adversarial
edge cases), repo link on screen: "I built this to find real bugs — here's
the code."

Checklist before uploading: public link, webcam visible, audio clear, ≤3:00.
