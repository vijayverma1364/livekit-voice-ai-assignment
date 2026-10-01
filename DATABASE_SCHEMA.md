# Database Schema Specification

This document details the relational data model for the **Supervised Voice AI Agent on Self-Hosted LiveKit** platform. The persistent store is PostgreSQL (14+), serving as the single durable source of truth for configuration, call lifecycles, real-time transcripts, latency diagnostics, and post-call compliance audits.

---

## 1. Entity Relationship Overview

```
                      +-------------------+
                      |      agents       |
                      +-------------------+
                                | 1
                                |
                                | N (ON DELETE RESTRICT)
                      +-------------------+
                      |       calls       |
                      +-------------------+
                         |      |       |
            +------------+      |       +------------+
            | 1                 | 1                  | 1
            |                   |                    |
            | N (CASCADE)       | N (CASCADE)        | 1 (CASCADE, UNIQUE)
+--------------------+ +--------------------+ +--------------------+
| transcript_entries | |latency_measurements| | compliance_results |
+--------------------+ +--------------------+ +--------------------+
```

---

## 2. Table Specifications

### 2.1 `agents`
Stores configuration profiles and behavioral parameters for AI voice agents. Each call references one agent profile, allowing dynamic, database-driven prompt engineering and voice customization.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | `PRIMARY KEY`, default `uuid_generate_v4()` | Unique agent identifier |
| `name` | `VARCHAR(255)` | `NOT NULL` | Human-readable name (e.g., "Acme Support Agent") |
| `system_prompt` | `TEXT` | `NOT NULL` | System prompt controlling agent behavior and policy adherence |
| `voice` | `VARCHAR(100)` | `NOT NULL`, default `'alloy'` | Voice synthesis model identifier (TTS voice ID) |
| `model` | `VARCHAR(100)` | `NOT NULL`, default `'gpt-4o-mini'` | LLM model identifier (e.g., `gpt-4o-mini`, `gpt-4o`) |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, default `CURRENT_TIMESTAMP` | Profile creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL`, default `CURRENT_TIMESTAMP` | Last modification timestamp |

---

### 2.2 `calls`
Maintains the lifecycle, state, duration, and participant mapping of every voice call session.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | `PRIMARY KEY`, default `uuid_generate_v4()` | Unique call session identifier |
| `agent_id` | `UUID` | `NOT NULL`, `REFERENCES agents(id) ON DELETE RESTRICT` | Agent profile driving this session |
| `room_name` | `VARCHAR(255)` | `NOT NULL`, `UNIQUE` | Unique LiveKit room identifier |
| `status` | `VARCHAR(50)` | `NOT NULL`, default `'CREATED'`, `CHECK (status IN ('CREATED', 'CONNECTING', 'ACTIVE', 'ENDED', 'FAILED'))` | Explicit real-time call lifecycle state |
| `started_at` | `TIMESTAMPTZ` | Nullable | Exact timestamp customer connected or speech started |
| `ended_at` | `TIMESTAMPTZ` | Nullable | Exact timestamp call session terminated |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, default `CURRENT_TIMESTAMP` | Initial record creation timestamp |

**Indexes:**
- `idx_calls_agent_id` on `(agent_id)`: Agent performance and lookup.
- `idx_calls_room_name` on `(room_name)`: Fast lookup when LiveKit webhooks/workers reference the room name.
- `idx_calls_status` on `(status)`: Filter active vs. completed calls.
- `idx_calls_created_at` on `(created_at DESC)`: Chronological listing in supervisor dashboards.

---

### 2.3 `transcript_entries`
Stores conversational utterances in real time. Supports isolation between customer-visible speech and private supervisor whispers.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | `PRIMARY KEY`, default `uuid_generate_v4()` | Unique transcript entry ID |
| `call_id` | `UUID` | `NOT NULL`, `REFERENCES calls(id) ON DELETE CASCADE` | Associated call session |
| `timestamp` | `TIMESTAMPTZ` | `NOT NULL`, default `CURRENT_TIMESTAMP` | Wall-clock timestamp of utterance |
| `speaker` | `VARCHAR(50)` | `NOT NULL`, `CHECK (speaker IN ('customer', 'agent', 'supervisor'))` | Speaker role |
| `text` | `TEXT` | `NOT NULL` | Utterance transcript text |
| `relative_time_ms` | `BIGINT` | `NOT NULL`, `CHECK (relative_time_ms >= 0)` | Milliseconds offset from session start |
| `is_private` | `BOOLEAN` | `NOT NULL`, default `false` | If `true`, utterance is strictly private (supervisor whisper) |

**Indexes:**
- `idx_transcripts_call_id` on `(call_id)`: Quick retrieval of entire call history.
- `idx_transcripts_timestamp` on `(timestamp ASC)`: Wall-clock chronological ordering.
- `idx_transcripts_relative_time` on `(call_id, relative_time_ms ASC)`: Fast ordered replay of conversation turns.

---

### 2.4 `latency_measurements`
Captures granular pipeline timing metrics per conversational turn to ensure SLA tracking (VAD speech end -> STT -> LLM first token -> TTS first chunk -> Audio playback).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | `PRIMARY KEY`, default `uuid_generate_v4()` | Unique measurement record ID |
| `call_id` | `UUID` | `NOT NULL`, `REFERENCES calls(id) ON DELETE CASCADE` | Associated call session |
| `turn_number` | `INTEGER` | `NOT NULL`, `CHECK (turn_number >= 0)` | Sequential dialogue turn index |
| `user_stop_ms` | `BIGINT` | Nullable | Millisecond timestamp VAD detected end of user speech |
| `stt_final_ms` | `BIGINT` | Nullable | Millisecond timestamp STT emitted final transcript |
| `llm_first_token_ms` | `BIGINT` | Nullable | Millisecond timestamp first LLM token stream arrived |
| `tts_first_audio_ms` | `BIGINT` | Nullable | Millisecond timestamp first audio chunk synthesized by TTS |
| `audio_published_ms`| `BIGINT` | Nullable | Millisecond timestamp audio frame sent into LiveKit room |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL`, default `CURRENT_TIMESTAMP` | Insertion timestamp |

