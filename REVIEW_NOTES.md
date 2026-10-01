# Technical Review Notes & Engineering Deep Dive

This document contains detailed architectural explanations matching the actual implementation of the **Supervised Voice AI Agent on Self-Hosted LiveKit**. It serves as an authoritative technical reference for engineering reviews and oral defenses.

---

## 1. LiveKit Media Concepts (As Implemented)

### 1.1 SFU (Selective Forwarding Unit)
- **Concept**: A WebRTC media server architecture where participants send their audio/video streams once to the server, and the server selectively routes copies of those streams to subscribed participants without re-encoding media for each recipient.
- **In This Project**: The self-hosted LiveKit SFU (`voice_ai_livekit` container) receives the customer's published microphone audio track (Opus 48kHz / 16kHz mono) and routes it simultaneously to the Agent Worker container and the Supervisor browser without mixing.

### 1.2 Rooms
- **Concept**: A virtual media session boundary isolating participants, tracks, and data channels.
- **In This Project**: Named deterministically as `call-{call_id}` (e.g. `call-43c2e6e8-87ff-473d-bc59-695f5fde5e1b`). Rooms are pre-created by FastAPI (`POST /calls`) via LiveKit's Twirp RPC API (`CreateRoomRequest`) with metadata containing the `agent_id`.

### 1.3 Participants
- **Concept**: A client endpoint connected to a LiveKit room.
- **In This Project**: There are three distinct participant roles:
  1. `customer`: Publishes microphone audio track; subscribes to agent audio track.
  2. `agent`: Autonomous Python worker participant (`identity="agent-..."`); subscribes to customer audio; publishes synthesized voice audio; listens on WebRTC data channel.
  3. `supervisor`: Stealth participant (`hidden=true`, `can_publish=false`, `can_subscribe=true`); subscribes to customer and agent audio tracks; publishes private text messages on the data channel.

### 1.4 Tracks & Publishing vs. Subscribing
- **Tracks**: Individual media streams (audio or video).
- **Publishing**: The act of streaming local media to the SFU. Customers publish via `room.local_participant.publish_track()`. Supervisors are strictly blocked from publishing by JWT VideoGrants (`can_publish=false`).
- **Subscribing**: The act of receiving a track published by another participant. Managed automatically by LiveKit's subscription manager (`can_subscribe=true`).

### 1.5 Agent Worker & Job Dispatch
- **Concept**: Rather than hard-coding room listeners, LiveKit Agents use a distributed worker model.
- **In This Project**: `agent/src/worker.py` registers with LiveKit via `WorkerOptions(entrypoint_fnc=entrypoint, agent_name="voice-agent-worker")`. When a room is created with dispatch metadata, LiveKit's scheduler dispatches a job to an available registered worker process over WebSocket.

### 1.6 VAD (Voice Activity Detection) & Turn Detection
- **Concept**: Algorithmic classification of audio frames to detect human speech vs. background noise.
- **In This Project**: Runs Silero VAD (`livekit.plugins.silero.VAD.load()`) processing 20ms audio frames. Turn detection monitors continuous speech frames and triggers speech endpointing after `min_endpointing_delay = 0.5s` of trailing silence, automatically transitioning conversational turn from customer to AI without manual push-to-talk.

### 1.7 Interruptions (Acoustic Barge-In)
- **Concept**: Detecting customer speech while the AI agent is actively speaking, immediately cutting off the AI's playback.
- **In This Project**: Handled by LiveKit Agents pipeline with `interruption_enabled=True` and `min_duration=0.2s`. When barge-in fires:
  1. Active TTS synthesis is aborted.
  2. In-flight WebRTC audio frames queued in playback buffers are cleared.
  3. `use_tts_aligned_transcript=True` truncates unspoken words from conversational context so conversational memory accurately matches what the customer heard.

### 1.8 WebRTC Data Channels (Reliable vs. Lossy)
- **Concept**: SCTP-encapsulated peer-to-peer data transport within the WebRTC connection.
- **Reliable Mode**: Operates like TCP with guaranteed, ordered delivery via SCTP retransmissions.
- **Lossy Mode**: Operates like UDP without retransmissions, favoring lower latency over reliability.
- **In This Project**: The supervisor whisper channel (`topic="whisper"`) uses **Reliable mode** (`reliable=True`) to ensure coaching instructions are never dropped or reordered due to packet loss.

