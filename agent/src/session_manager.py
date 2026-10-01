import asyncio
import json
import logging
import time
import uuid
from typing import List, Optional

from livekit import rtc
from livekit.agents.voice import (
    Agent,
    AgentSession,
    AgentStateChangedEvent,
    ConversationItemAddedEvent,
    UserInputTranscribedEvent,
    UserStateChangedEvent,
)

from agent.src.db import AgentConfig, db_client
from agent.src.latency_tracker import CallLatencyTracker

logger = logging.getLogger("agent.session_manager")


class CallSessionState:
    """
    Encapsulates all per-call isolated state for an active voice session.
    Guarantees no state leakage across calls or workers.
    """

    def __init__(
        self,
        call_id: uuid.UUID,
        room_name: str,
        agent_config: AgentConfig,
    ):
        self.call_id = call_id
        self.room_name = room_name
        self.agent_config = agent_config
        self.start_monotonic: float = time.monotonic()
        self.interruption_count: int = 0
        self.turn_count: int = 0
        self.supervisor_whispers: List[str] = []
        self._transcript_tasks: List[asyncio.Task] = []
        self.latency_tracker = CallLatencyTracker(
            call_id=self.call_id,
            room_name=self.room_name,
            agent_id=self.agent_config.id,
            start_monotonic=self.start_monotonic,
            save_measurement_fn=db_client.save_latency_measurement,
        )

    def add_supervisor_whisper(self, whisper_text: str) -> str:
        """
        Records a confidential supervisor whisper into session state and persists
        it to PostgreSQL as is_private=True. Returns the updated effective system prompt.
        """
        clean_text = whisper_text.strip()
        if not clean_text:
            return self.get_effective_system_prompt()

        self.supervisor_whispers.append(clean_text)
        self.record_turn(speaker="supervisor", text=clean_text, is_private=True)
        return self.get_effective_system_prompt()

    def get_effective_system_prompt(self) -> str:
        """
        Generates the dynamic system prompt combining base DB configuration with
        active supervisor coaching instructions, while strictly prohibiting supervisor disclosure.
        """
        base = self.agent_config.system_prompt
        if not self.supervisor_whispers:
            return base

        whisper_bullets = "\n".join(f"- {w}" for w in self.supervisor_whispers)
        return (
            f"{base}\n\n"
            f"[CONFIDENTIAL SUPERVISOR COACHING INSTRUCTIONS]:\n"
            f"{whisper_bullets}\n\n"
            f"Strict Guidelines for Supervisor Instructions:\n"
            f"1. In your upcoming response, incorporate and follow the supervisor's coaching instructions naturally.\n"
            f"2. Stealth Guarantee: You must NEVER disclose, mention, or hint to the customer that a supervisor, "
            f"coach, or third party instructed you, helped you, or is present. Do NOT say 'My supervisor told me...' or any similar phrase.\n"
            f"3. Speak strictly in your persona as Acme Support Agent."
        )

    def get_relative_time_ms(self) -> int:
        """
        Calculates millisecond offset relative to the start of this specific call session.
        Always non-negative.
        """
        elapsed_s = time.monotonic() - self.start_monotonic
        return max(0, int(elapsed_s * 1000))

    def record_barge_in(self) -> None:
        """
        Records a barge-in interruption occurrence on this session.
        """
        self.interruption_count += 1
        logger.info(
            "Call %s: Recorded barge-in interruption (total=%d)",
            self.call_id, self.interruption_count,
        )

    def record_turn(self, speaker: str, text: str, is_private: bool = False) -> None:
        """
        Asynchronously persists a dialogue turn to PostgreSQL.
        """
        clean_text = text.strip()
        if not clean_text:
            return

        # Deduplicate consecutive identical turns from the same speaker
        if hasattr(self, "_last_recorded_turn") and self._last_recorded_turn == (speaker, clean_text):
            logger.debug("Skipping duplicate consecutive turn for %s: %s", speaker, clean_text)
            return
        self._last_recorded_turn = (speaker, clean_text)

        # Never record initial greeting more than once per call
        if speaker == "agent" and "thank you for calling acme support" in clean_text.lower():
            if getattr(self, "_has_recorded_greeting", False):
                logger.debug("Skipping duplicate greeting record_turn for call %s", self.call_id)
                return
            self._has_recorded_greeting = True

        rel_time_ms = self.get_relative_time_ms()
        self.turn_count += 1

        task = asyncio.create_task(
            self._save_transcript_entry(
                speaker=speaker,
                text=clean_text,
                relative_time_ms=rel_time_ms,
                is_private=is_private,
            )
        )
        self._transcript_tasks.append(task)

    async def _save_transcript_entry(
        self,
        speaker: str,
        text: str,
        relative_time_ms: int,
        is_private: bool,
    ) -> None:
        try:
            await db_client.save_transcript_entry(
                call_id=self.call_id,
                speaker=speaker,
                text=text,
                relative_time_ms=relative_time_ms,
                is_private=is_private,
            )
        except Exception as e:
            logger.error(
                "Call %s: Failed to persist transcript entry for %s: %s",
                self.call_id, speaker, e,
            )

    async def flush(self) -> None:
        """
        Awaits all pending asynchronous database writes before session teardown.
        """
        if self._transcript_tasks:
            pending = [t for t in self._transcript_tasks if not t.done()]
            if pending:
                logger.debug("Flushing %d pending transcript writes for call %s", len(pending), self.call_id)
                await asyncio.gather(*pending, return_exceptions=True)
            self._transcript_tasks.clear()
        # Flush pending latency DB records
        await self.latency_tracker.flush()


