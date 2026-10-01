# System Architecture Specification

This document details the system design, communication protocols, participant isolation, and scalability roadmap for the **Supervised Voice AI Agent on Self-Hosted LiveKit**.

---

## 1. High-Level Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                                REAL-TIME MEDIA LAYER                              |
+-----------------------------------------------------------------------------------+

 Customer Browser                          Supervisor Browser
 (Microphone + Audio)                     (Audio Listen Only + Text Whisper)
        |                                                 |
        | WebRTC (Audio In/Out)                           | WebRTC (Audio Sub Only)
        |                                                 | Data Channel (Whisper)
        v                                                 v
  +-------------------------------------------------------------+
  |              Self-Hosted LiveKit SFU (Port 7880)            |
  |   Room: call-{call_id}                                      |
  |   - Customer: publish audio, subscribe agent audio          |
  |   - Supervisor: subscribe all audio, publish data channel   |
  |   - Agent: publish audio, subscribe customer audio/data     |
  +-------------------------------------------------------------+
                                |
                                | WebRTC Media / Data Channel
                                v
                +-------------------------------+
                |     LiveKit Agent Worker      |
                |  (Python livekit-agents SDK)  |
                +-------------------------------+
                     |          |          |
        +------------+          |          +------------+
        |                       |                       |
        v                       v                       v
     +-----+                 +-----+                 +-----+
     | STT |                 | LLM |                 | TTS |
     +-----+                 +-----+                 +-----+
  (Deepgram/OpenAI)     (OpenAI GPT-4o-mini)    (Cartesia/Eleven/OpenAI)


+-----------------------------------------------------------------------------------+
|                         CONTROL PLANE & PERSISTENCE LAYER                         |
+-----------------------------------------------------------------------------------+

 Customer / Supervisor Web Clients
               |
               | HTTP / REST (JSON)
               v
     +-------------------+
     |  FastAPI Backend  | <-------- Database Driver (Asyncpg / SQLAlchemy)
     +-------------------+
               |
               v
     +-------------------+
     | PostgreSQL (v16)  |
     | - agents          |
     | - calls           |
     | - transcripts     |
     | - latency_metrics |
     | - compliance      |
     +-------------------+
