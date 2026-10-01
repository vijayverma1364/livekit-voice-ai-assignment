import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from backend.app.db.models import (
    Agent,
    Call,
    ComplianceResult,
    LatencyMeasurement,
    TranscriptEntry,
)
from backend.app.db.seed import ACME_SUPPORT_PROMPT, seed_agent


@pytest.mark.asyncio
async def test_database_connection(db_session):
    """
    Test basic PostgreSQL connection.
    """
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_agent_insert_and_fetch(db_session):
    """
    Test inserting an Agent and retrieving its attributes.
    """
    agent = Agent(
        name=f"Test Agent {uuid.uuid4().hex[:6]}",
        system_prompt="Test system prompt.",
        voice="alloy",
        model="gpt-4o-mini",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    assert agent.id is not None
    assert agent.created_at is not None
    assert agent.updated_at is not None
    assert agent.voice == "alloy"
    assert agent.model == "gpt-4o-mini"

    # Fetch by ID
    stmt = select(Agent).where(Agent.id == agent.id)
    fetched = (await db_session.execute(stmt)).scalars().first()
    assert fetched is not None
    assert fetched.name == agent.name


@pytest.mark.asyncio
async def test_seed_agent_fetch(db_session):
    """
    Test that the seeded Acme Support Agent exists and adheres to required prompt criteria.
    """
    # Ensure seed function runs
    seeded = await seed_agent()
    assert seeded is not None
    assert seeded.name == "Acme Support Agent"
    assert "discloses recording early" in seeded.system_prompt.lower() or "recorded for quality" in seeded.system_prompt.lower()
    assert "refund" in seeded.system_prompt.lower()
    assert "supervisor" in seeded.system_prompt.lower()


@pytest.mark.asyncio
async def test_call_insert_and_status_transitions(db_session):
    """
    Test creating a Call with foreign key to Agent, and transitions through explicit statuses:
    CREATED -> CONNECTING -> ACTIVE -> ENDED.
    """
    agent = Agent(
        name="Agent for Call Test",
        system_prompt="Prompt",
        voice="echo",
        model="gpt-4o",
    )
    db_session.add(agent)
    await db_session.commit()

    room = f"test-room-{uuid.uuid4().hex[:8]}"
    call = Call(
        agent_id=agent.id,
        room_name=room,
        status="CREATED",
    )
    db_session.add(call)
    await db_session.commit()
    await db_session.refresh(call)

    assert call.id is not None
    assert call.status == "CREATED"
    assert call.created_at is not None

    # Status transition: CONNECTING -> ACTIVE -> ENDED
    call.status = "CONNECTING"
    await db_session.commit()
    assert call.status == "CONNECTING"

    call.status = "ACTIVE"
    call.started_at = datetime.now(timezone.utc)
    await db_session.commit()
    assert call.status == "ACTIVE"

    call.status = "ENDED"
    call.ended_at = datetime.now(timezone.utc)
    await db_session.commit()
    assert call.status == "ENDED"


@pytest.mark.asyncio
async def test_call_invalid_status_constraint(db_session):
    """
    Test that an invalid call status violates the CheckConstraint.
    """
    agent = Agent(name="Status Test Agent", system_prompt="P", voice="alloy", model="m")
    db_session.add(agent)
    await db_session.commit()

    invalid_call = Call(
        agent_id=agent.id,
        room_name=f"room-invalid-{uuid.uuid4().hex[:8]}",
        status="INVALID_STATUS_VALUE",
    )
    db_session.add(invalid_call)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_call_foreign_key_violation(db_session):
    """
    Test that inserting a Call with a non-existent agent_id raises IntegrityError.
    """
    non_existent_id = uuid.uuid4()
    bad_call = Call(
        agent_id=non_existent_id,
        room_name=f"room-fk-{uuid.uuid4().hex[:8]}",
        status="CREATED",
    )
    db_session.add(bad_call)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_transcript_insert_and_privacy(db_session):
    """
    Test inserting transcript entries and verifying supervisor privacy isolation.
    """
    agent = Agent(name="Transcript Agent", system_prompt="P", voice="alloy", model="m")
    db_session.add(agent)
    await db_session.commit()

    call = Call(agent_id=agent.id, room_name=f"room-{uuid.uuid4().hex[:8]}", status="ACTIVE")
    db_session.add(call)
    await db_session.commit()

    # Insert turns: agent greeting, customer question, supervisor whisper
    t1 = TranscriptEntry(
        call_id=call.id,
        speaker="agent",
        text="Thank you for calling. This call is recorded.",
        relative_time_ms=500,
        is_private=False,
    )
    t2 = TranscriptEntry(
        call_id=call.id,
        speaker="customer",
        text="I have a question about my invoice.",
        relative_time_ms=2500,
        is_private=False,
    )
    t3 = TranscriptEntry(
        call_id=call.id,
        speaker="supervisor",
        text="Offer a 10% loyalty credit.",
        relative_time_ms=3100,
        is_private=True,
    )
    db_session.add_all([t1, t2, t3])
    await db_session.commit()

    # Query customer-facing transcripts (is_private == False)
    stmt_customer = (
        select(TranscriptEntry)
        .where(TranscriptEntry.call_id == call.id, TranscriptEntry.is_private == False)
        .order_by(TranscriptEntry.relative_time_ms.asc())
    )
    public_entries = (await db_session.execute(stmt_customer)).scalars().all()
    assert len(public_entries) == 2
    assert all(not e.is_private for e in public_entries)
    assert all(e.speaker != "supervisor" for e in public_entries)

    # Query all transcripts for supervisor (including is_private == True)
    stmt_all = (
        select(TranscriptEntry)
        .where(TranscriptEntry.call_id == call.id)
        .order_by(TranscriptEntry.relative_time_ms.asc())
    )
    all_entries = (await db_session.execute(stmt_all)).scalars().all()
    assert len(all_entries) == 3


@pytest.mark.asyncio
async def test_latency_measurement_insert_and_idempotency(db_session):
    """
    Test inserting latency measurements per turn and verifying turn uniqueness.
    """
    agent = Agent(name="Latency Agent", system_prompt="P", voice="alloy", model="m")
    db_session.add(agent)
    await db_session.commit()

    call = Call(agent_id=agent.id, room_name=f"room-{uuid.uuid4().hex[:8]}", status="ACTIVE")
    db_session.add(call)
    await db_session.commit()

    latency_turn1 = LatencyMeasurement(
        call_id=call.id,
        turn_number=1,
        user_stop_ms=1000,
        stt_final_ms=1200,
        llm_first_token_ms=1450,
        tts_first_audio_ms=1600,
        audio_published_ms=1650,
    )
    db_session.add(latency_turn1)
    await db_session.commit()
    assert latency_turn1.id is not None

    # Attempt duplicate turn insertion -> IntegrityError
    duplicate_turn = LatencyMeasurement(
        call_id=call.id,
        turn_number=1,
        user_stop_ms=1000,
    )
    db_session.add(duplicate_turn)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_compliance_result_insert_and_idempotency(db_session):
    """
    Test compliance results insertion and verify uniqueness per call (idempotency).
    """
    agent = Agent(name="Compliance Agent", system_prompt="P", voice="alloy", model="m")
    db_session.add(agent)
    await db_session.commit()

    call = Call(agent_id=agent.id, room_name=f"room-{uuid.uuid4().hex[:8]}", status="ENDED")
    db_session.add(call)
    await db_session.commit()

    compliance = ComplianceResult(
        call_id=call.id,
        recording_rule_pass=True,
        recording_rule_details={"disclosure_offset_ms": 500, "threshold_ms": 30000},
        refund_rule_pass=True,
        refund_offending_line=None,
    )
    db_session.add(compliance)
    await db_session.commit()
    assert compliance.id is not None

    # Attempting to add a second compliance result for the same call must fail
    duplicate_compliance = ComplianceResult(
        call_id=call.id,
        recording_rule_pass=False,
        refund_rule_pass=False,
    )
    db_session.add(duplicate_compliance)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_relationships_and_cascades(db_session):
    """
    Test eager relationship loading and cascade deletion of related child records.
    """
    agent = Agent(name="Rel Agent", system_prompt="P", voice="alloy", model="m")
    db_session.add(agent)
    await db_session.commit()

    call = Call(agent_id=agent.id, room_name=f"room-{uuid.uuid4().hex[:8]}", status="ENDED")
    db_session.add(call)
    await db_session.commit()

    # Add child items
    t = TranscriptEntry(call_id=call.id, speaker="agent", text="Hi", relative_time_ms=100)
    l = LatencyMeasurement(call_id=call.id, turn_number=1, user_stop_ms=50)
    c = ComplianceResult(call_id=call.id, recording_rule_pass=True, refund_rule_pass=True)
    db_session.add_all([t, l, c])
    await db_session.commit()

    # Query with relationships loaded
    stmt = (
        select(Call)
        .where(Call.id == call.id)
        .options(
            selectinload(Call.agent),
            selectinload(Call.transcript_entries),
            selectinload(Call.latency_measurements),
            selectinload(Call.compliance_result),
        )
    )
    loaded_call = (await db_session.execute(stmt)).scalars().first()
    assert loaded_call.agent.id == agent.id
    assert len(loaded_call.transcript_entries) == 1
    assert len(loaded_call.latency_measurements) == 1
    assert loaded_call.compliance_result is not None

    # Delete call -> cascade deletes transcripts, latency, and compliance
    await db_session.delete(loaded_call)
    await db_session.commit()

    t_check = (await db_session.execute(select(TranscriptEntry).where(TranscriptEntry.call_id == call.id))).scalars().all()
    l_check = (await db_session.execute(select(LatencyMeasurement).where(LatencyMeasurement.call_id == call.id))).scalars().all()
    c_check = (await db_session.execute(select(ComplianceResult).where(ComplianceResult.call_id == call.id))).scalars().first()
    agent_check = (await db_session.execute(select(Agent).where(Agent.id == agent.id))).scalars().first()

    assert len(t_check) == 0
    assert len(l_check) == 0
    assert c_check is None
    # Agent remains intact
    assert agent_check is not None
