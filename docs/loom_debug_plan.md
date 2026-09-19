# AI debugging video plan — screen recording, narrate your prompts

Pick ONE real bug from your build session and show the full loop. Reviewers
want to see your prompts, your judgment about which suggestion to take, and
iteration — not a one-shot paste.

**Structure:**
1. Show the broken behavior (failing test, bad audio, or a traceback).
2. Paste the error + the relevant code into the AI. Read your prompt out loud
   and explain *why* you asked it that way.
3. Apply the fix, re-run, show it passing. If the first fix fails, keep going —
   the recovery is the interesting part.

**Good candidates already in this codebase** (if you hit them live):
- Twilio's recording-ready race → the retry-with-backoff fix in `recording.py`
  (callback fires before the media is downloadable; first attempts 404).
- SIP trunk auth failure → wiring `SIP_TRUNK_USER`/`SIP_TRUNK_PASSWORD`
  through the `<Sip>` element in `server.py`.
- Worker not joining before the call lands → the dispatch-then-wait in
  `runner.py`.

**Don't** stage a fake bug. **Do** keep it under ~5 minutes and leave your
thinking audible.
