import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

from livekit.agents import JobContext, JobProcess, WorkerOptions, cli
from livekit.agents.voice import Agent, AgentSession, CloseEvent, ErrorEvent
from livekit import rtc
from livekit.plugins import silero
try:
    from livekit.plugins import openai
except Exception:
    openai = None
try:
    from livekit.plugins import deepgram
except Exception:
    deepgram = None

from agent.src.config import settings
from agent.src.db import AgentConfig, CallRecord, db_client
from agent.src.interruption import (
    build_turn_handling_options,
    setup_interruption_tracking,
)
from agent.src.pipeline import (
    PipelineError,
    ProviderConfigurationError,
    create_pipeline,
)
from agent.src.latency_tracker import InstrumentedLLM, InstrumentedTTS
from agent.src.session_manager import (
    CallSessionState,
    attach_session_listeners,
    attach_supervisor_whisper_listener,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
)
logger = logging.getLogger("agent.worker")


async def resolve_agent_and_call(
    ctx: JobContext,
) -> tuple[Optional[CallRecord], Optional[AgentConfig]]:
    """
    Resolves the active Call and Agent records from PostgreSQL.
    Extracts agent_id from room metadata or falls back to querying the database
    by room name.
    """
    room_name = ctx.room.name
    logger.info("Resolving call and agent configuration for room: %s", room_name)

    call_record = await db_client.get_call_by_room(room_name)
    if not call_record:
        logger.error("Call record not found in PostgreSQL for room: %s", room_name)
        return None, None

    # Check if room metadata specifies an agent override
    agent_id: Optional[uuid.UUID] = None
    if ctx.room.metadata:
        try:
            meta = json.loads(ctx.room.metadata)
            if "agent_id" in meta:
                agent_id = uuid.UUID(meta["agent_id"])
        except Exception as e:
            logger.warning("Could not parse room metadata JSON: %s", e)

    if not agent_id:
        agent_id = call_record.agent_id

    # Load agent configuration for this call
    agent_config = await db_client.load_agent_config(agent_id)
    if not agent_config:
        logger.error(
            "Agent configuration not found in PostgreSQL for agent_id: %s (call: %s)",
            agent_id, call_record.id,
        )
        return call_record, None

    logger.info(
        "Successfully loaded agent config from DB: name='%s', voice='%s', model='%s'",
        agent_config.name, agent_config.voice, agent_config.model,
    )
    return call_record, agent_config


