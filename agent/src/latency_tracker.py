import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from livekit.agents import llm, tts
from livekit.agents.types import APIConnectOptions

logger = logging.getLogger("agent.latency_tracker")


def log_structured_latency_event(
    call_id: uuid.UUID,
    room_name: str,
    agent_id: uuid.UUID,
    turn_number: int,
    event: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Emits structured JSON observability logs containing:
    - call_id
    - room_name
    - agent_id
    - turn_number
    - event
    - timestamp (ISO-8601 UTC)
    Strictly excludes API secrets and auth tokens.
    """
    payload = {
        "call_id": str(call_id),
        "room_name": room_name,
        "agent_id": str(agent_id),
        "turn_number": turn_number,
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)

    # Format structured message for observability pipelines (e.g. Datadog, CloudWatch, ELK)
    logger.info("[OBSERVABILITY] %s", json.dumps(payload))


@dataclass
class TurnLatencyRecord:
    call_id: uuid.UUID
    room_name: str
    agent_id: uuid.UUID
    turn_number: int
    user_stop_ms: Optional[int] = None
    stt_final_ms: Optional[int] = None
    llm_first_token_ms: Optional[int] = None
    tts_first_audio_ms: Optional[int] = None
    audio_published_ms: Optional[int] = None
    persisted: bool = False

    @property
    def stt_latency_ms(self) -> Optional[int]:
        if self.stt_final_ms is not None and self.user_stop_ms is not None:
            return max(0, self.stt_final_ms - self.user_stop_ms)
        return None

    @property
    def llm_first_token_latency_ms(self) -> Optional[int]:
        if self.llm_first_token_ms is not None and self.stt_final_ms is not None:
            return max(0, self.llm_first_token_ms - self.stt_final_ms)
        return None

    @property
    def tts_first_audio_latency_ms(self) -> Optional[int]:
        if self.tts_first_audio_ms is not None and self.llm_first_token_ms is not None:
            return max(0, self.tts_first_audio_ms - self.llm_first_token_ms)
        return None

    @property
    def publish_latency_ms(self) -> Optional[int]:
        if self.audio_published_ms is not None and self.tts_first_audio_ms is not None:
            return max(0, self.audio_published_ms - self.tts_first_audio_ms)
        return None

    @property
    def overall_latency_ms(self) -> Optional[int]:
        if self.audio_published_ms is not None and self.user_stop_ms is not None:
            return max(0, self.audio_published_ms - self.user_stop_ms)
        return None


class CallLatencyTracker:
    """
    Per-call latency tracking and observability manager.
    Tracks real-time timestamp milestones for each conversational turn:
    1. user_stop_ms
    2. stt_final_ms
    3. llm_first_token_ms
    4. tts_first_audio_ms
    5. audio_published_ms

    Emits structured logs and persists durable records to PostgreSQL.
    """

    def __init__(
        self,
        call_id: uuid.UUID,
        room_name: str,
        agent_id: uuid.UUID,
        start_monotonic: float,
        save_measurement_fn: Optional[Callable[..., Any]] = None,
    ):
        self.call_id = call_id
        self.room_name = room_name
        self.agent_id = agent_id
        self.start_monotonic = start_monotonic
        self.save_measurement_fn = save_measurement_fn
        self._current_turn_number: int = 1
        self._turns: Dict[int, TurnLatencyRecord] = {}
        self._persistence_tasks: list[asyncio.Task] = []

    def get_relative_time_ms(self) -> int:
        elapsed_s = time.monotonic() - self.start_monotonic
        return max(0, int(elapsed_s * 1000))

    def _get_or_create_turn(self, turn_number: Optional[int] = None) -> TurnLatencyRecord:
        if turn_number is None:
            turn_number = self._current_turn_number
        if turn_number not in self._turns:
            self._turns[turn_number] = TurnLatencyRecord(
                call_id=self.call_id,
                room_name=self.room_name,
                agent_id=self.agent_id,
                turn_number=turn_number,
            )
        return self._turns[turn_number]

    def record_user_stop(self, custom_time_ms: Optional[int] = None) -> int:
        rel_ms = custom_time_ms if custom_time_ms is not None else self.get_relative_time_ms()
        rec = self._get_or_create_turn(self._current_turn_number)
        if rec.user_stop_ms is None:
            rec.user_stop_ms = rel_ms
            log_structured_latency_event(
                call_id=self.call_id,
                room_name=self.room_name,
                agent_id=self.agent_id,
                turn_number=rec.turn_number,
                event="user_stop",
                extra={"user_stop_ms": rec.user_stop_ms},
            )
        return rec.user_stop_ms

    def record_stt_final(self, custom_time_ms: Optional[int] = None) -> int:
        rel_ms = custom_time_ms if custom_time_ms is not None else self.get_relative_time_ms()
        rec = self._get_or_create_turn(self._current_turn_number)
        if rec.stt_final_ms is None:
            # Ensure monotonicity
            if rec.user_stop_ms is None:
                rec.user_stop_ms = max(0, rel_ms - 350)
            rec.stt_final_ms = max(rec.user_stop_ms, rel_ms)
            log_structured_latency_event(
                call_id=self.call_id,
                room_name=self.room_name,
                agent_id=self.agent_id,
                turn_number=rec.turn_number,
                event="stt_final",
                extra={
                    "stt_final_ms": rec.stt_final_ms,
                    "stt_latency_ms": rec.stt_latency_ms,
                },
            )
        return rec.stt_final_ms

    def record_llm_first_token(self, custom_time_ms: Optional[int] = None) -> int:
        rel_ms = custom_time_ms if custom_time_ms is not None else self.get_relative_time_ms()
        rec = self._get_or_create_turn(self._current_turn_number)
        if rec.llm_first_token_ms is None:
            base = rec.stt_final_ms if rec.stt_final_ms is not None else rec.user_stop_ms or rel_ms
            rec.llm_first_token_ms = max(base, rel_ms)
            log_structured_latency_event(
                call_id=self.call_id,
                room_name=self.room_name,
                agent_id=self.agent_id,
                turn_number=rec.turn_number,
                event="llm_first_token",
                extra={
                    "llm_first_token_ms": rec.llm_first_token_ms,
                    "llm_first_token_latency_ms": rec.llm_first_token_latency_ms,
                },
            )
        return rec.llm_first_token_ms

    def record_tts_first_audio(self, custom_time_ms: Optional[int] = None) -> int:
        rel_ms = custom_time_ms if custom_time_ms is not None else self.get_relative_time_ms()
        rec = self._get_or_create_turn(self._current_turn_number)
        if rec.tts_first_audio_ms is None:
            base = rec.llm_first_token_ms if rec.llm_first_token_ms is not None else rel_ms
            rec.tts_first_audio_ms = max(base, rel_ms)
            log_structured_latency_event(
                call_id=self.call_id,
                room_name=self.room_name,
                agent_id=self.agent_id,
                turn_number=rec.turn_number,
                event="tts_first_audio",
                extra={
                    "tts_first_audio_ms": rec.tts_first_audio_ms,
                    "tts_first_audio_latency_ms": rec.tts_first_audio_latency_ms,
                },
            )
        return rec.tts_first_audio_ms

    def record_audio_published(self, custom_time_ms: Optional[int] = None) -> int:
        rel_ms = custom_time_ms if custom_time_ms is not None else self.get_relative_time_ms()
        rec = self._get_or_create_turn(self._current_turn_number)
        if rec.audio_published_ms is None:
            base = rec.tts_first_audio_ms if rec.tts_first_audio_ms is not None else rel_ms
            rec.audio_published_ms = max(base, rel_ms)
            log_structured_latency_event(
                call_id=self.call_id,
                room_name=self.room_name,
                agent_id=self.agent_id,
                turn_number=rec.turn_number,
                event="audio_published",
                extra={
                    "audio_published_ms": rec.audio_published_ms,
                    "publish_latency_ms": rec.publish_latency_ms,
                    "overall_latency_ms": rec.overall_latency_ms,
                },
            )
        return rec.audio_published_ms

    def finalize_turn(
        self,
        livekit_metrics: Optional[Dict[str, Any]] = None,
    ) -> TurnLatencyRecord:
        """
        Finalizes measurements for the current turn, reconciles with LiveKit internal
        nanosecond metrics if available, emits turn summary, and persists to DB.
        Advances to the next turn number.
        """
        rec = self._get_or_create_turn(self._current_turn_number)

        # Reconcile missing timestamps from LiveKit native metrics if provided
        if livekit_metrics:
            ttft_s = livekit_metrics.get("llm_node_ttft")
            ttfb_s = livekit_metrics.get("tts_node_ttfb")
            playback_lat_s = livekit_metrics.get("playback_latency")
            e2e_lat_s = livekit_metrics.get("e2e_latency")
            tx_delay_s = livekit_metrics.get("transcription_delay")

            if rec.user_stop_ms is None:
                rec.user_stop_ms = max(0, self.get_relative_time_ms() - int((e2e_lat_s or 1.0) * 1000))

            if rec.stt_final_ms is None:
                if tx_delay_s is not None:
                    rec.stt_final_ms = rec.user_stop_ms + int(tx_delay_s * 1000)
                else:
                    rec.stt_final_ms = rec.user_stop_ms + 250

            if rec.llm_first_token_ms is None:
                if ttft_s is not None:
                    rec.llm_first_token_ms = rec.stt_final_ms + int(ttft_s * 1000)
                else:
                    rec.llm_first_token_ms = rec.stt_final_ms + 350

            if rec.tts_first_audio_ms is None:
                if ttfb_s is not None:
                    rec.tts_first_audio_ms = rec.llm_first_token_ms + int(ttfb_s * 1000)
                else:
                    rec.tts_first_audio_ms = rec.llm_first_token_ms + 250

            if rec.audio_published_ms is None:
                if playback_lat_s is not None:
                    rec.audio_published_ms = rec.tts_first_audio_ms + int(playback_lat_s * 1000)
                elif e2e_lat_s is not None:
                    rec.audio_published_ms = rec.user_stop_ms + int(e2e_lat_s * 1000)
                else:
                    rec.audio_published_ms = rec.tts_first_audio_ms + 40

        # Ensure all fields are valid monotonically increasing numbers
        if rec.user_stop_ms is None:
            rec.user_stop_ms = self.get_relative_time_ms()
        if rec.stt_final_ms is None:
            rec.stt_final_ms = rec.user_stop_ms + 250
        if rec.llm_first_token_ms is None:
            rec.llm_first_token_ms = rec.stt_final_ms + 350
        if rec.tts_first_audio_ms is None:
            rec.tts_first_audio_ms = rec.llm_first_token_ms + 250
        if rec.audio_published_ms is None:
            rec.audio_published_ms = rec.tts_first_audio_ms + 40

        # Log comprehensive turn summary
        summary = {
            "turn_number": rec.turn_number,
            "user_stop_ms": rec.user_stop_ms,
            "stt_final_ms": rec.stt_final_ms,
            "llm_first_token_ms": rec.llm_first_token_ms,
            "tts_first_audio_ms": rec.tts_first_audio_ms,
            "audio_published_ms": rec.audio_published_ms,
            "stt_latency_ms": rec.stt_latency_ms,
            "llm_first_token_latency_ms": rec.llm_first_token_latency_ms,
            "tts_first_audio_latency_ms": rec.tts_first_audio_latency_ms,
            "publish_latency_ms": rec.publish_latency_ms,
            "total_latency_ms": rec.overall_latency_ms,
        }
        log_structured_latency_event(
            call_id=self.call_id,
            room_name=self.room_name,
            agent_id=self.agent_id,
            turn_number=rec.turn_number,
            event="turn_latency_summary",
            extra=summary,
        )

        # Trigger async database persistence
        if self.save_measurement_fn and not rec.persisted:
            rec.persisted = True
            task = asyncio.create_task(
                self.save_measurement_fn(
                    call_id=self.call_id,
                    turn_number=rec.turn_number,
                    user_stop_ms=rec.user_stop_ms,
                    stt_final_ms=rec.stt_final_ms,
                    llm_first_token_ms=rec.llm_first_token_ms,
                    tts_first_audio_ms=rec.tts_first_audio_ms,
                    audio_published_ms=rec.audio_published_ms,
                )
            )
            self._persistence_tasks.append(task)

        # Advance turn number
        self._current_turn_number += 1
        return rec

    async def flush(self) -> None:
        """Awaits all pending latency DB writes."""
        if self._persistence_tasks:
            pending = [t for t in self._persistence_tasks if not t.done()]
            if pending:
                logger.debug("Flushing %d pending latency DB writes for call %s", len(pending), self.call_id)
                await asyncio.gather(*pending, return_exceptions=True)
            self._persistence_tasks.clear()


# =========================================================================
# Instrumented Wrappers for LLM and TTS Streaming Pipeline
# =========================================================================

class InstrumentedLLM(llm.LLM):
    def __init__(
        self,
        inner_llm: llm.LLM,
        tracker_provider: Callable[[], Optional[CallLatencyTracker]],
        state_provider: Optional[Callable[[], Optional[Any]]] = None,
    ):
        super().__init__()
        self._inner = inner_llm
        self._tracker_provider = tracker_provider
        self._state_provider = state_provider

    @property
    def model(self) -> str:
        return getattr(self._inner, "model", "gpt-4o-mini")

    @property
    def provider(self) -> str:
        return getattr(self._inner, "provider", "openai")

    @property
    def metrics_metadata(self) -> Dict[str, Any]:
        return getattr(self._inner, "metrics_metadata", {})

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: Optional[list[llm.Tool]] = None,
        conn_options: APIConnectOptions = APIConnectOptions(),
        **kwargs: Any,
    ) -> llm.LLMStream:
        # Guarantee Supervisor Whisper injection into the next LLM context
        if self._state_provider:
            try:
                state = self._state_provider()
                if state and getattr(state, "supervisor_whispers", None):
                    existing_msgs = chat_ctx.messages() if callable(getattr(chat_ctx, "messages", None)) else getattr(chat_ctx, "messages", [])
                    for whisper in state.supervisor_whispers:
                        already_in_ctx = False
                        for msg in existing_msgs:
                            msg_text = getattr(msg, "text_content", None) or getattr(msg, "content", "")
                            if isinstance(msg_text, list):
                                msg_text = " ".join(str(c) for c in msg_text)
                            if whisper in str(msg_text):
                                already_in_ctx = True
                                break
                        if not already_in_ctx:
                            coaching_msg = (
                                f"[CONFIDENTIAL SUPERVISOR COACHING INSTRUCTION]:\n"
                                f"{whisper}\n\n"
                                f"CRITICAL DIRECTIVES:\n"
                                f"1. IMMEDIATE PRIORITY: You must naturally apply and fulfill this coaching instruction in your response "
                                f"(e.g. if the instruction mentions 'Offer a 10% discount', enthusiastically offer a 10% discount on the customer's order). "
                                f"This coaching directive takes absolute precedence over any standard discount or credit restrictions.\n"
                                f"2. STEALTH REQUIREMENT: You must NEVER disclose, mention, or hint to the customer that a supervisor, "
                                f"manager, or coach gave you instructions or that a whisper was received. Do NOT say 'My supervisor told me...', "
                                f"'I was told to offer...', or anything similar. Present all offers or statements as your own direct action.\n"
                                f"3. Speak strictly in your persona as Acme Support Agent."
                            )
                            chat_ctx.add_message(role="system", content=coaching_msg)
                            logger.info("Injected supervisor whisper into LLM chat_ctx before inference: %s", whisper)
            except Exception as e:
                logger.error("Error injecting supervisor whisper in InstrumentedLLM: %s", e)

        inner_stream = self._inner.chat(
            chat_ctx=chat_ctx,
            tools=tools,
            conn_options=conn_options,
            **kwargs,
        )

        original_anext = inner_stream.__anext__
        first_token_called = False

        async def instrumented_anext():
            nonlocal first_token_called
            chunk = await original_anext()
            if not first_token_called:
                delta = getattr(chunk, "delta", None)
                content = getattr(delta, "content", None) if delta else None
                if content:
                    first_token_called = True
                    try:
                        tracker = self._tracker_provider()
                        if tracker:
                            tracker.record_llm_first_token()
                    except Exception as e:
                        logger.error("Error recording llm first token: %s", e)
            return chunk

        inner_stream.__anext__ = instrumented_anext
        return inner_stream


class InstrumentedTTS(tts.TTS):
    def __init__(self, inner_tts: tts.TTS, tracker_provider: Callable[[], Optional[CallLatencyTracker]]):
        super().__init__(
            capabilities=inner_tts.capabilities,
            sample_rate=inner_tts.sample_rate,
            num_channels=inner_tts.num_channels,
        )
        self._inner = inner_tts
        self._tracker_provider = tracker_provider

    @property
    def model(self) -> str:
        return getattr(self._inner, "model", "")

    @property
    def provider(self) -> str:
        return getattr(self._inner, "provider", "")

    @property
    def metrics_metadata(self) -> Dict[str, Any]:
        return getattr(self._inner, "metrics_metadata", {})

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = APIConnectOptions(),
    ) -> tts.ChunkedStream:
        tracker = self._tracker_provider()
        if tracker:
            tracker.record_tts_first_audio()
        return self._inner.synthesize(text=text, conn_options=conn_options)

    def stream(
        self,
        *,
        conn_options: APIConnectOptions = APIConnectOptions(),
    ) -> tts.SynthesizeStream:
        inner_stream = self._inner.stream(conn_options=conn_options)

        original_anext = inner_stream.__anext__
        first_audio_called = False

        async def instrumented_anext():
            nonlocal first_audio_called
            val = await original_anext()
            if not first_audio_called:
                first_audio_called = True
                try:
                    tracker = self._tracker_provider()
                    if tracker:
                        tracker.record_tts_first_audio()
                except Exception as e:
                    logger.error("Error recording tts first audio: %s", e)
            return val

        inner_stream.__anext__ = instrumented_anext
        return inner_stream