```

---

## 2. Component Responsibilities

### 2.1 Self-Hosted LiveKit SFU
- Manages low-latency WebRTC audio tracks, signaling, and data channels.
- Enforces room-level access permissions via cryptographic JWT participant tokens minted by FastAPI.
- Routes customer microphone stream to the agent worker.
- Broadcasts agent synthesized audio to both customer and supervisor.
- Restricts supervisor from publishing an audio track into the customer's audio mix.
- Delivers private supervisor text messages (whispers) directly to the agent worker via WebRTC Data Channels.

### 2.2 Python LiveKit Voice Agent Worker
- Connects to LiveKit SFU as an autonomous participant worker (`livekit-agents` worker pool).
- **VAD & Turn Detection**: Uses Silero VAD to detect customer speech boundaries in real time.
- **Barge-In Handling**: When customer begins speaking while the agent is speaking:
  - Agent immediately cancels current audio playback.
  - Flushes queued TTS output.
  - Truncates assistant conversational context so unspoken text is never recorded as spoken dialogue.
- **Real-Time Pipeline**:
  - `Customer Audio` -> `STT` (Streaming Speech-to-Text).
  - `Transcribed Text` -> `LLM` (Streaming Chat Completion with Dynamic System Prompt).
  - `LLM Token Stream` -> `TTS` (Streaming Text-to-Speech).
  - `Synthesized PCM Audio` -> Published to LiveKit audio track.
- **Supervisor Whisper Handler**:
  - Listens to incoming data channel messages from the supervisor.
  - Dynamically injects instructions into current agent context (system instructions or internal guidance) without voicing the supervisor's text aloud to the customer.
- **Telemetry & Latency Instrumentation**:
  - Emits timestamps at every stage: `user_speech_stopped`, `stt_final`, `llm_first_token`, `tts_first_audio`, `audio_published`.
- **Post-Call Finalizer**:
  - Persists completed transcript, latency metrics, and triggers compliance checks into PostgreSQL upon room disconnection.

### 2.3 FastAPI Backend (Control Plane)
- **Stateless Web API**: Does not maintain in-memory call state or session dictionaries.
- **Agent Lifecycle Management**: CRUD endpoints (`POST /agents`, `GET /agents/{id}`).
- **Call Session Orchestration**: Creates call records in PostgreSQL and signs LiveKit JWT tokens with appropriate role-based ACLs for customers and supervisors.
- **Read APIs**: Serves call records, transcripts, latency metrics, and compliance evaluations (`GET /calls/{id}`).

### 2.4 PostgreSQL Persistence Layer
- Durable source of truth for all entities (`agents`, `calls`, `transcript_entries`, `latency_measurements`, `compliance_results`).
- Enforces data integrity through foreign keys, check constraints, and unique compound keys for idempotency.

### 2.5 LiveKit Networking & Port Specifications

The self-hosted LiveKit SFU requires distinct ports for signaling control and real-time media exchange.

| Port | Protocol | Purpose | Why Required | Who Uses It |
|---|---|---|---|---|
| **`7880`** | TCP (HTTP/WS) | **Signaling & Management API** | Establishes initial HTTP handshake, room creation via Twirp/gRPC, and persistent WebSocket signaling channels for peer connection negotiation (SDP offer/answer exchange). | Customer web client, Supervisor dashboard, Voice AI Agent worker, FastAPI backend |
| **`7881`** | TCP | **WebRTC TCP Fallback** | Provides reliable fallback media transport (ICE-TCP) when UDP packets are dropped or restricted by enterprise firewalls/proxies. | WebRTC clients (Browsers and Agent workers under restrictive NATs) |
| **`50000–50100`** | UDP | **WebRTC Media Range (RTP/RTCP)** | Delivers high-throughput, low-latency full-duplex voice streams via SRTP. UDP is essential to avoid TCP Head-of-Line blocking and preserve sub-second latency. | Customer browser, Supervisor audio monitor, Agent worker audio publisher |

---

## 3. Communication Flows

### 3.1 Call Initialization Flow
```
Customer Web           FastAPI Backend          PostgreSQL          LiveKit SFU
     |                        |                      |                   |
     |--- POST /calls ------->|                      |                   |
     |    (agent_id, name)    |--- Query Agent ----->|                   |
     |                        |<-- Agent Config -----|                   |
     |                        |                      |                   |
     |                        |--- Insert Call Record------------------->|
     |                        |    (room_name, initiated)                |
     |                        |                                          |
     |                        |--- Mint JWT Access Token --------------->|
     |                        |    (grants roomJoin: room_name)          |
     |                        |                                          |
     |<-- 201 Created --------|                                          |
     |    (call_id, token, ws_url)                                       |
     |                                                                   |
     |=== Connect WebRTC with JWT ======================================>|
```

### 3.2 Real-Time Conversational Turn & Latency Flow
```
Customer               LiveKit SFU            Agent Worker            AI Providers (STT/LLM/TTS)
   |                        |                      |                               |
   |--- Audio Stream ------>|                      |                               |
   |                        |--- Audio Stream ---->|                               |
   |                        |                      |-- Silero VAD (Speech End)     |
   |                        |                      |-- [T0: user_speech_stopped]   |
   |                        |                      |--- Stream PCM Audio --------->| STT
   |                        |                      |<-- Final Transcript ----------| STT
   |                        |                      |-- [T1: stt_final]             |
   |                        |                      |--- Stream Prompt+History ---->| LLM
   |                        |                      |<-- First Token Stream --------| LLM
   |                        |                      |-- [T2: llm_first_token]       |
   |                        |                      |--- Stream Text Chunks ------->| TTS
   |                        |                      |<-- First Audio Frame ---------| TTS
   |                        |                      |-- [T3: tts_first_audio]       |
   |                        |<-- Publish Audio ----|-- [T4: audio_published]       |
   |<-- Play Audio ---------|                      |                               |
```

### 3.3 Supervisor Whisper Flow
```
Supervisor Client            LiveKit SFU                  Agent Worker             Customer Client
       |                          |                            |                          |
       |=== Join Room (Sub-only)=>|                            |                          |
       |<== Receive Audio Mix ====| (Listens to conversation)  |                          |
       |                          |                            |                          |
       |--- DataChannel Message ->|                            |                          |
       |    ("Offer 10% discount")|--- DataChannel Message --->|                          |
       |                          |    (topic: "whisper")      |                          |
       |                          |                            |-- Appends instruction to |
       |                          |                            |   internal context       |
       |                          |                            |-- Agent follows prompt   |
       |                          |                            |   in subsequent turns    |
       |                          |                            |-- (Never spoken aloud)   |
       |                          |                            |   (Never leaks to user)  |