async def entrypoint(ctx: JobContext) -> None:
    """
    Main worker loop for an assigned call session. Handles room connection,
    pipeline wiring, turn-taking with barge-in, and post-call cleanup.
    """
    logger.info("Starting voice agent worker session for room: %s", ctx.room.name)

    # Join the LiveKit room
    try:
        await ctx.connect()
        logger.info("Connected to LiveKit room: %s", ctx.room.name)
    except Exception as e:
        logger.error("Failed to connect to LiveKit room %s: %s", ctx.room.name, e)
        raise

    # Look up call record and agent instructions
    call_record, agent_config = await resolve_agent_and_call(ctx)

    if not call_record:
        logger.error("Invalid call: Room %s has no matching database record. Aborting.", ctx.room.name)
        return

    if not agent_config:
        logger.error("Invalid config: Agent configuration missing for call %s. Marking call FAILED.", call_record.id)
        await db_client.update_call_status(
            call_id=call_record.id,
            status="FAILED",
            ended_at=datetime.now(timezone.utc),
        )
        return

    # Track per-call session state and telemetry
    session_state = CallSessionState(
        call_id=call_record.id,
        room_name=ctx.room.name,
        agent_config=agent_config,
    )

    # Mark call active in database
    now_utc = datetime.now(timezone.utc)
    await db_client.update_call_status(
        call_id=call_record.id,
        status="ACTIVE",
        started_at=now_utc,
    )

    # Build pipeline components (Silero VAD, STT, LLM, TTS)
    try:
        vad_cached = ctx.proc.userdata.get("vad") if hasattr(ctx, "proc") and hasattr(ctx.proc, "userdata") else None
        pipeline = create_pipeline(agent_config, vad_instance=vad_cached)
    except ProviderConfigurationError as pce:
        logger.error("Provider configuration error for call %s: %s", call_record.id, pce)
        await db_client.update_call_status(
            call_id=call_record.id,
            status="FAILED",
            ended_at=datetime.now(timezone.utc),
        )
        return
    except Exception as e:
        logger.error("Pipeline initialization failed for call %s: %s", call_record.id, e)
        await db_client.update_call_status(
            call_id=call_record.id,
            status="FAILED",
            ended_at=datetime.now(timezone.utc),
        )
        return

    # Initialize agent instructions from dynamic config
    agent = Agent(
        instructions=agent_config.system_prompt,
    )

    # Configure session with turn handling, latency tracking, and barge-in
    turn_handling = build_turn_handling_options()
    instrumented_llm = InstrumentedLLM(
        inner_llm=pipeline.llm,
        tracker_provider=lambda: session_state.latency_tracker,
        state_provider=lambda: session_state,
    )
    instrumented_tts = InstrumentedTTS(
        inner_tts=pipeline.tts,
        tracker_provider=lambda: session_state.latency_tracker,
    )
    session = AgentSession(
        vad=pipeline.vad,
        stt=pipeline.stt,
        llm=instrumented_llm,
        tts=instrumented_tts,
        turn_handling=turn_handling,
        use_tts_aligned_transcript=True,  # Keeps transcript aligned with what was actually voiced
    )

    # Attach session listeners and supervisor whisper channel
    setup_interruption_tracking(session, session_state)
    attach_session_listeners(session, session_state)
    attach_supervisor_whisper_listener(ctx.room, session, agent, session_state)

    # Handle pipeline runtime errors
    call_failed = False

    @session.on("error")
    def on_pipeline_error(ev: ErrorEvent) -> None:
        nonlocal call_failed
        logger.error(
            "Call %s encountered pipeline error from source '%s': %s",
            session_state.call_id,
            ev.source,
            ev.error,
        )
        call_failed = True

    # Start the live agent session in the room
    try:
        await session.start(agent=agent, room=ctx.room)
        logger.info("AgentSession started successfully in room: %s", ctx.room.name)
    except Exception as e:
        logger.error("Failed to start AgentSession in room %s: %s", ctx.room.name, e)
        await db_client.update_call_status(
            call_id=call_record.id,
            status="FAILED",
            ended_at=datetime.now(timezone.utc),
        )
        return

    # Deliver recording disclosure greeting
    initial_disclosure = (
        "Thank you for calling Acme Support. Please note that this call is recorded "
        "for quality assurance. How can I help you today?"
    )
    try:
        logger.info("Playing initial greeting with mandatory recording disclosure...")
        session_state.record_turn(speaker="agent", text=initial_disclosure)
        handle = session.say(initial_disclosure, allow_interruptions=True)
    except Exception as e:
        logger.error("Failed to voice initial recording disclosure: %s", e)

    # Wait for session close or all participants leaving
    close_future: asyncio.Future[None] = asyncio.get_event_loop().create_future()

    @session.on("close")
    def on_session_close(ev: CloseEvent) -> None:
        logger.info("AgentSession close event received: reason=%s", ev.reason)
        if not close_future.done():
            close_future.set_result(None)

    @ctx.room.on("disconnected")
    def on_room_disconnected(reason: rtc.DisconnectReason) -> None:
        logger.info("LiveKit room disconnected: reason=%s", reason)
        if not close_future.done():
            close_future.set_result(None)

    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(participant: rtc.RemoteParticipant) -> None:
        logger.info("Remote participant disconnected: %s", participant.identity)
        remotes = [
            p for p in ctx.room.remote_participants.values()
            if not p.identity.startswith("agent")
        ]
        if not remotes:
            logger.info("All customer and supervisor participants left room. Ending call session.")
            if not close_future.done():
                close_future.set_result(None)

    async def _on_shutdown() -> None:
        if not close_future.done():
            close_future.set_result(None)

    ctx.add_shutdown_callback(_on_shutdown)

    try:
        await close_future
    except asyncio.CancelledError:
        logger.info("Call session cancelled.")
    finally:
        # Teardown: flush transcript records, evaluate compliance, and finalize call state
        logger.info("Tearing down call session: %s", session_state.call_id)
        await session_state.flush()

        try:
            from backend.app.services.compliance_service import compliance_service
            async with db_client.session() as db_session:
                await compliance_service.run_and_persist_compliance(session_state.call_id, db_session)
            logger.info("Call %s compliance successfully evaluated and persisted.", session_state.call_id)
        except Exception as e:
            logger.error("Failed to run compliance during worker teardown for %s: %s", session_state.call_id, e)
            final_status = "FAILED" if call_failed else "ENDED"
            await db_client.update_call_status(
                call_id=session_state.call_id,
                status=final_status,
                ended_at=datetime.now(timezone.utc),
            )
        else:
            if call_failed:
                await db_client.update_call_status(
                    call_id=session_state.call_id,
                    status="FAILED",
                    ended_at=datetime.now(timezone.utc),
                )


def prewarm(proc: JobProcess) -> None:
    """Prewarm function running on the main thread of worker processes."""
    proc.userdata["vad"] = silero.VAD.load()


def main() -> None:
    """
    CLI entrypoint for running the LiveKit Voice Agent Worker.
    Usage:
        python -m agent.src.worker start
        python -m agent.src.worker dev
    """
    logger.info("Initializing LiveKit Voice Agent Worker...")
    logger.info("LiveKit URL: %s", settings.livekit_connection_url)
    logger.info("Database URL: %s", settings.DATABASE_URL)

    options = WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm,
        ws_url=settings.livekit_connection_url,
        api_key=settings.LIVEKIT_API_KEY,
        api_secret=settings.LIVEKIT_API_SECRET,
        agent_name=settings.WORKER_AGENT_NAME,
    )

    cli.run_app(options)


if __name__ == "__main__":
    main()
