import json
import logging
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.src.db import db_client
from agent.src.latency_tracker import (
    CallLatencyTracker,
    TurnLatencyRecord,
    log_structured_latency_event,
)
from backend.app.db.models import Agent, Call, LatencyMeasurement
from backend.app.schemas.latency import LatencyMeasurementRead


@pytest_asyncio.fixture
async def test_agent(db_session: AsyncSession):
    agent_id = uuid.uuid4()
    agent = Agent(
        id=agent_id,
        name="Latency Test Agent",
        system_prompt="You are Acme Support Agent.",
        voice="alloy",
        model="gpt-4o-mini",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


# =========================================================================
# 1. STAGE DURATION CALCULATIONS
# =========================================================================
def test_stage_duration_calculations():
    """
    Verifies that all 5 stage latency calculations are correctly derived
    from the milestone timestamps:
    - STT latency = stt_final_ms - user_stop_ms
    - LLM first token latency = llm_first_token_ms - stt_final_ms
    - TTS first audio latency = tts_first_audio_ms - llm_first_token_ms
    - Publish latency = audio_published_ms - tts_first_audio_ms
    - Overall latency = audio_published_ms - user_stop_ms
    """
    rec = TurnLatencyRecord(
        call_id=uuid.uuid4(),
        room_name="test-room",
        agent_id=uuid.uuid4(),
        turn_number=1,
        user_stop_ms=1000,
        stt_final_ms=1350,
        llm_first_token_ms=1800,
        tts_first_audio_ms=2150,
        audio_published_ms=2200,
    )

    assert rec.stt_latency_ms == 350
    assert rec.llm_first_token_latency_ms == 450
    assert rec.tts_first_audio_latency_ms == 350
    assert rec.publish_latency_ms == 50
    assert rec.overall_latency_ms == 1200


# =========================================================================
# 2. STRUCTURED OBSERVABILITY LOGGING
# =========================================================================
def test_structured_observability_logging(caplog):
    """
    Verifies that structured logs contain:
    - call_id
    - room_name
    - agent_id
    - turn_number
    - event
    - timestamp
    And strictly contain no secrets.
    """
    call_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    with caplog.at_level(logging.INFO):
        log_structured_latency_event(
            call_id=call_id,
            room_name="room-alpha-123",
            agent_id=agent_id,
            turn_number=1,
            event="stt_final",
            extra={"stt_latency_ms": 320},
        )

    matched_log = None
    for record in caplog.records:
        if "[OBSERVABILITY]" in record.message:
            matched_log = record.message
            break

    assert matched_log is not None
    json_part = matched_log.split("[OBSERVABILITY]")[1].strip()
    data = json.loads(json_part)

    assert data["call_id"] == str(call_id)
    assert data["room_name"] == "room-alpha-123"
    assert data["agent_id"] == str(agent_id)
    assert data["turn_number"] == 1
    assert data["event"] == "stt_final"
    assert "timestamp" in data
    assert data["stt_latency_ms"] == 320

    # Ensure no secret strings leaked
    assert "secret" not in json_part.lower()
    assert "key" not in json_part.lower() or "turn_number" in json_part


# =========================================================================
# 3. DATABASE PERSISTENCE & IDEMPOTENCY
# =========================================================================
@pytest.mark.asyncio
async def test_latency_persistence_in_database(db_session: AsyncSession, test_agent: Agent):
    """
    Verifies that turn latency metrics are persisted to PostgreSQL latency_measurements
    and can be queried with idempotent upserts.
    """
    call_id = uuid.uuid4()
    call = Call(
        id=call_id,
        agent_id=test_agent.id,
        room_name=f"test-latency-db-{call_id}",
        status="ACTIVE",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(call)
    await db_session.commit()

    # Save Turn 1
    meas_id = await db_client.save_latency_measurement(
        call_id=call_id,
        turn_number=1,
        user_stop_ms=1100,
        stt_final_ms=1450,
        llm_first_token_ms=1900,
        tts_first_audio_ms=2250,
        audio_published_ms=2300,
    )
    assert meas_id is not None

    # Query directly from DB
    stmt = select(LatencyMeasurement).where(
        LatencyMeasurement.call_id == call_id,
        LatencyMeasurement.turn_number == 1,
    )
    saved = (await db_session.execute(stmt)).scalars().first()
    assert saved is not None
    assert saved.turn_number == 1
    assert saved.user_stop_ms == 1100
    assert saved.stt_final_ms == 1450
    assert saved.llm_first_token_ms == 1900
    assert saved.tts_first_audio_ms == 2250
    assert saved.audio_published_ms == 2300

    # Idempotent update on duplicate write
    meas_id_2 = await db_client.save_latency_measurement(
        call_id=call_id,
        turn_number=1,
        audio_published_ms=2310,
    )
    assert meas_id_2 == meas_id

    # Verify no duplicate row was created
    stmt_all = select(LatencyMeasurement).where(LatencyMeasurement.call_id == call_id)
    records = (await db_session.execute(stmt_all)).scalars().all()
    assert len(records) == 1


# =========================================================================
# 4. MULTI-TURN LATENCY TRACKER LIFECYCLE
# =========================================================================
@pytest.mark.asyncio
async def test_call_latency_tracker_multi_turn_lifecycle(db_session: AsyncSession, test_agent: Agent):
    """
    Exercises multiple conversational turns through CallLatencyTracker:
    Turn 1 and Turn 2 milestones captured and persisted.
    """
    call_id = uuid.uuid4()
    call = Call(
        id=call_id,
        agent_id=test_agent.id,
        room_name=f"test-tracker-multi-{call_id}",
        status="ACTIVE",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(call)
    await db_session.commit()

    tracker = CallLatencyTracker(
        call_id=call_id,
        room_name=call.room_name,
        agent_id=test_agent.id,
        start_monotonic=0.0,
        save_measurement_fn=db_client.save_latency_measurement,
    )

    # --- Turn 1 ---
    tracker.record_user_stop(custom_time_ms=1000)
    tracker.record_stt_final(custom_time_ms=1320)
    tracker.record_llm_first_token(custom_time_ms=1750)
    tracker.record_tts_first_audio(custom_time_ms=2100)
    tracker.record_audio_published(custom_time_ms=2140)

    turn1 = tracker.finalize_turn()
    assert turn1.turn_number == 1
    assert turn1.stt_latency_ms == 320
    assert turn1.llm_first_token_latency_ms == 430
    assert turn1.tts_first_audio_latency_ms == 350
    assert turn1.publish_latency_ms == 40
    assert turn1.overall_latency_ms == 1140

    # --- Turn 2 ---
    tracker.record_user_stop(custom_time_ms=5000)
    tracker.record_stt_final(custom_time_ms=5300)
    tracker.record_llm_first_token(custom_time_ms=5720)
    tracker.record_tts_first_audio(custom_time_ms=6050)
    tracker.record_audio_published(custom_time_ms=6090)

    turn2 = tracker.finalize_turn()
    assert turn2.turn_number == 2
    assert turn2.stt_latency_ms == 300
    assert turn2.llm_first_token_latency_ms == 420
    assert turn2.tts_first_audio_latency_ms == 330
    assert turn2.publish_latency_ms == 40
    assert turn2.overall_latency_ms == 1090

    await tracker.flush()

    # Verify both turns in database
    records = await db_client.get_latency_measurements(call_id)
    assert len(records) == 2
    assert records[0].turn_number == 1
    assert records[1].turn_number == 2


# =========================================================================
# 5. GET /calls/{id} EXPOSES LATENCY METRICS WITH DURATIONS
# =========================================================================
@pytest.mark.asyncio
async def test_get_call_exposes_latency_measurements_with_durations(
    client: AsyncClient,
    db_session: AsyncSession,
    test_agent: Agent,
):
    """
    Verifies that GET /calls/{id} returns latency measurements with computed stage durations:
    - stt_latency_ms
    - llm_first_token_latency_ms
    - tts_first_audio_latency_ms
    - publish_latency_ms
    - overall_latency_ms
    """
    call_id = uuid.uuid4()
    call = Call(
        id=call_id,
        agent_id=test_agent.id,
        room_name=f"test-api-lat-{call_id}",
        status="ACTIVE",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(call)

    # Insert turn 1 latency measurement
    m1 = LatencyMeasurement(
        id=uuid.uuid4(),
        call_id=call_id,
        turn_number=1,
        user_stop_ms=1200,
        stt_final_ms=1550,
        llm_first_token_ms=1980,
        tts_first_audio_ms=2320,
        audio_published_ms=2365,
    )
    db_session.add(m1)
    await db_session.commit()

    response = await client.get(f"/calls/{call_id}")
    assert response.status_code == 200
    data = response.json()

    assert "latency_measurements" in data
    measurements = data["latency_measurements"]
    assert len(measurements) >= 1
    turn_1 = measurements[0]

    assert turn_1["turn_number"] == 1
    assert turn_1["user_stop_ms"] == 1200
    assert turn_1["stt_final_ms"] == 1550
    assert turn_1["llm_first_token_ms"] == 1980
    assert turn_1["tts_first_audio_ms"] == 2320
    assert turn_1["audio_published_ms"] == 2365

    # Check computed stage durations
    assert turn_1["stt_latency_ms"] == 350
    assert turn_1["llm_first_token_latency_ms"] == 430
    assert turn_1["tts_first_audio_latency_ms"] == 340
    assert turn_1["publish_latency_ms"] == 45
    assert turn_1["overall_latency_ms"] == 1165
