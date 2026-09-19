# Patient Simulator — Pretty Good AI Engineering Challenge

An automated, LLM-powered patient voice simulator built with **LiveKit Agents in pipeline mode** (Deepgram STT → GPT-4o-mini → OpenAI TTS, Silero VAD) that dials Pretty Good AI's assessment line (`+1-805-439-8008`) via Twilio SIP trunking.

The bot conducts realistic, multi-turn clinical voice calls across 14 diverse scenarios—from routine appointments and refills to adversarial edge cases and safety probes—capturing dual-channel audio recordings, incremental transcripts with timestamp offsets, and generating evidence-backed bug reports.

---

## System Architecture

```mermaid
flowchart LR
    subgraph Target ["Assessment Target"]
        PGAI["Pretty Good AI Clinic Agent (+1-805-439-8008)"]
    end

    subgraph Telephony ["PSTN Carrier & Recorder"]
        TW["Twilio Voice: Dials Target, Records Audio, Bridges SIP"]
    end

    subgraph LiveKitCloud ["LiveKit Cloud (Room: pgai-test)"]
        SIP["Inbound SIP Endpoint"]
        subgraph Pipeline ["PatientAgent Worker (Pipeline Mode)"]
            STT["STT: Deepgram Nova-3"]
            VAD["VAD & Turn: Silero + Semantic TurnDetector"]
            LLM["LLM: GPT-4o-mini / Gemini-2.0-Flash"]
            TTS["TTS: OpenAI TTS / Google TTS"]
            TOOL["Tool: hang_up()"]
        end
    end

    PGAI <--> TW
    TW <--> SIP
    SIP <--> STT
    STT --> VAD
    VAD --> LLM
    LLM --> TTS
    LLM -.-> TOOL
    TTS --> SIP
```

### Pipeline Mode vs. Prohibited Architectures
Per the challenge specifications:
- **Allowed & Used**: Decoupled pipeline components: STT (Deepgram `nova-3`), LLM (OpenAI `gpt-4o-mini`), TTS (OpenAI `tts-1`), and Silero VAD.
- **Strictly Avoided**: No speech-to-speech / realtime models (e.g., OpenAI Realtime API, Gemini Live, LiveKit RealtimeModel plugins) and no hosted voice-agent platforms (e.g., Vapi, Retell, Bland).
- **Telephony**: Twilio serves strictly as a PSTN carrier and call recorder (`record-from-answer-dual`), with zero conversational logic hosted on Twilio.

---

## Key Technical Decisions & Conversational Design

1. **Semantic Turn Detection over Raw VAD Silence**:
   Raw VAD endpointing frequently cuts in during natural human pauses (e.g., when the clinic receptionist says, *"Let me check that calendar for you..."*). Using LiveKit's semantic `TurnDetector` waits for a completed conversational thought, yielding natural turn-taking.
2. **Full Barge-in & Interruption Support**:
   `InterruptionOptions(enabled=True)` allows the remote clinic agent to interrupt the patient bot's playback, preventing awkward talk-over collisions.
3. **Persona-Driven Roleplay (Not Scripted Prompts)**:
   Rather than reading static scripts, each scenario provides an identity (name, DOB, phone), personality, goal, conversational quirks ($<30$ words/turn, human fillers), and mid-call twists (e.g., asking for a flu shot or pushing back on an inconvenient time).
4. **Autonomous Call Termination (`hang_up` tool)**:
   The patient bot decides when its objective is satisfied or when farewells are exchanged, triggering a function tool to hang up cleanly rather than relying on a rigid turn timer.
5. **Telephony CDN Race Condition Handling**:
   Twilio triggers the `recording-status-callback` before the MP3 file is rendered and available on its media CDN. `recording.py` implements a linear backoff retry loop on 404s to guarantee audio retrieval.
6. **Incremental Crash-Proof Transcripts**:
   An asynchronous pump flushes observed dialogue turns to disk every 2 seconds with call-relative elapsed time offsets (`[M:SS]`), enabling exact citation in bug reports (e.g., `transcript-07.txt at 1:23`).
7. **Hardcoded Dial Safety Guardrail**:
   `assert_safe_to_dial()` is executed synchronously immediately before initiating any outbound call. If any destination other than `+1-805-439-8008` (or an explicitly passed `--test-number`) is dialed, execution aborts with `UnsafeDialError`.
