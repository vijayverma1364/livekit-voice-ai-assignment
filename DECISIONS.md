# Architectural Decision Records (ADR)

This log documents the key technical decisions, context, and trade-offs made while designing and building the Supervised Voice AI platform on self-hosted LiveKit.

---

## ADR-001: PostgreSQL for Durable Persistence

### Context
Voice calls generate concurrent streams of transcripts, latency benchmarks, and compliance audits. During an active call, multiple asynchronous tasks write turn events and metrics simultaneously. SQLite was initially considered for simple local setup, but its file-level write lock causes serialization bottlenecks and `database is locked` errors under concurrent worker load.

### Decision
We use PostgreSQL (16+) as the primary datastore for all persistent domain entities (`agents`, `calls`, `transcript_entries`, `latency_measurements`, and `compliance_results`).

### Consequences & Trade-offs
- Writing transcripts concurrently from background tasks works reliably without lock contention.
- We leverage native PostgreSQL capabilities: UUID primary keys, JSONB for flexible metadata, and strict check constraints for the call state machine.
- Requires running a local Postgres container during development (handled via Docker Compose).

---

## ADR-002: Stateless FastAPI Backend Control Plane

### Context
WebRTC signaling and voice processing require resilient session handling. If backend state is stored in memory dictionaries on the HTTP server, any restart, redeployment, or horizontal scaling immediately breaks active session tracking.

### Decision
The FastAPI backend is strictly stateless. No process-global in-memory dictionaries (such as `active_calls = {}`) serve as the source of truth. All call lifecycle transitions, tokens, and configurations are queried and written directly to PostgreSQL.

### Consequences & Trade-offs
- Any FastAPI instance can handle any incoming request behind a standard load balancer.
- LiveKit manages real-time media streaming and WebRTC room state; FastAPI manages metadata, authentication, and HTTP APIs.
- Eliminates memory synchronization issues between multi-worker deployments.

---

## ADR-003: Decoupled Voice Agent Worker

### Context
Voice streaming, VAD inference, audio packet buffering, and WebSocket pipeline processing require high-frequency, non-blocking event loops. Running this directly inside the FastAPI web server process would degrade HTTP API response times and complicate scaling.

### Decision
The Voice AI Agent runs as a standalone Python process using LiveKit Agents framework, completely decoupled from the FastAPI backend.

### Consequences & Trade-offs
- We can scale voice worker processes independently from HTTP API instances based on concurrent call volume.
- The worker uses LiveKit's native dispatch protocol to pick up room jobs automatically.
- Development requires running two Python processes (API server and agent worker), orchestrated via dev scripts or Docker Compose.

---

## ADR-004: React (Vite) Frontends with Vanilla CSS

### Context
The platform requires two separate client experiences:
1. **Customer Web UI**: Clean, single-call interface focused on audio connectivity, speaking indicators, and real-time transcripts.
2. **Supervisor Dashboard**: Administrative view supporting stealth listening, live multi-speaker transcripts, private whispers, and compliance review.

### Decision
Both client applications are built with React and Vite, styled using Vanilla CSS modules rather than heavy utility frameworks like Tailwind.

### Consequences & Trade-offs
- Full compatibility with the official `livekit-client` WebRTC SDK for track subscription, audio element management, and data channels.
- Fast build times and minimal bundle size.
- Clear separation between customer capabilities and supervisor privileges.

---

## ADR-005: Docker Compose for Local Development

### Context
The stack consists of multiple moving pieces: PostgreSQL, the self-hosted LiveKit SFU, FastAPI backend, LiveKit voice worker, and two frontend applications. Manually configuring port mappings and service dependencies slows down onboarding and causes environment drift.

### Decision
We provide a centralized `docker-compose.yml` with health checks (`pg_isready`, LiveKit HTTP probe, FastAPI `/health`) to orchestrate the entire platform locally with a single command.

### Consequences & Trade-offs
- Developers can launch the entire stack with `docker compose up --build`.
- Developers can also run individual services natively against containerized dependencies by pointing environment variables to local ports.

---

## ADR-006: Environment Variable Configuration

### Context
The application relies on external API keys (OpenAI, Deepgram) and infrastructure secrets (LiveKit keys, Postgres credentials). Hardcoding or committing these credentials presents a critical security risk.

### Decision
All configuration and secrets are read from environment variables loaded via `.env` files using Pydantic Settings.

### Consequences & Trade-offs
- `.env` is excluded in `.gitignore` and `.dockerignore`.
- `.env.example` serves as the single reference for required environment variables across the backend, worker, and frontends.

---

