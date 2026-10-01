import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.pool import NullPool

from agent.src.config import settings
from agent.src.db import AgentConfig, CallRecord, DBAgent, DBCall, DBTranscriptEntry, db_client
from agent.src.interruption import build_turn_handling_options
from agent.src.pipeline import (
    ProviderConfigurationError,
    create_pipeline,
)
from agent.src.session_manager import CallSessionState


@pytest.fixture(autouse=True)
def configure_test_db_pool():
    """
    Ensures db_client uses NullPool during pytest execution
    to prevent connection sharing across individual test event loops.
    """
    db_client.reconfigure_pool(NullPool)
    yield


@pytest.mark.asyncio
async def test_agent_db_config_loading():
    """
    Verifies that the worker dynamically loads agent configuration
    (name, system_prompt, voice, model) from PostgreSQL by agent ID.
    Guarantees the system prompt is loaded from the database and not hard-coded.
    """
    test_agent_id = uuid.uuid4()
    custom_prompt = (
        "You are a dedicated Acme Support agent. Always greet the user politely. "
        "Notice: this call is recorded."
    )

    async with db_client.session() as session:
        agent = DBAgent(
            id=test_agent_id,
            name="Unit Test Support Agent",
            system_prompt=custom_prompt,
            voice="nova",
            model="gpt-4o",
        )
        session.add(agent)
        await session.commit()

    try:
        config = await db_client.load_agent_config(test_agent_id)
        assert config is not None
        assert config.id == test_agent_id
        assert config.name == "Unit Test Support Agent"
        assert config.system_prompt == custom_prompt
        assert config.voice == "nova"
        assert config.model == "gpt-4o"
    finally:
        async with db_client.session() as session:
            stmt = select(DBAgent).where(DBAgent.id == test_agent_id)
            obj = (await session.execute(stmt)).scalars().first()
            if obj:
                await session.delete(obj)
                await session.commit()


@pytest.mark.asyncio
async def test_agent_db_call_resolution_and_status_updates():
    """
    Verifies that the worker can lookup a call by room_name and update its lifecycle status.
    """
    test_agent_id = uuid.uuid4()
    test_call_id = uuid.uuid4()
    test_room = f"test-worker-room-{uuid.uuid4().hex[:8]}"

    async with db_client.session() as session:
        agent = DBAgent(
            id=test_agent_id,
            name="Room Lookup Agent",
            system_prompt="Test prompt",
            voice="alloy",
            model="gpt-4o-mini",
        )
        call = DBCall(
            id=test_call_id,
            agent_id=test_agent_id,
            room_name=test_room,
            status="CREATED",
        )
        session.add_all([agent, call])
        await session.commit()

    try:
        # Lookup by room name
        call_rec = await db_client.get_call_by_room(test_room)
        assert call_rec is not None
        assert call_rec.id == test_call_id
        assert call_rec.agent_id == test_agent_id
        assert call_rec.status == "CREATED"

        # Update to ACTIVE
        start_time = datetime.now(timezone.utc)
        updated = await db_client.update_call_status(test_call_id, "ACTIVE", started_at=start_time)
        assert updated is True

        call_rec_active = await db_client.get_call_by_room(test_room)
        assert call_rec_active.status == "ACTIVE"
        assert call_rec_active.started_at is not None

        # Update to ENDED
        end_time = datetime.now(timezone.utc)
        updated_end = await db_client.update_call_status(test_call_id, "ENDED", ended_at=end_time)
        assert updated_end is True

        call_rec_ended = await db_client.get_call_by_room(test_room)
        assert call_rec_ended.status == "ENDED"
        assert call_rec_ended.ended_at is not None
    finally:
        async with db_client.session() as session:
            call_obj = (await session.execute(select(DBCall).where(DBCall.id == test_call_id))).scalars().first()
            if call_obj:
                await session.delete(call_obj)
                await session.commit()
            agent_obj = (await session.execute(select(DBAgent).where(DBAgent.id == test_agent_id))).scalars().first()
            if agent_obj:
                await session.delete(agent_obj)
                await session.commit()


