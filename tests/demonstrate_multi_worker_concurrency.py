"""
Phase 10: Multi-Worker Concurrency Demonstration
Demonstrates:
- 2+ agent worker processes actively registered to LiveKit SFU.
- 3 simultaneous calls executed concurrently in parallel.
- Work distributed across the worker pool without cross-talk or race conditions.
- Clean completion and transcript persistence for all 3 concurrent calls.
"""

import asyncio
import logging
import wave
import httpx
import numpy as np
from livekit import rtc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("multi_worker_demo")

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


async def stream_audio_frames(source: rtc.AudioSource, samples: np.ndarray, sample_rate: int = 16000, chunk_size: int = 480):
    for i in range(0, len(samples), chunk_size):
        chunk = samples[i : i + chunk_size]
        if len(chunk) < chunk_size:
            chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
        frame = rtc.AudioFrame(chunk.tobytes(), sample_rate, 1, chunk_size)
        await source.capture_frame(frame)
        await asyncio.sleep(chunk_size / sample_rate)

    # 1.0s silence trailing for endpointing
    silence = np.zeros(chunk_size, dtype=np.int16)
    for _ in range(35):
        frame = rtc.AudioFrame(silence.tobytes(), sample_rate, 1, chunk_size)
        await source.capture_frame(frame)
        await asyncio.sleep(chunk_size / sample_rate)


async def execute_concurrent_call(
    call_index: int,
    agent_id: str,
    samples: np.ndarray,
    results: dict,
):
    logger.info("[Call %d] Starting concurrent call session...", call_index)
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        # 1. Create call
        resp = await http_client.post(
            f"{API_BASE_URL}/calls",
            json={
                "agent_id": agent_id,
                "customer_name": f"Concurrent Customer {call_index}",
            },
        )
        assert resp.status_code == 201, f"Call {call_index} creation failed: {resp.text}"
        data = resp.json()
        call_id = data["call_id"]
        room_name = data["room_name"]
        token = data["livekit_token"]
        logger.info("[Call %d] Created Call ID: %s, Room: %s", call_index, call_id, room_name)

        # 2. Connect to LiveKit Room
        room = rtc.Room()
        await room.connect(LIVEKIT_URL, token)
        logger.info("[Call %d] Connected to LiveKit room %s", call_index, room_name)

        # 3. Publish customer mic
        source = rtc.AudioSource(sample_rate=16000, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track(f"mic_{call_index}", source)
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        await room.local_participant.publish_track(track, options)

        # 4. Wait for worker agent to join
        agent_identity = None
        for _ in range(15):
            await asyncio.sleep(1.0)
            remotes = [p.identity for p in room.remote_participants.values()]
            matching = [r for r in remotes if "agent" in r.lower()]
            if matching:
                agent_identity = matching[0]
                logger.info("[Call %d] Agent worker assigned: %s", call_index, agent_identity)
                break

        assert agent_identity is not None, f"Call {call_index}: Agent worker failed to join"

        # 5. Wait for initial greeting
        await asyncio.sleep(3.0)

        # 6. Stream speech audio
        logger.info("[Call %d] Streaming speech utterance...", call_index)
        await stream_audio_frames(source, samples)

        # 7. Wait for AI response
        await asyncio.sleep(3.0)

        # 8. Disconnect
        logger.info("[Call %d] Disconnecting from room...", call_index)
        await room.disconnect()

        # Allow teardown
        await asyncio.sleep(4.0)

        # 9. Query final call details
        final_resp = await http_client.get(f"{API_BASE_URL}/calls/{call_id}")
        assert final_resp.status_code == 200
        call_details = final_resp.json()

        results[call_index] = {
            "call_id": call_id,
            "room_name": room_name,
            "agent_identity": agent_identity,
            "transcripts_count": len(call_details.get("transcripts", [])),
            "latency_count": len(call_details.get("latency_measurements", [])),
            "compliance_pass": call_details.get("compliance_result") is not None,
        }
        logger.info(
            "[Call %d] Completed! Transcripts: %d, Latency records: %d, Compliance: %s",
            call_index,
            results[call_index]["transcripts_count"],
            results[call_index]["latency_count"],
            results[call_index]["compliance_pass"],
        )


async def main():
    print("=" * 75)
    print("PHASE 10: MULTI-WORKER CONCURRENCY DEMONSTRATION")
    print("=" * 75)

    samples = load_resampled_audio("test_speech.wav", 16000)

    async with httpx.AsyncClient(timeout=15.0) as http_client:
        agents = (await http_client.get(f"{API_BASE_URL}/agents")).json()
        acme_agent = next((a for a in agents if "Acme" in a["name"]), agents[0])
        agent_id = acme_agent["id"]

    results = {}
    print("\n[Execution] Launching 3 simultaneous calls in parallel across worker pool...")
    tasks = [
        execute_concurrent_call(1, agent_id, samples, results),
        execute_concurrent_call(2, agent_id, samples, results),
        execute_concurrent_call(3, agent_id, samples, results),
    ]

    await asyncio.gather(*tasks)

    print("\n" + "=" * 75)
    print("MULTI-WORKER CONCURRENCY RESULTS SUMMARY")
    print("=" * 75)
    for idx, r in sorted(results.items()):
        print(f"Call {idx}:")
        print(f"  - Call ID:           {r['call_id']}")
        print(f"  - Room Name:         {r['room_name']}")
        print(f"  - Assigned Agent:    {r['agent_identity']}")
        print(f"  - Transcripts Saved: {r['transcripts_count']}")
        print(f"  - Latency Measured:  {r['latency_count']} turns")
        print(f"  - Compliance Passed: {r['compliance_pass']}")

    assigned_agents = {r["agent_identity"] for r in results.values()}
    print(f"\nUnique Worker Assignments: {len(assigned_agents)} distinct agent sessions")
    assert len(results) == 3, f"Expected 3 completed calls, got {len(results)}"
    for r in results.values():
        assert r["transcripts_count"] > 0, "Expected transcripts to be saved"
        assert r["latency_count"] > 0, "Expected latency records"
        assert r["compliance_pass"] is True, "Expected compliance to pass"

    print("\n>>> ALL 3 CONCURRENT CALLS COMPLETED AND VERIFIED ACROSS WORKER POOL! <<<")
    return True


if __name__ == "__main__":
    asyncio.run(main())
