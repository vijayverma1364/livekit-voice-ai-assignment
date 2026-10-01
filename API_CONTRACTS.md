# API Contracts Specification

This document defines the REST API contracts exposed by the FastAPI backend for the **Supervised Voice AI Agent on Self-Hosted LiveKit** platform.

Base URL: `http://localhost:8000` (Local) / `http://<backend_host>:8000`

---

## 1. System Health

### `GET /health`
Returns the operational status of the backend and its upstream dependencies (PostgreSQL, LiveKit).

#### Request
No parameters or payload required.

#### Response: `200 OK`
```json
{
  "status": "healthy",
  "timestamp": "2026-09-30T13:00:00.000Z",
  "dependencies": {
    "database": "connected",
    "livekit": "connected"
  },
  "version": "1.0.0"
}
```

#### Error Response: `503 Service Unavailable`
```json
{
  "status": "unhealthy",
  "timestamp": "2026-09-30T13:00:00.000Z",
  "dependencies": {
    "database": "disconnected",
    "livekit": "connected"
  },
  "detail": "Failed to connect to database"
}
```

---

## 2. Agent Management

### `POST /agents`
Creates a new AI agent configuration profile with custom system prompts, voice attributes, and LLM hyperparameters.

#### Request Body
```json
{
  "name": "Customer Support Tier 1",
  "system_prompt": "You are a courteous customer support assistant for Acme Corp. Start the call by notifying the customer that the call is being recorded for quality assurance. Answer questions politely and concisely.",
  "voice": "alloy",
  "model": "gpt-4o-mini"
}
```

#### Field Validation Rules
| Field | Type | Required | Default | Validation |
|---|---|---|---|---|
| `name` | `string` | Yes | - | `1 <= len <= 255` |
| `system_prompt` | `string` | Yes | - | `min_length: 1` |
| `voice` | `string` | No | `"alloy"` | `1 <= len <= 100` |
| `model` | `string` | No | `"gpt-4o-mini"` | `1 <= len <= 100` |

#### Response: `201 Created`
```json
{
  "id": "e4b5a2e1-8d2a-4933-bf9c-29b4e7fa0001",
  "name": "Customer Support Tier 1",
  "system_prompt": "You are a courteous customer support assistant...",
  "voice": "alloy",
  "model": "gpt-4o-mini",
  "created_at": "2026-09-30T13:00:00.000Z",
  "updated_at": "2026-09-30T13:00:00.000Z"
}
```

#### Error Responses
- `422 Unprocessable Entity`: Validation failure on input schema.
```json
{
  "detail": [
    {
      "loc": ["body", "temperature"],
      "msg": "Input should be less than or equal to 2.0",
      "type": "less_than_equal"
    }
  ]
}
```

---

### `GET /agents/{id}`
Retrieves an existing agent configuration profile by its UUID.

#### Parameters
- Path: `id` (`UUID`, Required) — The unique agent ID.

#### Response: `200 OK`
```json
{
  "id": "e4b5a2e1-8d2a-4933-bf9c-29b4e7fa0001",
  "name": "Customer Support Tier 1",
  "system_prompt": "You are a courteous customer support assistant...",
  "voice_id": "alloy",
  "llm_model": "gpt-4o-mini",
  "temperature": 0.70,
  "max_tokens": 256,
  "is_active": true,
  "created_at": "2026-09-30T13:00:00.000Z",
  "updated_at": "2026-09-30T13:00:00.000Z"
}
```

#### Error Responses
- `404 Not Found`: Agent with specified UUID does not exist.
```json
{
  "detail": "Agent not found"
}
```
- `422 Unprocessable Entity`: Invalid UUID format in path.

---

## 3. Call Lifecycle & Session Management

### `POST /calls`
Initiates a voice call session. Allocates a unique LiveKit room, binds the call to the specified agent configuration, stores the session record in PostgreSQL, and generates a LiveKit participant access token for the customer client.

#### Request Body
```json
{
  "agent_id": "e4b5a2e1-8d2a-4933-bf9c-29b4e7fa0001",
  "room_name": "optional-custom-room-name",
  "customer_identity": "customer-alice-456",
  "customer_name": "Alice"
}
```

#### Field Validation Rules
| Field | Type | Required | Default | Validation |
|---|---|---|---|---|
| `agent_id` | `UUID` | Yes | - | Must exist in `agents` table |
| `room_name` | `string` | No | `call-<uuid>` | `1 <= len <= 255` |
| `customer_identity` | `string` | No | `customer-<uuid>` | `1 <= len <= 255` |
| `customer_name` | `string` | No | `null` | `1 <= len <= 255` |

