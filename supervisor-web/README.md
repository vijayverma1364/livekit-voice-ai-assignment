# Supervisor Web Console (Phase 6)

A React single-page application providing a stealth dashboard for human supervisors to listen to ongoing calls and provide real-time private coaching whispers to the Voice AI agent over LiveKit WebRTC Data Channels.

---

## Features

- **Active Call Discovery**:
  - Dynamically fetches ongoing and recent call sessions from PostgreSQL (`GET /calls?limit=50`).
  - Supports manual entry of any Call ID (UUID).
- **Stealth Eavesdrop Audio Connection**:
  - Requests restricted supervisor access token via `POST /calls/{call_id}/supervisor-token`.
  - LiveKit grants strictly enforce `can_publish = false` (hardware-locked listen-only), `can_subscribe = true`, and `hidden = true` (invisible to customer).
  - Subscribes to customer and agent WebRTC audio tracks for real-time monitoring.
- **Private Data Channel Whisper**:
  - Dispatches confidential coaching directives over LiveKit WebRTC Data Channel (`topic: 'whisper'`).
  - Agent worker immediately integrates the instruction into its upcoming conversational turn.
  - Strict anti-disclosure rules prevent the agent from saying "My supervisor told me..." or revealing supervisor presence.
- **Supervisor Full Transcript Feed**:
  - Synchronizes all conversation turns with `include_private=true`.
  - Explicitly highlights confidential whispers with `[SUPERVISOR WHISPER] (🔒 Hidden from Customer)` badges.
- **Audio Stream Monitor**:
  - Visual activity waveforms indicating customer speech vs. agent speech in real time.

---

## Architecture Flow

```
Supervisor Browser (:3001)
      │
      ├── 1. GET /calls ────────────────► FastAPI Backend (:8000)
      │◄── Active Calls List ────────────┘
      │
      ├── 2. POST /calls/{id}/supervisor-token ──► FastAPI Backend (:8000)
      │◄── {room_name, stealth_token} ────────────┘
      │
      ├── 3. Connect (stealth_token) ───► LiveKit SFU (:7880)
      │   (can_publish=false, hidden=true)    │
      │                                       │
      │◄── 4. Subscribes Audio Tracks ────────┤ (Customer & Agent Audio)
      │                                       │
      └── 5. DataChannel.publishData() ───────┤
          (topic: 'whisper')                  ▼
                                     Agent Worker (Python)
                                     - Receives whisper
                                     - Records in DB (is_private=true)
                                     - Augments LLM prompt
                                     - Executes without disclosing supervisor
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

# Start development server on port 3001
npm run dev

# Build production bundle
npm run build

# Run linter
npm run lint

# Run automated tests
npm test
```