## ADR-007: Relational Schema & Unified Compliance Model

### Context
Compliance audits evaluate two rules per call:
1. Deterministic Rule 1: Agent must state the recording disclosure within the first 30 seconds.
2. LLM-evaluated Rule 2: Agent must never promise a refund.
Call disconnect events can trigger repeatedly (browser refresh, network drop, timeout), risking duplicate audit records.

### Decision
We model compliance results as a 1-to-1 table (`compliance_results`) with a unique constraint on `call_id`. Transcripts include an `is_private` boolean to partition supervisor coaching whispers from customer-visible transcripts.

### Consequences & Trade-offs
- Compliance audits are idempotent: repeated calls to finalize a session perform safe upserts without creating orphan records.
- Queries can reliably filter out supervisor whispers from customer-facing views (`WHERE is_private = false`).
- Alembic migrations provide version-controlled schema evolution.

---

## ADR-008: Room Dispatch & Supervisor Security

### Context
When a customer starts a call, the voice worker needs to know which agent prompt, voice, and model to load. Additionally, when a supervisor connects to listen, the supervisor must never appear in the customer's call UI or transmit accidental microphone audio into the room.

### Decision
1. When `POST /calls` creates a session, the backend creates the LiveKit room with metadata containing `agent_id`. When the worker joins, it reads this metadata and loads the appropriate agent configuration from PostgreSQL.
2. The `POST /calls/{id}/supervisor-token` endpoint mints a restricted JWT token with `can_publish=False, can_subscribe=True, hidden=True, can_publish_data=True`.

### Consequences & Trade-offs
- The worker dynamically configures its system prompt, voice, and model on a per-call basis without restarts.
- The supervisor is completely invisible to the customer client: no audio can be published to the room, but the supervisor can listen to audio tracks and send coaching notes via LiveKit data channels (`topic: "whisper"`).

---

## ADR-009: Idempotent Post-Call Finalization

### Context
WebRTC clients frequently fire multiple disconnect signals when a user navigates away or closes a tab. Calling transcript flush, compliance evaluation, and call closure on every event could waste LLM API tokens or create duplicate database entries.

### Decision
All finalization logic in both the worker teardown and the backend API (`POST /calls/{id}/finalize`) is idempotent. The system checks if compliance has already been evaluated for the call before invoking the evaluation pipeline.

### Consequences & Trade-offs
- Finalization can be called safely from worker event handlers, client unload hooks, or administrative triggers.
- Future work can move the finalization step into an asynchronous task queue (e.g. Celery / SQS) without changing the database schema or API contract.

---

## ADR-010: Failure Handling & Error Transparency

### Context
In voice AI systems, upstream speech-to-text, LLM, or TTS providers can experience transient timeouts or rate limits. Silently faking success or ignoring pipeline errors leads to corrupted transcripts and false compliance passes.

### Decision
We implement explicit failure containment across service boundaries:
- If provider credentials are missing or the model fails during compliance evaluation, the system marks the call as `FAILED` or records `pass=False` with error details rather than producing a false positive.
- When all human participants disconnect from a LiveKit room, the worker terminates the session promptly, avoiding lingering orphaned processes.

### Consequences & Trade-offs
- Audit logs and compliance records reflect true system state.
- Voice sessions clean up media server sockets promptly on participant disconnect.

---

## ADR-011: Multi-Worker Isolation Architecture

### Context
Processing concurrent voice streams involves audio resampling, VAD inference, and real-time streaming sockets. Shared memory structures between concurrent calls lead to state leakage, cross-talk bugs, or shared crashes.

### Decision
Each call handled by the worker uses an isolated `CallSessionState` instance containing its own latency tracker, whisper buffer, and transcript flush tasks. In production, workers run as multiple container replicas assigned jobs by LiveKit's distributed scheduler.

### Consequences & Trade-offs
- One call encountering an error or barge-in has zero effect on any other active call.
- The application scales horizontally by spinning up additional worker containers as call traffic grows.

---

## ADR-012: Container Startup Sequencing & Healthchecks

### Context
In multi-container setups, race conditions often occur if dependent services (like the backend API or voice worker) attempt to connect before PostgreSQL or the LiveKit server have fully bound their listening ports.

### Decision
Our `docker-compose.yml` uses Docker health checks (`pg_isready` for Postgres, HTTP readiness probes for LiveKit and FastAPI) alongside `condition: service_healthy` dependencies.

### Consequences & Trade-offs
- Services start in strict dependency order: Postgres & LiveKit -> Backend migrations & API -> Agent worker & Frontends.
- Eliminates connection retry crashes during initial stack startup.