#### Response: `201 Created`
```json
{
  "call_id": "c1a2b3c4-9876-4321-abcd-ef0123456789",
  "agent_id": "e4b5a2e1-8d2a-4933-bf9c-29b4e7fa0001",
  "room_name": "call-c1a2b3c4-9876-4321-abcd-ef0123456789",
  "status": "CREATED",
  "customer_identity": "customer-alice-456",
  "livekit_url": "ws://localhost:7880",
  "livekit_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "created_at": "2026-09-30T13:05:00.000Z"
}
```

#### Error Responses
- `404 Not Found`: The specified `agent_id` does not exist.
```json
{
  "detail": "Agent not found"
}
```
- `500 Internal Server Error`: Failed to mint LiveKit access token or persist call to database.

---

### `GET /calls/{id}`
Retrieves detailed state, transcripts, latency metrics, and compliance evaluations for a call session.

#### Parameters
- Path: `id` (`UUID`, Required) — The call ID.
- Query: `include_private` (`boolean`, Optional, default `false`) — If `true`, returns supervisor whisper transcripts (`is_private = true`). Defaults to `false` to guarantee customer privacy and prevent supervisor leak.

#### Response: `200 OK`
```json
{
  "id": "c1a2b3c4-9876-4321-abcd-ef0123456789",
  "agent_id": "e4b5a2e1-8d2a-4933-bf9c-29b4e7fa0001",
  "room_name": "call-c1a2b3c4-9876-4321-abcd-ef0123456789",
  "status": "ENDED",
  "started_at": "2026-09-30T13:05:05.120Z",
  "ended_at": "2026-09-30T13:06:18.450Z",
  "created_at": "2026-09-30T13:05:00.000Z",
  "transcripts": [
    {
      "id": "t1-...",
      "call_id": "c1a2b3c4-9876-4321-abcd-ef0123456789",
      "speaker": "agent",
      "text": "Hello Alice, thanks for reaching out. Please note this call is recorded for quality and training.",
      "relative_time_ms": 1250,
      "is_private": false,
      "timestamp": "2026-09-30T13:05:06.370Z"
    },
    {
      "id": "t2-...",
      "call_id": "c1a2b3c4-9876-4321-abcd-ef0123456789",
      "speaker": "customer",
      "text": "Hi, I have a billing question regarding my invoice.",
      "relative_time_ms": 4800,
      "is_private": false,
      "timestamp": "2026-09-30T13:05:09.920Z"
    }
  ],
  "latency_measurements": [
    {
      "id": "l1-...",
      "call_id": "c1a2b3c4-9876-4321-abcd-ef0123456789",
      "turn_number": 1,
      "user_stop_ms": 1000,
      "stt_final_ms": 1180,
      "llm_first_token_ms": 1470,
      "tts_first_audio_ms": 1620,
      "audio_published_ms": 1670,
      "created_at": "2026-09-30T13:05:10.000Z"
    }
  ],
  "compliance_result": {
    "id": "c1-...",
    "call_id": "c1a2b3c4-9876-4321-abcd-ef0123456789",
    "recording_rule_pass": true,
    "recording_rule_details": {
      "disclosure_offset_ms": 1250,
      "threshold_ms": 30000
    },
    "refund_rule_pass": true,
    "refund_offending_line": null,
    "checked_at": "2026-09-30T13:06:19.000Z"
  }
}
```

#### Error Responses
- `404 Not Found`: Call session does not exist.
```json
{
  "detail": "Call not found"
}
```

---

## 4. Supervisor Integration Endpoint

### `POST /calls/{id}/supervisor-token`
Generates a restricted LiveKit access token for a supervisor to join the active call room. The supervisor token grants:
- **Audio Subscribe ONLY** (cannot publish microphone to the room's main audio mix).
- **Data Channel Publish ONLY** (allows sending private whisper messages via LiveKit data channel).
- **Hidden Participant Flag** (does not emit participant join notifications to standard customer UI).

#### Parameters
- Path: `id` (`UUID`, Required) — The call ID.

#### Request Body
```json
{
  "supervisor_identity": "supervisor-dan-789"
}
```

#### Response: `200 OK`
```json
{
  "call_id": "c1a2b3c4-9876-4321-abcd-ef0123456789",
  "room_name": "call-c1a2b3c4-9876-4321-abcd-ef0123456789",
  "supervisor_identity": "supervisor-dan-789",
  "livekit_url": "ws://localhost:7880",
  "livekit_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```
