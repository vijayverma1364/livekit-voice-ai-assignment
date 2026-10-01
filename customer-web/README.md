# Customer Web Client (Phase 5)

A React single-page application providing a voice interface for customers to converse with the Voice AI Agent over self-hosted LiveKit WebRTC.

---

## Features

- **Agent Selector**: Dynamically fetches active Voice AI agents configured in PostgreSQL via `GET /agents`.
- **Call Lifecycle Management**: Initiates calls via `POST /calls` to receive session ID, room name, and LiveKit WebRTC tokens.
- **WebRTC Audio Streaming**:
  - Automatically captures browser microphone input and publishes audio to LiveKit.
  - Subscribes to the agent's audio track and routes playback to the user's speakers.
- **Connection & Microphone Telemetry**: Real-time status indicators for call connectivity (`IDLE`, `CONNECTING`, `LIVE CALL`, `ENDED`, `ERROR`), active speaker waveforms, and microphone state (`Live & Transmitting`, `Muted`, `Standby`).
- **Live Transcript Feed**:
  - Displays conversation turns with explicit `USER` or `AGENT` labels on every line.
  - Respects supervisor privacy by strictly filtering out supervisor whisper messages (`include_private=false`).
- **Clean Separation of Concerns**:
  - Zero durable state held on the frontend.
  - Zero backend secrets, database passwords, or provider keys bundled into client code.
  - API communication encapsulated in `src/services/api.js` and WebRTC room logic isolated in `src/hooks/useLiveKitCall.js`.

---

## Architecture Flow

```
Customer Browser
      │
      ├── 1. GET /agents ───────────────► FastAPI Backend (:8000)
      │                                       │ (Queries DB)
      │◄── Available Agents List ─────────────┘
      │
      ├── 2. POST /calls ───────────────► FastAPI Backend (:8000)
      │   (agent_id, customer_name)           │
      │                                       ├─► Pre-creates LiveKit Room
      │                                       └─► Generates JWT Access Token
      │◄── {call_id, room_name, token} ───────┘
      │
      ├── 3. Connect (token) ───────────► LiveKit SFU (:7880)
      │                                       │
      ├── 4. Publish Microphone ──────────────┤ (Customer Audio Stream)
      │                                       │
      │◄── 5. Subscribe Agent Audio ──────────┤ (AI Voice Playback)
      │                                       │
      └── 6. GET /calls/{id} ───────────► FastAPI Backend (:8000)
          (Live Transcript Polling)           │ (Streams non-private turns)
```

---

## Configuration

Environment variables can be set via `.env`:

```bash
VITE_API_URL=http://localhost:8000
VITE_LIVEKIT_URL=ws://localhost:7880
```

---

## Development

```bash
# Install dependencies
npm install

# Start development server on port 3000
npm run dev

# Build production bundle
npm run build

# Run linter
npm run lint
```