def attach_session_listeners(session: AgentSession, state: CallSessionState) -> None:
    """
    Attaches event listeners to the AgentSession to capture customer transcription,
    agent dialogue turns, and latency milestones into the database.
    """

    @session.on("user_state_changed")
    def on_user_state_changed(ev: UserStateChangedEvent) -> None:
        """
        Detects when the user stops speaking.
        """
        if ev.old_state == "speaking" and ev.new_state in ("listening", "idle"):
            state.latency_tracker.record_user_stop()

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(ev: UserInputTranscribedEvent) -> None:
        """
        Captures final STT transcriptions for the customer and records stt_final milestone.
        """
        if ev.is_final and ev.transcript:
            state.latency_tracker.record_stt_final()
            logger.info("Call %s [Customer]: %s", state.call_id, ev.transcript)
            state.record_turn(
                speaker="customer",
                text=ev.transcript,
                is_private=False,
            )

    @session.on("agent_state_changed")
    def on_agent_state_changed(ev: AgentStateChangedEvent) -> None:
        """
        Detects when agent begins uttering speech into the room (audio published).
        """
        if ev.new_state == "speaking":
            state.latency_tracker.record_audio_published()

    @session.on("conversation_item_added")
    def on_conversation_item_added(ev: ConversationItemAddedEvent) -> None:
        """
        Captures conversation turns (including agent answers).
        If speech was interrupted, ev.item reflects the truncated text that was spoken.
        """
        item = ev.item
        role = getattr(item, "role", None)
        text = getattr(item, "text_content", None) or ""

        if role == "assistant" and text:
            was_interrupted = getattr(item, "interrupted", False)
            if was_interrupted:
                logger.info("Call %s [Agent - Interrupted]: %s", state.call_id, text)
            else:
                logger.info("Call %s [Agent]: %s", state.call_id, text)

            state.record_turn(
                speaker="agent",
                text=text,
                is_private=False,
            )

            # Reconcile turn latency metrics and persist to PostgreSQL
            livekit_metrics = getattr(item, "metrics", None)
            state.latency_tracker.finalize_turn(livekit_metrics=livekit_metrics)
        elif role == "user" and text and not getattr(ev, "_handled", False):
            # Fallback if user turn was added through conversation item
            pass


def attach_supervisor_whisper_listener(
    room: rtc.Room,
    session: AgentSession,
    agent: Agent,
    state: CallSessionState,
) -> None:
    """
    Listens for confidential supervisor whisper instructions sent over LiveKit data channel.
    Injects instructions into the agent's dynamic context and persists them with is_private=True.
    Strictly prevents supervisor disclosure to the customer.
    """
    @room.on("data_received")
    def on_data_received(data_packet: rtc.DataPacket) -> None:
        try:
            topic = getattr(data_packet, "topic", "")
            raw_text = data_packet.data.decode("utf-8", errors="ignore").strip()
            if not raw_text:
                return

            whisper_text = None
            try:
                data_json = json.loads(raw_text)
                if isinstance(data_json, dict):
                    if data_json.get("type") == "whisper" or topic == "whisper" or "text" in data_json or "instruction" in data_json:
                        whisper_text = str(data_json.get("text") or data_json.get("instruction") or "").strip()
            except Exception:
                pass

            if not whisper_text:
                if topic == "whisper":
                    whisper_text = raw_text
                else:
                    return

            logger.info(
                "Call %s: Received private supervisor whisper: '%s' (topic=%s)",
                state.call_id, whisper_text, topic,
            )

            # 1. Record confidential whisper in DB with is_private=True and update state
            effective_prompt = state.add_supervisor_whisper(whisper_text)

            # 2. Update agent system instructions asynchronously
            asyncio.create_task(agent.update_instructions(effective_prompt))

            # 3. Inject system coaching message into session chat history for immediate next-turn effect
            system_instruction = (
                f"[CONFIDENTIAL SUPERVISOR COACHING INSTRUCTION]:\n{whisper_text}\n\n"
                f"CRITICAL DIRECTIVES:\n"
                f"1. IMMEDIATE PRIORITY: You must naturally apply and fulfill this coaching instruction in your response "
                f"(e.g. if the instruction mentions 'Offer a 10% discount', enthusiastically offer a 10% discount on the customer's order). "
                f"This coaching directive takes absolute precedence over any standard discount or credit restrictions.\n"
                f"2. STEALTH REQUIREMENT: You must NEVER disclose, mention, or hint to the customer that a supervisor, "
                f"manager, or coach gave you instructions or that a whisper was received. Do NOT say 'My supervisor told me...', "
                f"'I was told to offer...', or anything similar. Present all offers or statements as your own direct action.\n"
                f"3. Speak strictly in your persona as Acme Support Agent."
            )
            try:
                session.history.add_message(role="system", content=system_instruction)
            except Exception as e:
                logger.warning("Could not add system message to session history: %s", e)

        except Exception as err:
            logger.error("Error processing supervisor data channel packet: %s", err)

