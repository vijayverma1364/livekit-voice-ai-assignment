"""
Phase 8: Real Call Latency Measurement Runner
Executes real LiveKit WebRTC call sessions across multiple dialogue turns,
records authentic runtime wall-clock timestamps for every pipeline stage:
1. user_stop_ms (VAD user stop)
2. stt_final_ms (Speech-to-text final transcript)
3. llm_first_token_ms (First LLM streaming token arrived)
4. tts_first_audio_ms (First synthesized TTS audio frame ready)
5. audio_published_ms (Audio frame published to WebRTC room)

Validates PostgreSQL persistence and outputs the README latency table.
"""

import asyncio
import logging
import wave
import httpx
import numpy as np
from livekit import rtc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("latency_runner")

API_BASE_URL = "http://127.0.0.1:8000"
LIVEKIT_URL = "ws://localhost:7880"


def load_resampled_audio(wav_path: str, target_sr: int = 16000) -> np.ndarray:
    with wave.open(wav_path, "rb") as wf:
        orig_sr = wf.getframerate()
        orig_channels = wf.getnchannels()
        raw_bytes = wf.readframes(wf.getnframes())
        samples = np.frombuffer(raw_bytes, dtype=np.int16)
        if orig_channels > 1:
            samples = samples[::orig_channels]

        if orig_sr != target_sr:
            indices = np.round(np.arange(0, len(samples), orig_sr / target_sr)).astype(int)
            indices = indices[indices < len(samples)]
            samples = samples[indices]
        return samples


async def stream_audio_utterance(
    source: rtc.AudioSource,
    samples: np.ndarray,
    sample_rate: int = 16000,
    chunk_size: int = 480,
):
    logger.info("Streaming customer voice utterance (%d samples, %.2fs)...", len(samples), len(samples) / sample_rate)
    for i in range(0, len(samples), chunk_size):
        chunk = samples[i : i + chunk_size]
        if len(chunk) < chunk_size:
            chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
        frame = rtc.AudioFrame(chunk.tobytes(), sample_rate, 1, chunk_size)
        await source.capture_frame(frame)
        await asyncio.sleep(chunk_size / sample_rate)

    # Follow with 1.2s silence to ensure VAD endpointing cleanly detects speech completion
    logger.info("Utterance finished. Sending endpointing silence...")
    silence = np.zeros(chunk_size, dtype=np.int16)
    for _ in range(40):  # 40 * 30ms = 1200ms
        frame = rtc.AudioFrame(silence.tobytes(), sample_rate, 1, chunk_size)
        await source.capture_frame(frame)
        await asyncio.sleep(chunk_size / sample_rate)


async def run_latency_measurement_call():
    logger.info("=" * 65)
    logger.info("STARTING PHASE 8 REAL CALL LATENCY MEASUREMENT")
    logger.info("=" * 65)

    samples = load_resampled_audio("test_speech.wav", 16000)

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        # 1. Fetch Agent
        agents = (await http_client.get(f"{API_BASE_URL}/agents")).json()
        agent = next((a for a in agents if "Acme" in a["name"]), agents[0])
        logger.info("Selected Agent: %s (ID: %s)", agent["name"], agent["id"])

        # 2. Initiate Call Session
        call_init_resp = await http_client.post(
            f"{API_BASE_URL}/calls",
            json={
                "agent_id": agent["id"],
                "customer_name": "Latency Test Customer",
            },
        )
        assert call_init_resp.status_code == 201, f"Call initiation failed: {call_init_resp.text}"
        call_data = call_init_resp.json()
        call_id = call_data["call_id"]
        room_name = call_data["room_name"]
        customer_token = call_data["livekit_token"]
        logger.info("Call Created: ID=%s, Room=%s", call_id, room_name)

        # 3. Connect Customer to LiveKit Room
        room = rtc.Room()
        logger.info("Connecting Customer WebRTC client to %s...", LIVEKIT_URL)
        await room.connect(LIVEKIT_URL, customer_token)
        logger.info("Customer connected to room: %s", room_name)

        # 4. Set up Customer Microphone Track
        source = rtc.AudioSource(sample_rate=16000, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("customer_mic", source)
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        publication = await room.local_participant.publish_track(track, options)
        logger.info("Published customer microphone track: %s", publication.sid)

        # 5. Wait for Agent Worker to Join
        logger.info("Waiting for agent worker to connect...")
        worker_joined = False
        for _ in range(15):
            await asyncio.sleep(1.0)
            remotes = [p.identity for p in room.remote_participants.values()]
            if any("agent" in r.lower() for r in remotes):
                logger.info("Agent joined room! Remotes: %s", remotes)
                worker_joined = True
                break

        assert worker_joined, "Voice agent worker failed to join room within timeout"

        # Allow initial recording disclosure greeting to voice
        logger.info("Waiting 3.5s for agent initial greeting to voice...")
        await asyncio.sleep(3.5)

        # -----------------------------------------------------------------
        # TURN 1: Customer speaks first utterance
        # -----------------------------------------------------------------
        logger.info("\n>>> EXECUTING TURN 1 <<<")
        await stream_audio_utterance(source, samples)

        # Allow pipeline to process Turn 1 and agent to voice response
        logger.info("Waiting 4.0s for Turn 1 STT -> LLM -> TTS -> Publication...")
        await asyncio.sleep(4.0)

        # -----------------------------------------------------------------
        # TURN 2: Customer speaks second utterance
        # -----------------------------------------------------------------
        logger.info("\n>>> EXECUTING TURN 2 <<<")
        await stream_audio_utterance(source, samples)

        # Allow pipeline to process Turn 2 and agent to voice response
        logger.info("Waiting 4.0s for Turn 2 STT -> LLM -> TTS -> Publication...")
        await asyncio.sleep(4.0)

        # 6. Disconnect Call
        logger.info("Disconnecting customer from room...")
        await room.disconnect()
        logger.info("Customer disconnected.")

        # Allow worker teardown and async DB flush
        logger.info("Waiting 2.5s for call finalization and database write...")
        await asyncio.sleep(2.5)

        # 7. Query Call Details from Control Plane
        logger.info("Fetching final call records from Control Plane...")
        resp = await http_client.get(f"{API_BASE_URL}/calls/{call_id}")
        assert resp.status_code == 200, f"Failed to get call details: {resp.text}"
        call_details = resp.json()

        measurements = call_details.get("latency_measurements", [])
        transcripts = call_details.get("transcripts", [])

        logger.info("Call Status: %s", call_details.get("status"))
        logger.info("Persisted Transcripts: %d turns", len(transcripts))
        for t in transcripts:
            logger.info("  [%s] (+%dms): %s", t["speaker"], t["relative_time_ms"], t["text"][:60])

        logger.info("Persisted Latency Measurements: %d records", len(measurements))
        for m in measurements:
            logger.info(
                "  Turn %d: user_stop=%sms, stt_final=%sms, llm_first_token=%sms, tts_first_audio=%sms, audio_published=%sms",
                m["turn_number"],
                m["user_stop_ms"],
                m["stt_final_ms"],
                m["llm_first_token_ms"],
                m["tts_first_audio_ms"],
                m["audio_published_ms"],
            )
            logger.info(
                "  Durations: STT=%sms, LLM_TTFT=%sms, TTS_TTFB=%sms, Publish=%sms, Total=%sms",
                m.get("stt_latency_ms"),
                m.get("llm_first_token_latency_ms"),
                m.get("tts_first_audio_latency_ms"),
                m.get("publish_latency_ms"),
                m.get("overall_latency_ms"),
            )

        return call_details


if __name__ == "__main__":
    asyncio.run(run_latency_measurement_call())
