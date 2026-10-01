import asyncio
import logging
from typing import Any, Optional

from livekit import rtc
from livekit.agents import llm, stt, tts
from livekit.agents.types import APIConnectOptions

logger = logging.getLogger("agent.mock_providers")


class MockLLMStream(llm.LLMStream):
    async def _run(self) -> None:
        last_message = ""
        for msg in reversed(self._chat_ctx.messages()):
            if msg.role == "user":
                last_message = msg.text_content
                break

        reply = f"Thank you for contacting Acme Support. I received: '{last_message}'. How can I help further?"
        tokens = reply.split(" ")
        for token in tokens:
            chunk = llm.ChatChunk(
                id="mock_chunk",
                delta=llm.ChoiceDelta(
                    role="assistant",
                    content=token + " ",
                ),
            )
            await self._event_ch.send(chunk)
            await asyncio.sleep(0.01)


class MockLLM(llm.LLM):
    def __init__(self, model: str = "gpt-4o-mini"):
        super().__init__()
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: Optional[list[llm.Tool]] = None,
        conn_options: APIConnectOptions = APIConnectOptions(),
        parallel_tool_calls: Any = None,
        tool_choice: Any = None,
        extra_kwargs: Any = None,
    ) -> llm.LLMStream:
        return MockLLMStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )


class MockChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        sample_rate = 24000
        num_channels = 1
        samples = int(sample_rate * 0.1)  # 100ms silence
        pcm_silence = b"\x00" * (samples * 2)

        output_emitter.initialize(
            request_id="mock_req",
            sample_rate=sample_rate,
            num_channels=num_channels,
            mime_type="audio/pcm",
        )
        output_emitter.push(pcm_silence)
        output_emitter.flush()


class MockTTS(tts.TTS):
    def __init__(self, voice: str = "alloy"):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=24000,
            num_channels=1,
        )
        self.voice = voice

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = APIConnectOptions(),
    ) -> tts.ChunkedStream:
        return MockChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )


class MockSTT(stt.STT):
    def __init__(self):
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False),
        )

    async def _recognize_impl(
        self,
        buffer: Any,
        *,
        language: Any = None,
        conn_options: APIConnectOptions = APIConnectOptions(),
    ) -> stt.SpeechEvent:
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[
                stt.SpeechData(
                    text="Hello, I need help with my account.",
                    language="en",
                    confidence=0.98,
                )
            ],
        )