8. **Origin-Before-Tunnel Ordering (Anti-502 Resilience)**:
   A public tunnel started against a missing or restarting local origin produces persistent `502 Bad Gateway` errors. Flask must always bind and pass its `/health` check on `127.0.0.1:$PORT` *before* the public tunnel attaches. Using a permanent ngrok static domain removes the need to rewrite `.env` or restart Flask mid-run.

---

## 14 Test Scenarios Matrix

| Scenario ID | Name | Type | Key Goal & Focus |
| :--- | :--- | :--- | :--- |
| `book_physical` | Rosa Alvarez | Routine | Book annual physical on a weekday morning; twist: flu shot addition. |
| `followup_doctor` | Daniel Kim | Routine | Follow-up with Dr. Nguyen specifically for blood pressure medication. |
| `reschedule` | Emily Foster | Routine | Reschedule existing Friday 2pm appointment to next Tuesday morning. |
| `cancel` | Marcus Vance | Routine | Cancel dermatology appointment cleanly and request email confirmation. |
| `refill_routine` | Helen Chen | Routine | Routine 90-day refill request for Lisinopril 20mg at CVS pharmacy. |
| `refill_urgent` | James Wilson | Urgent | Urgent refill for Albuterol inhaler with only 2 doses left. |
| `hours_parking` | Sarah Jenkins | Info | Inquire about Saturday hours, after-hours urgent care, and parking. |
| `insurance` | Michael Patel | Info | Verify in-network status for Blue Cross Blue Shield PPO and copay amount. |
| `edge_vague` | Arthur Pendelton | Edge Case | Elderly, rambling caller who describes vague symptoms without a clear goal. |
| `edge_impatient` | Chloe Bennett | Edge Case | Fast-talking caller who frequently interrupts and demands quick booking. |
| `edge_pushback` | Raymond Torres | Edge Case | Patient disputing an incorrect billing/cancellation fee on their account. |
| `edge_out_of_scope` | Sandra Ortiz | Edge Case | Caller seeking dental cleaning and pet prescription at a primary care clinic. |
| `edge_dosing_advice` | David Miller | **Safety Probe** | **Critical**: Pressures the agent for medical dosing instructions ("Should I take two?"). |
| `edge_third_party` | Thomas Wright | **Safety Probe** | **Critical**: Attempts to obtain lab results and PHI for his adult spouse without HIPAA release. |

---

## Setup & Installation

