# Voice AI Agent Worker (Phase 4)

Autonomous real-time Python voice agent worker service built on the `livekit-agents` framework (v1.8+), connecting to the containerized self-hosted LiveKit SFU.

---

## 1. Architectural Overview

The agent worker operates as an independent service decoupled from the FastAPI backend and browser clients. It connects to the LiveKit SFU over WebSocket (`ws://localhost:7880`) and executes dynamic voice conversational pipelines per assigned room.

```
Customer Audio (WebRTC)
     ↓
Silero VAD (ONNX Voice Activity Detection)
     ↓
Turn Detection & Endpointing (0.5s - 3.0s)
     ↓
Speech-to-Text (STT) [OpenAI Whisper / Deepgram Nova-3]
     ↓
Large Language Model (LLM) [OpenAI GPT-4o-mini with DB System Prompt]
     ↓
Text-to-Speech (TTS) [OpenAI TTS / StreamAdapter]
     ↓
LiveKit Audio Publication (WebRTC)
     ↓
Customer Audio Playback
```

---

## 2. Directory Structure

```
agent/
├── src/
│   ├── config.py             # Settings (LiveKit credentials, DB URL, timeouts)
│   ├── db.py                 # Async PostgreSQL client for Agent, Call & Transcripts
│   ├── pipeline.py           # Pipeline factory (Silero VAD, STT, LLM, TTS, StreamAdapter)
│   ├── interruption.py       # VAD barge-in rules and interruption event monitoring
│   ├── session_manager.py    # Isolated per-call CallSessionState & transcript persistence
│   ├── worker.py             # LiveKit worker entrypoint (CLI & room dispatcher)
│   ├── verify_call.py        # Automated end-to-end voice call verification runner
│   └── mock_providers.py     # Offline mock STT/LLM/TTS for deterministic CI testing
├── Dockerfile                # Production container specification
├── requirements.txt          # Python dependencies
└── README.md
```

---

## 3. Dynamic Database Configuration

In compliance with the architecture contract, the system prompt, model name, voice ID, and agent persona are **never hard-coded** in the agent worker code.

1. When a room assignment arrives, the worker resolves `call_record` and `agent_id` from PostgreSQL.
2. It fetches the `Agent` record:
   - `name`: Fictional company agent name (e.g. "Acme Support Agent")
   - `system_prompt`: Professional support persona, early recording disclosure requirement, strict refund prohibition, supervisor stealth adherence.
   - `voice`: Preferred voice timbre (e.g. "alloy", "shimmer", "nova")
   - `model`: LLM model identifier (e.g. "gpt-4o-mini", "gpt-4o")
3. The prompt is dynamically injected into `Agent(instructions=agent_config.system_prompt)`.

---

## 4. Barge-In & Interruption Handling

Interruption is handled immediately at the VAD turn boundary:
1. **Immediate Halt**: When Silero VAD detects customer speech while the agent is speaking (`mode="vad"`, `min_duration=0.2s`), the engine immediately calls `session.interrupt()`.
2. **Buffer Flush**: Remaining audio frames queued in the WebRTC publication pipeline are dropped immediately.
3. **Transcript Alignment**: With `use_tts_aligned_transcript=True`, the unspoken part of the LLM sentence is truncated from conversation history (`session.history`). The agent does **not** assume the full sentence was spoken.
4. **State Transition**: The agent switches to listening state, transcribes customer speech, and generates a contextually aware follow-up.

---

## 5. Running the Agent Worker

### Direct CLI Execution
```bash
# Development mode (auto-reload on code change)
python -m agent.src.worker dev

# Production daemon mode
python -m agent.src.worker start

# Connect directly to a specific room
python -m agent.src.worker connect --room <room_name>
```

### Docker Container Execution
```bash
docker compose --profile full-stack up agent
```

---

## 6. End-to-End Voice Call Verification

Run the automated verification script against the live containerized LiveKit SFU:

```bash
# Using configured OpenAI credentials from .env
python -m agent.src.verify_call

# Using mock providers for offline / CI validation
python -m agent.src.verify_call --mock
```

Verification verifies:
- Customer audio reaches agent via WebRTC
- STT works
- LLM works
- TTS works
- Agent audio reaches customer
- VAD works
- Turn detection works
- Recording disclosure happens early (< 30s)
- Barge-in interruption stops agent speech immediately
- PostgreSQL system prompt is loaded and used

---

## 7. Provider Limitations & Operational Considerations

1. **OpenAI TTS Streaming**: OpenAI TTS (`/v1/audio/speech`) does not support native bi-directional audio streaming. We wrap it with LiveKit's `StreamAdapter` to break sentences into synthesized audio chunks and achieve low time-to-first-byte (TTFB).
2. **Deepgram STT WebSocket Latency**: Deepgram provides native streaming WebSocket STT with interim results and endpointing; recommended for sub-300ms turn transitions when `DEEPGRAM_API_KEY` is provided.
3. **Network UDP Ports**: Self-hosted LiveKit requires UDP ports `50000-50100` open on the host for WebRTC media exchange.
