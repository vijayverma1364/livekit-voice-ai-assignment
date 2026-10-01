"""
Barge-in and turn handling configuration.

Manages VAD-based interruption thresholds, endpointing delays, and logs
turn state transitions to keep dialogue history aligned with what was
actually spoken.
"""

import logging
from typing import TYPE_CHECKING, Any

from livekit.agents.voice import (
    AgentSession,
    AgentStateChangedEvent,
    SpeechCreatedEvent,
    UserStateChangedEvent,
)
from livekit.agents.voice.turn import (
    EndpointingOptions,
    InterruptionOptions,
    PreemptiveGenerationOptions,
    TurnHandlingOptions,
)

from agent.src.config import settings

if TYPE_CHECKING:
    from agent.src.session_manager import CallSessionState

logger = logging.getLogger("agent.interruption")


def build_turn_handling_options() -> TurnHandlingOptions:
    """
    Builds turn detection and barge-in settings for the agent session.
    """
    interruption_options = InterruptionOptions(
        enabled=settings.INTERRUPTION_ENABLED,
        mode="vad",
        min_duration=settings.INTERRUPTION_MIN_DURATION,
        discard_audio_if_uninterruptible=False,
        resume_false_interruption=True,
    )

    endpointing_options = EndpointingOptions(
        min_delay=settings.MIN_ENDPOINTING_DELAY,
        max_delay=settings.MAX_ENDPOINTING_DELAY,
    )
    endpointing_options["min_endpointing_delay"] = settings.MIN_ENDPOINTING_DELAY
    endpointing_options["max_endpointing_delay"] = settings.MAX_ENDPOINTING_DELAY

    preemptive_options = PreemptiveGenerationOptions(
        enabled=False,
    )

    logger.info(
        "Built TurnHandlingOptions: interruption_enabled=%s, mode=vad, min_duration=%.2fs, min_delay=%.2fs",
        settings.INTERRUPTION_ENABLED,
        settings.INTERRUPTION_MIN_DURATION,
        settings.MIN_ENDPOINTING_DELAY,
    )

    return TurnHandlingOptions(
        interruption=interruption_options,
        endpointing=endpointing_options,
        preemptive_generation=preemptive_options,
    )


def setup_interruption_tracking(session: AgentSession, state: "CallSessionState") -> None:
    """
    Hooks event listeners into the AgentSession to monitor and log barge-in interruptions,
    ensuring full observability of interruption events and history adjustments.
    """

    @session.on("user_state_changed")
    def on_user_state_changed(ev: UserStateChangedEvent) -> None:
        """
        Detects when customer transitions to 'speaking'.
        If the agent is also currently 'speaking', a barge-in event is in progress.
        """
        if ev.new_state == "speaking" and session.agent_state == "speaking":
            logger.info(
                "[BARGE-IN TRIGGERED] Customer began speaking while agent was voicing audio. "
                "Halting agent speech and switching to customer input.",
            )
            state.record_barge_in()

    @session.on("agent_state_changed")
    def on_agent_state_changed(ev: AgentStateChangedEvent) -> None:
        """
        Monitors agent transitions between 'listening', 'thinking', and 'speaking'.
        """
        logger.debug(
            "[AGENT STATE] Transitioned from '%s' to '%s'",
            ev.old_state,
            ev.new_state,
        )

    @session.on("speech_created")
    def on_speech_created(ev: SpeechCreatedEvent) -> None:
        """
        Tracks created speech handles and attaches a completion callback
        to verify if the utterance was cleanly completed or interrupted mid-sentence.
        """
        handle = ev.speech_handle

        def on_speech_done(_: Any) -> None:
            if handle.interrupted:
                logger.warning(
                    "[BARGE-IN APPLIED] Agent speech handle %s was interrupted! "
                    "Unspoken text was stripped from conversation history.",
                    handle.id,
                )
            else:
                logger.debug("[SPEECH COMPLETED] Agent speech handle %s finished cleanly.", handle.id)

        handle.add_done_callback(on_speech_done)