@pytest.mark.asyncio
async def test_session_state_isolation():
    """
    Verifies that CallSessionState maintains strictly isolated per-call runtime state
    without cross-call contamination or global state leakage.
    """
    call1_id = uuid.uuid4()
    call2_id = uuid.uuid4()

    config1 = AgentConfig(
        id=uuid.uuid4(),
        name="Agent 1",
        system_prompt="Prompt 1",
        voice="alloy",
        model="gpt-4o-mini",
    )
    config2 = AgentConfig(
        id=uuid.uuid4(),
        name="Agent 2",
        system_prompt="Prompt 2",
        voice="shimmer",
        model="gpt-4o",
    )

    state1 = CallSessionState(call1_id, "room-1", config1)
    state2 = CallSessionState(call2_id, "room-2", config2)

    # Mutate state 1
    state1.record_barge_in()
    state1.record_barge_in()

    assert state1.interruption_count == 2
    assert state2.interruption_count == 0  # Completely isolated

    assert state1.call_id == call1_id
    assert state2.call_id == call2_id
    assert state1.agent_config.voice == "alloy"
    assert state2.agent_config.voice == "shimmer"


@pytest.mark.asyncio
async def test_interruption_turn_handling_options():
    """
    Verifies that turn handling options configure immediate VAD barge-in interruption.
    """
    options = build_turn_handling_options()
    interruption = options.get("interruption")
    assert interruption is not None
    assert interruption["enabled"] is True
    assert interruption["mode"] == "vad"
    assert interruption["min_duration"] == 0.2
    assert interruption["discard_audio_if_uninterruptible"] is False

    endpointing = options.get("endpointing")
    assert endpointing is not None
    assert endpointing["min_endpointing_delay"] == 0.5
    assert endpointing["max_endpointing_delay"] == 3.0


@pytest.mark.asyncio
async def test_transcript_persistence():
    """
    Verifies that customer and agent dialogue turns are persisted to PostgreSQL
    with relative_time_ms and correct speaker tags.
    """
    test_agent_id = uuid.uuid4()
    test_call_id = uuid.uuid4()
    test_room = f"test-transcript-{uuid.uuid4().hex[:8]}"

    async with db_client.session() as session:
        agent = DBAgent(
            id=test_agent_id,
            name="Transcript Test Agent",
            system_prompt="Test prompt",
            voice="alloy",
            model="gpt-4o-mini",
        )
        call = DBCall(
            id=test_call_id,
            agent_id=test_agent_id,
            room_name=test_room,
            status="ACTIVE",
        )
        session.add_all([agent, call])
        await session.commit()

    agent_cfg = AgentConfig(
        id=test_agent_id,
        name="Transcript Test Agent",
        system_prompt="Test prompt",
        voice="alloy",
        model="gpt-4o-mini",
    )
    state = CallSessionState(test_call_id, test_room, agent_cfg)

    try:
        # Record agent disclosure turn
        state.record_turn(
            speaker="agent",
            text="Thank you for calling Acme Support. Please note that this call is recorded for quality assurance.",
        )
        await asyncio.sleep(0.02)
        # Record customer turn
        state.record_turn(
            speaker="customer",
            text="Hi, I am calling about my order status.",
        )
        # Flush pending writes
        await state.flush()

        async with db_client.session() as session:
            stmt = (
                select(DBTranscriptEntry)
                .where(DBTranscriptEntry.call_id == test_call_id)
                .order_by(DBTranscriptEntry.relative_time_ms, DBTranscriptEntry.timestamp)
            )
            entries = (await session.execute(stmt)).scalars().all()
            assert len(entries) == 2
            assert entries[0].speaker == "agent"
            assert "call is recorded" in entries[0].text
            assert entries[0].relative_time_ms >= 0

            assert entries[1].speaker == "customer"
            assert entries[1].text == "Hi, I am calling about my order status."
    finally:
        async with db_client.session() as session:
            del_t = (
                select(DBTranscriptEntry)
                .where(DBTranscriptEntry.call_id == test_call_id)
            )
            for t in (await session.execute(del_t)).scalars().all():
                await session.delete(t)
            await session.commit()

            call_obj = (await session.execute(select(DBCall).where(DBCall.id == test_call_id))).scalars().first()
            if call_obj:
                await session.delete(call_obj)
                await session.commit()

            agent_obj = (await session.execute(select(DBAgent).where(DBAgent.id == test_agent_id))).scalars().first()
            if agent_obj:
                await session.delete(agent_obj)
                await session.commit()


