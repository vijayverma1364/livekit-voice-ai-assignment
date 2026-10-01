import asyncio
import wave
import numpy as np
from livekit import rtc
from livekit.plugins import silero

async def main():
    vad = silero.VAD.load()
    stream = vad.stream()

    with wave.open("test_speech.wav", "rb") as wf:
        orig_sr = wf.getframerate()
        orig_channels = wf.getnchannels()
        raw_bytes = wf.readframes(wf.getnframes())
        print(f"Loaded WAV: sr={orig_sr}, ch={orig_channels}, bytes={len(raw_bytes)}")

        samples = np.frombuffer(raw_bytes, dtype=np.int16)
        if orig_channels > 1:
            samples = samples[::orig_channels]

        # Resample to 16000 if needed
        if orig_sr != 16000:
            indices = np.round(np.arange(0, len(samples), orig_sr / 16000)).astype(int)
            indices = indices[indices < len(samples)]
            samples = samples[indices]

        # Stream in 30ms chunks (480 samples at 16kHz)
        chunk_size = 480
        speech_events = []
        for i in range(0, len(samples), chunk_size):
            chunk = samples[i : i + chunk_size]
            if len(chunk) < chunk_size:
                chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
            frame = rtc.AudioFrame(chunk.tobytes(), 16000, 1, chunk_size)
            stream.push_frame(frame)

        stream.end_input()
        async for ev in stream:
            if "SPEECH" in str(ev.type):
                print("VAD SPEECH EVENT:", ev.type, "prob:", getattr(ev, "probability", None))
                speech_events.append(ev.type)

        print("Total speech events detected:", len(speech_events))

if __name__ == "__main__":
    asyncio.run(main())
