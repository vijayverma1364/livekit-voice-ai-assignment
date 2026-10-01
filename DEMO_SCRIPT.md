# Live Demonstration Script: Supervised Voice AI Agent on Self-Hosted LiveKit

This document outlines the exact 3–5 minute demonstration sequence and speaking points for presenting the **Supervised Voice AI Agent on Self-Hosted LiveKit** platform.

---

## Demonstration Metadata
- **Duration**: 3.5 – 5.0 Minutes
- **Prerequisites Running**:
  - LiveKit SFU (`ws://localhost:7880`)
  - PostgreSQL Database (`localhost:5432`)
  - FastAPI Control Plane (`http://localhost:8000`)
  - Voice Agent Worker (`python -m agent.src.worker dev`)
  - Customer Web Client (`http://localhost:3000`)
  - Supervisor Console (`http://localhost:3001`)

---

## 22-Step Demonstration Walkthrough

| Step | Time | Interface | Action / Trigger | Spoken Dialogue / Operator Speaking Point | Expected System Behavior |
|:---:|:---:|:---:|:---|:---|:---|
| **1** | 0:00 | Browser 1 | Open `http://localhost:3000` | *"Welcome. Here we have our customer-facing web client connecting to our self-hosted LiveKit WebRTC server."* | Customer UI loads in `IDLE` state with green server indicator. |
| **2** | 0:15 | Browser 1 | Select Agent | *"We select our PostgreSQL-backed Acme Support Agent profile."* | Dropdown dynamically displays agents fetched via `GET /agents`. |
| **3** | 0:25 | Browser 1 | Click **Start Voice Call** | *"Clicking Call initiates the session via our stateless FastAPI backend."* | App calls `POST /calls`, retrieves room name and JWT token, transitions to `CONNECTING`. |
| **4** | 0:35 | Browser 1 | Allow Microphone | *"The browser connects over WebRTC and publishes the microphone track."* | Status badge changes to `LIVE CALL`; active microphone audio waveform animates. |
| **5** | 0:45 | Audio | AI Greeting | *[Listen to Agent]*: *"Thank you for calling Acme Support. Please note that this call is recorded for quality assurance. How can I help you today?"* | Worker dispatches into room; voices greeting through TTS. |
| **6** | 0:55 | Screen 1 | Point out Disclosure | *"Notice the agent disclosed recording within the first 10 seconds. This is critical for our post-call compliance audit."* | Initial turn appears in the live transcript. |
| **7** | 1:05 | Mic | Customer Speaks | **Customer**: *"Hi, my Acme Router has a flashing red light and I can't connect to the internet."* | Customer waveform pulses; VAD detects speech; streaming STT executes. |
| **8** | 1:20 | Screen 1 | Show Live Transcript | *"As we speak, the dialogue turns stream into our live transcript, tagged with speaker and relative timestamps."* | `USER` and `AGENT` badges render chronologically in the transcript panel. |
| **9** | 1:35 | Audio | Trigger Barge-In | **Agent starts speaking**: *"I can certainly help you troubleshoot that router. First, let's locate the..."*<br/>**Customer interrupts**: *"Wait, I already rebooted it twice!"* | Silero VAD detects customer speech while agent audio is active. |
| **10** | 1:45 | Audio | Show AI Stops Immediately | *"Notice how the AI immediately stopped speaking mid-sentence. That is our acoustic barge-in handler."* | Agent audio halts instantly; pending TTS playback buffers are dropped. |
| **11** | 1:55 | Screen 1 | Continue Conversation | **Agent**: *"Understood. Since you've already power-cycled the router, let's check the cable connection on the back."* | Unspoken text from the interrupted sentence is truncated; only heard words persist in LLM context. |
| **12** | 2:10 | Browser 2 | Open `http://localhost:3001` | *"Now, let's switch to the Supervisor Console on port 3001."* | Dashboard displays active calls list fetched via `GET /calls`. |
| **13** | 2:20 | Browser 2 | Click **Monitor Call** | *"The supervisor joins the active call room in stealth mode."* | Supervisor connects using a restricted JWT token with `hidden=true` and `can_publish=false`. |
| **14** | 2:30 | Audio 2 | Supervisor Listens | *"The supervisor can hear both the customer and the agent with crystal-clear full-duplex WebRTC audio, but the supervisor's microphone is locked."* | Both customer and agent audio tracks play through supervisor headphones; customer UI participant list omits supervisor. |
| **15** | 2:45 | Browser 2 | Enter Whisper & Send | Supervisor types: **`Offer a 10% discount.`** and clicks **Send Whisper**. | Message is published over WebRTC Data Channel on topic `whisper`. |
| **16** | 3:00 | Mic | Customer Asks Question | **Customer**: *"This router has been nothing but trouble, is there anything you can do for me?"* | Customer audio streams to agent. |
| **17** | 3:15 | Audio | AI Follows Whisper | **Agent**: *"I apologize for the frustration. To make things right, I can offer you a 10% discount on your next monthly bill while we resolve this."* | Agent integrates the supervisor's coaching whisper into its active prompt context. |
| **18** | 3:30 | Screen 1 & 2 | Point out Anti-Disclosure | *"Notice two vital things: the agent never revealed a supervisor coached it, and the whisper never appeared in the customer's transcript."* | Whisper is saved with `is_private=true`, visible only to the supervisor. |
| **19** | 3:45 | Browser 1 | Click **End Call** | *"The customer ends the call. The browser disconnects and the worker tears down cleanly."* | Customer UI transitions to `CALL ENDED`; agent worker flushes uncommitted turns and triggers compliance. |
| **20** | 4:00 | Browser 2 | Show Final Transcript | *"In the supervisor console, we view the complete call record with 9 persisted turns."* | Full dialogue history is displayed with accurate relative time offsets. |
| **21** | 4:15 | Browser 2 | Show Compliance Results | *"Here are the automated compliance results stored in PostgreSQL:*<br/>*1. Recording Disclosure: PASS (detected at 0.8s, strictly deterministic timestamp math).*<br/>*2. Refund Policy Audit: PASS (LLM semantic check confirmed no unauthorized refund was promised)."* | Displays structured compliance badge: `Recording Disclosure: PASS`, `Refund Audit: PASS`. |
| **22** | 4:35 | Browser 2 | Show Latency Telemetry | *"Finally, our per-turn latency observability captured all 5 discrete milestones: user speech stop, STT final, LLM TTFT, TTS TTFB, and WebRTC audio publication, achieving sub-second response times."* | Displays per-turn latency breakdown table with stage durations. |

---

## Key Technical Talking Points for Reviewers

1. **Self-Hosted Realism**: Emphasize that WebRTC media routing is entirely self-hosted via LiveKit on `localhost:7880`. No third-party media cloud is used.
2. **Stateless Control Plane**: FastAPI stores zero call dictionaries in memory (`active_calls = {}` does not exist). PostgreSQL is the durable source of truth.
3. **Supervisor Stealth Guarantee**: The supervisor's presence is cryptographically isolated via LiveKit JWT permissions (`can_publish = false`, `hidden = true`), and private whispers travel via WebRTC Data Channels.
4. **Deterministic Compliance Rule**: Reiterate that Rule 1 (30s recording disclosure) strictly compares timestamps without an LLM, while Rule 2 (refund promise) uses structured LLM output with offending line attribution and never fakes PASS.
5. **Acoustic Barge-In**: Highlight that unspoken LLM text is truncated so conversational memory accurately mirrors what was actually voiced.