### 1.9 Egress, Ingress & SIP
- **Egress**: LiveKit service for recording rooms or streaming to RTMP/HLS. Can be used for archiving call recordings directly to S3.
- **Ingress**: Ingesting external RTMP/Whip streams into LiveKit rooms.
- **SIP**: LiveKit SIP Gateway bridges standard telephony (PSTN / Twilio / Telnyx) into LiveKit WebRTC rooms, allowing regular telephone callers to converse with the Voice AI agent.

### 1.10 Self-Hosted LiveKit vs. LiveKit Cloud
- **Self-Hosted (Implemented)**: Full control over media routing, zero per-minute cloud routing fees, internal network isolation, customizable ports (`7880`, `7881`, `50000-50100/udp`), runs on Docker Compose on developer hardware.
- **LiveKit Cloud**: Managed SaaS offering global mesh routing across multi-region edge nodes, automated TURN server allocation, and built-in auto-scaling at the cost of egress usage fees and cloud dependency.

---

## 2. WebRTC Fundamentals (As Implemented)

### 2.1 Signaling & SDP (Session Description Protocol)
- **Signaling**: The out-of-band communication channel used to discover peers and exchange connection parameters before media flows. In our stack, signaling occurs over persistent WebSocket connections to port `7880`.
- **SDP**: A text-based format describing codec support (Opus, sample rates), encryption keys (DTLS-SRTP fingerprints), media formats, and network transport details exchanged during the Offer/Answer handshake.

### 2.2 ICE (Interactive Connectivity Establishment) & Candidates
- **ICE Framework**: RFC 8445 protocol used by WebRTC endpoints to discover the optimal network path between browser and SFU across NATs and firewalls.
- **Candidate Types**:
  1. **Host Candidate**: Local network interface IP address (e.g. `192.168.1.x` or `127.0.0.1`). Used for direct local communication.
  2. **Server-Reflexive Candidate (STUN)**: The public IP address and port allocated by the NAT router, discovered via STUN probes.
  3. **Relay Candidate (TURN)**: An allocated relay port on a public TURN server used when symmetric NATs block direct peer communication.

### 2.3 STUN vs. TURN
- **STUN (Session Traversal Utilities for NAT)**: A lightweight protocol (RFC 5389) that asks an external server *"What is my public IP and port?"*. Uses almost zero bandwidth.
- **TURN (Traversal Using Relays around NAT)**: A relay server protocol (RFC 5766). When both endpoints are behind restrictive symmetric NATs, all media packets are proxied through the TURN server, consuming server bandwidth.

### 2.4 UDP vs. TCP in Voice Media
- **UDP (User Datagram Protocol)**: Preferred for real-time voice (ports `50000–50100/udp`). If a voice packet is dropped, UDP continues without waiting. The human ear tolerates a 20ms micro-gap far better than the 500ms delay introduced by TCP packet retransmission (Head-of-Line blocking).
- **TCP Fallback**: LiveKit provides port `7881` as an ICE-TCP fallback only when corporate firewalls strictly drop all UDP packets.

### 2.5 Jitter, Packet Loss & Jitter Buffers
- **Jitter**: Variations in packet arrival time due to network congestion.
- **Jitter Buffer**: A small buffer (typically 20ms–60ms) on the receiving WebRTC client that reorders out-of-sequence packets and smooths out playback timing before feeding the Opus decoder.
- **Packet Loss Concealment (PLC)**: Opus codec feature that synthesizes missing audio frames when packets are lost in transit.

### 2.6 Audio Codecs: Opus vs. G.711
- **Opus (Used in This Project)**: Modern, highly adaptive audio codec (RFC 6716). Supports full-band 48kHz audio down to narrowband 8kHz, dynamic bitrates (6 kbps to 510 kbps), and built-in Forward Error Correction (FEC). Delivers studio-quality conversational AI voice over WebRTC.
- **G.711 ($\mu$-law / A-law)**: Legacy 1972 telephony standard (64 kbps, 8kHz sampling). Used when bridging to legacy PSTN/SIP phone lines, but lacks the high-fidelity acoustic features required for modern acoustic VAD.