```

### 3.4 Call Teardown & Compliance Flow
```
Agent Worker / Webhook             FastAPI / Database Worker            PostgreSQL
          |                                    |                             |
          |--- Call Disconnected ------------->|                             |
          |    (room_name, duration)           |--- Update Call Status ----->|
          |                                    |    (status: completed)      |
          |                                    |                             |
          |--- Flush Transcript Entries ------>|--- Batch Insert ----------->|
          |                                    |    (transcripts)            |
          |                                    |                             |
          |--- Flush Latency Telemetry ------->|--- Insert Latency --------->|
          |                                    |                             |
          |--- Run Compliance Checks --------->|                             |
          |    1. Recording Disclosure         |                             |
          |       (Deterministic timing <30s)  |                             |
          |    2. Refund Promise               |                             |
          |       (LLM Semantic Evaluation)    |--- Upsert Compliance ------>|
          |                                    |    (uq_compliance_call_rule)|
```

---

## 4. Horizontal Scalability Roadmap (Target: 10,000 Concurrent Calls)

In a future production deployment, the architecture scales horizontally without altering database schemas or API contracts:

```
                          Internet Traffic
                                 |
                                 v
                     [ Global Load Balancer ]
                                 |
           +---------------------+---------------------+
           |                                           |
           v                                           v
   [ LiveKit SFU Node 1 ]                      [ LiveKit SFU Node N ]
   (Distributed Mesh / Redis Egress)           (Distributed Mesh / Redis Egress)
           |                                           |
           +---------------------+---------------------+
                                 |
                    [ Agent Worker Pool Autoscaler ]
                    |                              |
                    v                              v
            [ Agent Worker 1 ]             [ Agent Worker M ]
            (Room Dispatch)                (Room Dispatch)

                                 |
                     [ API Gateway / Ingress ]
                                 |
           +---------------------+---------------------+
           |                                           |
           v                                           v
   [ FastAPI Instance 1 ]                     [ FastAPI Instance K ]
           |                                           |
           +---------------------+---------------------+
                                 |
                                 v
                     [ PostgreSQL Cluster ]
                     - Primary (Writes)
                     - Read Replicas (Dashboard Analytics)
                     - PgBouncer (Connection Pooling)
```

1. **Stateless FastAPI**: Scale from 1 to K instances behind standard HTTP load balancers.
2. **Autonomous Agent Workers**: Workers register to LiveKit server and accept call dispatches automatically. Adding worker instances horizontally scales voice processing capacity.
3. **SFU Clustering**: LiveKit natively supports multi-node clustering with Redis-based room routing for media scale.
4. **Connection Pooling**: PostgreSQL scaled via PgBouncer and Read Replicas for reporting and supervisor analytics.

---

## 5. Phase 10 Production Hardening & Failure Handling Lifecycle

### 5.1 Disconnect Lifecycle & State Cleanliness
- **Customer Disconnect Detection**: The worker listens to `@ctx.room.on("participant_disconnected")`. When the customer drops, the agent session immediately tears down audio tracks, flushes buffered speech context to PostgreSQL, initiates compliance audits, and exits the room cleanly.
- **Supervisor Disconnect Isolation**: Because the supervisor is a stealth eavesdropper (`hidden=True, can_publish=False`), supervisor disconnection events are isolated and have zero impact on the active call audio or agent worker loop.
- **Worker Crash Handling**: In the local POC, worker termination drops published media while leaving existing transcripts intact in PostgreSQL. In production, LiveKit's worker heartbeats detect worker loss within 2 seconds and trigger job re-dispatch to a standby warm worker container with state rehydration from PostgreSQL.

### 5.2 Asynchronous Post-Call Processing Strategy
In production, synchronous post-call compliance and transcription finalization transition to an asynchronous queue:
1. **Webhook / Event Egress**: When a call ends, LiveKit SFU webhook or worker emits `call.completed` event to an asynchronous queue (e.g. AWS SQS, Redis Streams, or RabbitMQ).
2. **Decoupled Audit Workers**: Worker pools dedicated to compliance processing pull call IDs, evaluate deterministic regex rules and LLM refund audits, and write back to `compliance_results`.
3. **Idempotent Upserts**: Protected by `UniqueConstraint("call_id", name="uq_compliance_call")` ensuring retry safety and zero duplicate audits during transient worker re-deliveries.

