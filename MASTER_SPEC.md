# Master Specification: Supervised Voice AI Agent on Self-Hosted LiveKit

This document serves as the formal project contract and specification for the take-home assignment: **"Supervised Voice AI Agent on Self-Hosted LiveKit"**.

All development across all phases must adhere to the boundaries, categories, and requirements established here.

---

## 1. Project Overview

The objective is to design, implement, and demonstrate a production-ready, scalable proof-of-concept (POC) for a real-time conversational voice AI agent. The platform provides:
1. Low-latency, full-duplex conversational voice via self-hosted LiveKit.
2. Robust voice processing: Speech-to-Text (STT), Large Language Model (LLM), and Text-to-Speech (TTS), integrated with Voice Activity Detection (VAD), turn detection, and user barge-in handling.
3. Live human supervisor capabilities: stealth eavesdropping (listen) and real-time private coaching (whisper via data channel).
4. Automated post-call compliance verification (deterministic timing checks and LLM-assisted semantic policy checks).
5. Comprehensive per-turn latency instrumentation.
6. A clean, stateless control plane (FastAPI) backed by persistent relational storage (PostgreSQL).

---

## 2. Requirement Classification

### 2.1 Tier 1: Mandatory Requirements
These capabilities are core requirements of the assignment and must be fully designed, implemented, and verified.

| Category | Requirement | Specification |
|---|---|---|
| **Infrastructure** | **Self-Hosted LiveKit** | Deployed locally or via containerized environment (`livekit/livekit-server`), configured via `livekit.yaml`. WebRTC audio streaming for client and agent connections. |
| **Agent Worker** | **Python LiveKit Agent** | Autonomous worker using `livekit-agents` framework. Connects to LiveKit server and joins allocated call rooms on demand. |
| **Pipeline** | **STT → LLM → TTS** | Streaming pipeline chaining speech transcription (e.g., Deepgram or OpenAI Whisper), conversational reasoning (e.g., OpenAI GPT-4o-mini), and audio synthesis (e.g., Cartesia, ElevenLabs, or OpenAI TTS). |
| **Turn Taking** | **VAD & Turn Detection** | Voice Activity Detection (Silero VAD) to accurately detect conversational pauses, turn boundaries, and speech start/stop events without manual push-to-talk. |
| **Interactivity** | **Barge-In Handling** | Immediate interruption when customer speaks while agent is voicing audio. Agent stops speaking immediately, flushes remaining TTS buffers, and truncates unspoken text from LLM history. |
| **Control Plane** | **FastAPI APIs** | Stateless REST API service providing endpoints for agent creation (`POST /agents`, `GET /agents/{id}`), call initialization (`POST /calls`), and call details retrieval (`GET /calls/{id}`). |
| **Configuration**| **DB-Backed Config** | System prompts, voice IDs, LLM models, and hyperparameters stored in PostgreSQL and dynamically injected into agent sessions per call. |
| **Client UI** | **Customer Web Client** | Clean web application allowing end-users to start/join a voice call with microphone input and audio playback. |
| **Supervisor** | **Supervisor Listen** | Supervisor can connect to the active call room in real time to listen to the bidirectional conversation. Customer has no indication supervisor is present. |
| **Supervisor** | **Supervisor Whisper** | Supervisor can send text instructions to the agent via LiveKit WebRTC Data Channel. Agent receives instruction and incorporates it into upcoming dialogue turns. Supervisor text and presence remain completely hidden from customer. |
| **Persistence** | **Call Transcript** | Real-time capturing and storage of all dialogue turns (`customer`, `agent`, `supervisor`). Private supervisor whispers must be flagged (`is_private = true`) and excluded from customer-facing views. |
| **Compliance 1** | **Recording Disclosure**| Post-call automated check: Validates whether agent announced that the call is being recorded within the first 30 seconds of the call. Must be evaluated using deterministic timestamp logic (NO LLM for timing rule). |
| **Compliance 2** | **Refund-Promise Policy**| Post-call automated check: Validates whether agent promised an unauthorized refund or financial guarantee. Evaluated via structured LLM semantic analysis, outputting pass/fail, offending quote, and reasoning. |
| **Instrumentation**|**Latency Measurement**| Explicit per-turn latency capture: measures `user stops speaking` → `STT final` → `LLM first token` → `TTS first audio chunk` → `audio published`. |
| **Deliverables** | **Documentation & Demo**| Comprehensive `README.md`, architectural diagrams, setup guides, and demonstration video walkthrough. |

---

### 2.2 Tier 2: Optional Stretch Requirements
These features represent advanced capabilities. They must only be introduced if they do not compromise the stability or correctness of Tier 1 requirements.

| Category | Requirement | Specification |
|---|---|---|
| **Supervisor** | **Supervisor Takeover** | Ability for human supervisor to unmute their own microphone and directly speak to the customer, muting the AI agent worker. |
| **Recording** | **Egress / Call Recording** | Exporting full audio recording of the call room via LiveKit Egress or server-side track recording. |
| **Concurrency** | **Concurrent Call Scaling** | Multi-call stress testing demonstrating multiple simultaneous voice agent sessions. |
| **DevOps** | **One-Click Compose** | Single `docker compose up` spinning up LiveKit, PostgreSQL, Backend, Agent, and both frontends simultaneously. |

---

### 2.3 Tier 3: Future Production Improvements
Production-grade patterns to plan for architecturally, but strictly out-of-scope for the core POC implementation:

- **Distributed LiveKit SFU Cluster**: Multi-node LiveKit deployment using Redis mesh signaling and turn routing.
- **FastAPI Horizontal Replicas**: Multiple backend nodes fronted by NGINX / AWS ALB with centralized rate-limiting.
- **Distributed Agent Worker Pool**: Dynamic autoscaling worker fleet distributed across multiple GPU/CPU nodes using LiveKit server-side room dispatching.
- **Asynchronous Post-Call Processing**: Decoupling compliance evaluations and transcript aggregation into dedicated task queues (e.g., Celery / Temporal / RabbitMQ).
- **Enterprise Telemetry**: Distributed tracing with OpenTelemetry, Prometheus metrics, and Grafana dashboards for latency SLA monitoring.
- **High Availability & Disaster Recovery**: Multi-region PostgreSQL streaming replication and automated failover.

---

## 3. Strict Boundary Rules

1. **Deterministic Compliance Rule**: Under no circumstances should the 30-second recording disclosure rule be evaluated by an LLM prompt. The exact utterance timestamp of the disclosure turn must be compared deterministically against the session start timestamp.
2. **Supervisor Stealth Guarantee**: The supervisor's microphone must NEVER be published to the customer's audio mix during listening or whispering. The supervisor's whisper text must NEVER appear in customer-facing transcripts or API responses without explicit supervisor privilege.
3. **Idempotency Guarantee**: Call finalization (storing transcripts, running compliance rules, computing summary metrics) must be safely repeatable without creating duplicate records or throwing database constraint errors.