---

## 3. Production Architecture & Scaling (Target: 10,000 Concurrent Calls)

### 3.1 Scaling Strategy by Tier
1. **Control Plane (FastAPI)**:
   - **Horizontal Scale**: 4–6 stateless pods behind an Application Load Balancer (ALB).
   - **Load Profile**: At 10,000 active calls (average 3-minute duration), traffic is ~55 call creations/sec and ~55 call finalizations/sec (~110 requests/sec), easily handled by small container instances.
2. **Worker Compute Pool**:
   - **Resource Profile**: Each call runs VAD, WebRTC audio streaming, and provider socket orchestration (~0.1 vCPU per active call).
   - **Sizing**: 10,000 calls require **850 to 1,250 worker vCPUs** (60–80 `c6i.4xlarge` AWS compute instances) managed via Kubernetes Horizontal Pod Autoscaler (HPA) scaling on LiveKit pending dispatch queue depth.
3. **LiveKit Media SFU Cluster**:
   - **Bandwidth**: 10,000 concurrent calls with Opus audio (~128 kbps full duplex) require **~1.28 Gbps of continuous egress bandwidth**.
   - **Cluster Topology**: 15–20 LiveKit SFU nodes behind a Network Load Balancer (NLB) with a Redis Cluster room-routing mesh.
4. **PostgreSQL Persistence Layer**:
   - **Write Rate**: ~550 transcript writes/sec and ~110 latency/compliance writes/sec (~700–800 writes/sec).
   - **Connection Pooler**: **PgBouncer** in transaction pooling mode to prevent 1,000+ worker pods from exhausting database connection limits.

### 3.2 What Bottlenecks First and Why?
> **Primary Bottleneck: Upstream Cloud LLM Provider Rate Limits (TPM/RPM) and Time-To-First-Token (TTFT).**

- **Why**: Infrastructure scaling (SFU nodes, worker compute, PgBouncer) is a straightforward horizontal engineering problem. In contrast, cloud LLM providers (OpenAI / Anthropic) enforce strict Token-Per-Minute and Request-Per-Minute quotas. At 10,000 calls generating ~550 LLM requests every second (~13.2M TPM), cloud APIs will throttle with HTTP 429 errors or experience severe TTFT queue delays (spiking from 400ms to 4,000ms+).
- **Mitigation**: Dedicated Provisioned Throughput Units (PTU) on Azure OpenAI, multi-region fallback routing across OpenAI, Anthropic Claude 3.5 Haiku, and Groq Llama 3.

### 3.3 Cost Breakdown
- **LLM Inference**: 35% – 45% of total cost (multi-turn conversation history compounds token consumption).
- **TTS Synthesis**: 25% – 35% of total cost (per-character generation fees).
- **STT Streaming**: 15% – 20% of total cost (per-minute streaming connection fees).
- **Compute & SFU Hosting**: 10% – 15% of total cost (worker container nodes and SFU instances).
- **Bandwidth / Egress**: 3% – 5% of total cost (cloud internet data egress).

### 3.4 Failure Modes & Recovery
- **Worker Crash**: If a worker process dies mid-call, the WebRTC audio drops. Transcripts up to the crash are safe in PostgreSQL. In production, LiveKit's heartbeat scheduler detects worker loss within 2s, dispatches a standby warm worker, rehydrates context from PostgreSQL, and rejoins the room with a polite recovery greeting (*"Pardon the interruption, I am back. How can I help?"*).
- **Media SFU Restart**: Clients leverage WebRTC ICE restart and reconnect to an alternative SFU node in the cluster without dropping the application session.
- **Compliance Failure**: If the compliance LLM times out or returns malformed JSON, the service records `pass=False` with error details. It **never fakes PASS**. In production, an asynchronous dead-letter queue (DLQ) retries failed audits with exponential backoff.