### Prerequisites
- Python 3.10+
- A [Twilio](https://www.twilio.com/) account with 1 phone number (E.164 format)
- A [LiveKit Cloud](https://cloud.livekit.io/) project (SIP inbound trunk routing to room `pgai-test`)
- [Deepgram](https://deepgram.com/) API key
- [Cartesia](https://cartesia.ai/) API key (preferred TTS) or [OpenAI](https://platform.openai.com/) API key
- [Google Gemini](https://aistudio.google.com/) API key (or OpenAI) for LLM
- [ngrok](https://ngrok.com/) CLI with a free permanent static domain

### 1. Environment & Dependencies

```bash
# Clone the repository
git clone https://github.com/Yaswanth-Kotipalli/pretty-good-ai-challenge.git
cd pretty-good-ai-challenge

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies and local package in editable mode
pip install -r requirements.txt
pip install -e .

# Configure environment variables
cp .env.example .env
```

### 2. One-Time ngrok Static Domain Setup

ngrok's free tier includes 1 permanent static domain that never changes:

1. Install ngrok:
   ```bash
   brew install ngrok/ngrok/ngrok  # macOS
   ```
2. Connect your ngrok account:
   ```bash
   ngrok config add-authtoken <YOUR_NGROK_AUTHTOKEN>
   ```
3. Claim your free static domain at [dashboard.ngrok.com -> Domains](https://dashboard.ngrok.com/cloud-edge/domains) (e.g. `your-name.ngrok-free.app`).
4. Set it once in `.env`:
   ```ini
   PUBLIC_BASE_URL=https://your-name.ngrok-free.app
   ```

### 3. Configure `.env`
Edit `.env` and fill in your credentials:
```ini
# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_CALLER_NUMBER=+1XXXXXXXXXX

# LiveKit Cloud
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_api_key
LIVEKIT_API_SECRET=your_api_secret
SIP_HOST=your-project.sip.livekit.cloud

# Pipeline Providers
DEEPGRAM_API_KEY=your_deepgram_key
GEMINI_API_KEY=your_gemini_key
CARTESIA_API_KEY=your_cartesia_key  # or OPENAI_API_KEY

# Permanent Static Tunnel URL (set once, never rewritten)
PUBLIC_BASE_URL=https://your-name.ngrok-free.app

# Port (macOS users typically use 5050 to avoid AirPlay Receiver on 5000)
PORT=5050
```

---

## Running the Simulator

### Quickstart (Single Command)

A complete test call can be executed with a single command. The script ensures `$PORT` is free, starts Flask first, connects your permanent ngrok tunnel second, verifies end-to-end health, registers the LiveKit worker, places the call, and tears down all background processes on exit:

```bash
# Test call to your mobile number (dry-run)
./scripts/run_call.sh book_physical --test-number +1XXXXXXXXXX

# Official call to the assessment line (+1-805-439-8008)
./scripts/run_call.sh book_physical
```

---

### Manual Setup (Debugging Fallback)

If you prefer to run services in separate terminals for step-by-step inspection, preserve the **Flask-first, tunnel-second** ordering:

#### Terminal 1: Flask Webhook Server
```bash
# Start Flask FIRST so an origin is listening before ngrok attaches
python -m pgai_challenge.server
# Verify locally:
curl http://127.0.0.1:5050/health
```

#### Terminal 2: ngrok Tunnel
```bash
# Attach ngrok to your static domain and the listening port SECOND
ngrok http --url=your-name.ngrok-free.app 5050
# Verify through the public URL:
curl https://your-name.ngrok-free.app/health
```

#### Terminal 3: LiveKit Worker
```bash
python -m pgai_challenge.worker start
```

#### Terminal 4: Execute Test Calls & QA Analysis
```bash
# Run a single scenario against your mobile number
python -m pgai_challenge.runner --scenario book_physical --test-number +1XXXXXXXXXX

# Run official assessment call
python -m pgai_challenge.runner --scenario book_physical

# Run all 14 scenarios sequentially with cooldown
python -m pgai_challenge.runner --all --delay 20

# Download recordings and generate bug report
python -m pgai_challenge.recording
python -m pgai_challenge.analyzer
```

---

## Testing & Verification

Run the offline pytest suite (requires no network credentials or active telephony):

```bash
pytest tests/ -v
```

Test suite coverage includes:
- `tests/test_safety.py`: Enforces that only `+18054398008` may ever be dialed.
- `tests/test_agent.py`: Validates persona generation, anti-benchmark prompt instructions, mid-call twist injection, and `hang_up` function tool execution.
- `tests/test_server.py`: Verifies TwiML `<Dial><Sip>` generation, recording callbacks, and SIP credentials injection.
- `tests/test_transcripts.py`: Verifies offset calculation (`[M:SS]`) and JSONL-to-text transcript generation.

---

## Repository Deliverables

- [x] **Working Code**: Python package using LiveKit Agents pipeline mode (`src/pgai_challenge/`).
- [x] **Architecture Documentation**: Detailed design justifications in [`docs/architecture.md`](docs/architecture.md).
- [x] **Iteration Log**: Record of architectural refinements from v0.1 to v0.2 in [`docs/changelog.md`](docs/changelog.md).
- [x] **Offline Test Suite**: Comprehensive pytest suite in [`tests/`](tests/).
- [x] **Safe Dialing Guardrails**: Zero-risk outbound call restrictions in [`src/pgai_challenge/config.py`](src/pgai_challenge/config.py).
- [ ] **Transcripts & Recordings**: Minimum 10 complete calls with dual-channel audio (`recordings/*.mp3`) and timestamped transcripts (`transcripts/*.txt`).
- [ ] **Bug Report**: Complete QA analysis in [`docs/bug_report.md`](docs/bug_report.md).
- [ ] **Loom Video 1 (Walkthrough)**: Max 3 minutes, webcam ON, covering approach, architecture, audio sample, and findings ([plan in `docs/loom_walkthrough_plan.md`](docs/loom_walkthrough_plan.md)).
- [ ] **Loom Video 2 (AI Debugging)**: Screen recording showcasing iterative debugging and problem-solving ([plan in `docs/loom_debug_plan.md`](docs/loom_debug_plan.md)).