@pytest.mark.asyncio
async def test_pipeline_missing_credentials_failure_handling():
    """
    Verifies that create_pipeline handles missing provider credentials cleanly
    by raising ProviderConfigurationError, rather than faking a successful response.
    """
    cfg = AgentConfig(
        id=uuid.uuid4(),
        name="Fail Agent",
        system_prompt="Prompt",
        voice="alloy",
        model="gpt-4o-mini",
    )

    # Temporarily ensure keys are absent and not in mock mode
    orig_mock = settings.USE_MOCK_PROVIDERS
    orig_openai = settings.OPENAI_API_KEY
    orig_dg = settings.DEEPGRAM_API_KEY
    env_openai = os.environ.pop("OPENAI_API_KEY", None)
    env_dg = os.environ.pop("DEEPGRAM_API_KEY", None)

    try:
        settings.USE_MOCK_PROVIDERS = False
        settings.OPENAI_API_KEY = None
        settings.DEEPGRAM_API_KEY = None

        with pytest.raises(ProviderConfigurationError):
            create_pipeline(cfg)
    finally:
        settings.USE_MOCK_PROVIDERS = orig_mock
        settings.OPENAI_API_KEY = orig_openai
        settings.DEEPGRAM_API_KEY = orig_dg
        if env_openai is not None:
            os.environ["OPENAI_API_KEY"] = env_openai
        if env_dg is not None:
            os.environ["DEEPGRAM_API_KEY"] = env_dg


@pytest.mark.asyncio
async def test_mock_pipeline_creation_and_components():
    """
    Verifies that when USE_MOCK_PROVIDERS is True, create_pipeline instantiates
    valid VAD, STT, LLM, and TTS components suitable for offline verification.
    """
    cfg = AgentConfig(
        id=uuid.uuid4(),
        name="Mock Agent",
        system_prompt="Prompt",
        voice="alloy",
        model="gpt-4o-mini",
    )

    orig_mock = settings.USE_MOCK_PROVIDERS
    try:
        settings.USE_MOCK_PROVIDERS = True
        pipe = create_pipeline(cfg)
        assert pipe.vad is not None
        assert pipe.stt is not None
        assert pipe.llm is not None
        assert pipe.tts is not None
        assert pipe.provider_name == "mock"
    finally:
        settings.USE_MOCK_PROVIDERS = orig_mock