**Unique Constraint:**
- `uq_latency_call_turn`: `UNIQUE (call_id, turn_number)` prevents duplicate turn telemetry writes (idempotent updates).

**Indexes:**
- `idx_latency_call_id` on `(call_id)`: Fast turn retrieval and aggregation for turn-by-turn latencies.

---

### 2.5 `compliance_results`
Stores automated post-call compliance verification evaluations for both recording disclosure and refund policy checks.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | `PRIMARY KEY`, default `uuid_generate_v4()` | Unique compliance result ID |
| `call_id` | `UUID` | `NOT NULL`, `REFERENCES calls(id) ON DELETE CASCADE`, `UNIQUE` | 1-to-1 association with call session |
| `recording_rule_pass` | `BOOLEAN` | `NOT NULL` | True if recording disclosure was made within 30s |
| `recording_rule_details`| `JSONB` | Nullable | Details (e.g. `{"disclosure_offset_ms": 1200, "threshold_ms": 30000}`) |
| `refund_rule_pass` | `BOOLEAN` | `NOT NULL` | True if agent did not promise an unauthorized refund |
| `refund_offending_line` | `TEXT` | Nullable | Offending utterance quote if failed |
| `checked_at` | `TIMESTAMPTZ` | `NOT NULL`, default `CURRENT_TIMESTAMP` | Timestamp of compliance evaluation |

**Unique Constraint:**
- `uq_compliance_call`: `UNIQUE (call_id)` enforces strict 1-to-1 relation, guaranteeing that repeated post-call finalization calls safely update the existing row rather than creating duplicates.

**Indexes:**
- `idx_compliance_call_id` on `(call_id)`: Quick compliance audit retrieval on call lookup.

---

## 3. Idempotency & Concurrency Guarantees

1. **Upsert Safety**: All post-call writes (`compliance_results`, `latency_measurements`) utilize composite unique keys (`call_id` for compliance, `(call_id, turn_number)` for latency). Multiple call completion events (e.g., duplicated webhooks or concurrent worker teardowns) will safely update existing records without duplicate insertions.
2. **Cascade Deletions**: Deleting a call record cascades to all related transcripts, latency metrics, and compliance evaluations, preventing orphaned data.
3. **Agent Referential Integrity**: Agents cannot be deleted while referenced by existing calls (`ON DELETE RESTRICT`).