@pytest.mark.asyncio
async def test_supervisor_whisper_recording_and_privacy():
    """
    Verifies that supervisor whispers:
    1. Are saved with speaker='supervisor' and is_private=True.
    2. Are excluded from customer-facing queries (include_private=False).
    3. Are included when include_private=True.
    """
    test_agent_id = uuid.uuid4()
    test_call_id = uuid.uuid4()
    test_room = f"test-whisper-{uuid.uuid4().hex[:8]}"

    async with db_client.session() as session:
        agent = DBAgent(
            id=test_agent_id,
            name="Whisper Test Agent",
            system_prompt="Base Prompt",
            voice="alloy",
            model="gpt-4o-mini",
        )
        call = DBCall(
            id=test_call_id,
            agent_id=test_agent_id,
            room_name=test_room,
            status="ACTIVE",
        )
        session.add_all([agent, call])
        await session.commit()

    agent_cfg = AgentConfig(
        id=test_agent_id,
        name="Whisper Test Agent",
        system_prompt="Base Prompt",
        voice="alloy",
        model="gpt-4o-mini",
    )

    state = CallSessionState(
        call_id=test_call_id,
        room_name=test_room,
        agent_config=agent_cfg,
    )

    try:
        # Add normal customer and agent turns
        state.record_turn("agent", "Welcome to support", is_private=False)
        state.record_turn("customer", "Can you give a discount?", is_private=False)

        # Add private supervisor whisper
        effective_prompt = state.add_supervisor_whisper("Offer a 10% discount.")
        assert "Offer a 10% discount." in effective_prompt
        assert "Do NOT say 'My supervisor told me...'" in effective_prompt

        await state.flush()

        # Query entries from DB
        async with db_client.session() as session:
            stmt = select(DBTranscriptEntry).where(DBTranscriptEntry.call_id == test_call_id)
            entries = (await session.execute(stmt)).scalars().all()
            assert len(entries) == 3

            # Check privacy flags
            supervisor_entries = [e for e in entries if e.speaker == "supervisor"]
            assert len(supervisor_entries) == 1
            assert supervisor_entries[0].text == "Offer a 10% discount."
            assert supervisor_entries[0].is_private is True

            # Verify customer filter (is_private == False) excludes whisper
            customer_visible = [e for e in entries if not e.is_private]
            assert len(customer_visible) == 2
            assert all(e.speaker in ("customer", "agent") for e in customer_visible)
    finally:
        async with db_client.session() as session:
            stmt_t = select(DBTranscriptEntry).where(DBTranscriptEntry.call_id == test_call_id)
            for t in (await session.execute(stmt_t)).scalars().all():
                await session.delete(t)
            await session.commit()

        async with db_client.session() as session:
            stmt = select(DBCall).where(DBCall.id == test_call_id)
            call_obj = (await session.execute(stmt)).scalars().first()
            if call_obj:
                await session.delete(call_obj)
            await session.commit()

        async with db_client.session() as session:
            stmt_agent = select(DBAgent).where(DBAgent.id == test_agent_id)
            agent_obj = (await session.execute(stmt_agent)).scalars().first()
            if agent_obj:
                await session.delete(agent_obj)
            await session.commit()


@pytest.mark.asyncio
async def test_supervisor_whisper_listener_integration():
    """
    Verifies that attach_supervisor_whisper_listener:
    1. Handles data_received events from LiveKit room.
    2. Updates agent instructions without throwing.
    3. Injects confidential coaching instructions into session chat history.
    """
    from unittest.mock import AsyncMock, MagicMock
    from agent.src.session_manager import attach_supervisor_whisper_listener

    test_agent_id = uuid.uuid4()
    test_call_id = uuid.uuid4()
    test_room = "test-whisper-listener"

    agent_cfg = AgentConfig(
        id=test_agent_id,
        name="Listener Test Agent",
        system_prompt="Base Acme Prompt",
        voice="alloy",
        model="gpt-4o-mini",
    )

    state = CallSessionState(
        call_id=test_call_id,
        room_name=test_room,
        agent_config=agent_cfg,
    )

    # Mock Room and Event registration
    callbacks = {}
    mock_room = MagicMock()
    def mock_on(event):
        def decorator(fn):
            callbacks[event] = fn
            return fn
        return decorator
    mock_room.on = mock_on

    # Mock Agent and Session
    mock_agent = MagicMock()
    mock_agent.update_instructions = AsyncMock()

    mock_chat_ctx = MagicMock()
    mock_chat_ctx.add_message = MagicMock()

    mock_session = MagicMock()
    mock_session.history = mock_chat_ctx

    attach_supervisor_whisper_listener(mock_room, mock_session, mock_agent, state)
    assert "data_received" in callbacks

    # Simulate supervisor sending whisper via data packet
    mock_packet = MagicMock()
    mock_packet.data = json.dumps({"type": "whisper", "text": "Offer free shipping."}).encode("utf-8")
    mock_packet.topic = "whisper"

    callbacks["data_received"](mock_packet)

    # Verify whisper recorded
    assert len(state.supervisor_whispers) == 1
    assert state.supervisor_whispers[0] == "Offer free shipping."

    # Verify session chat history received system instruction
    assert mock_chat_ctx.add_message.called
    call_args = mock_chat_ctx.add_message.call_args
    assert call_args.kwargs["role"] == "system"
    assert "Offer free shipping." in call_args.kwargs["content"]
    assert "NEVER disclose" in call_args.kwargs["content"]

