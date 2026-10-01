import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.db.models import Agent, Call, ComplianceResult, TranscriptEntry
from backend.app.db.session import async_session_factory
from backend.app.main import app
from backend.app.services.compliance_service import (
    ComplianceService,
    RefundComplianceOutput,
    compliance_service,
)


@pytest_asyncio.fixture
async def test_agent(db_session: AsyncSession):
    agent_id = uuid.uuid4()
    agent = Agent(
        id=agent_id,
        name="Compliance Test Agent",
        system_prompt="You are Acme Support Agent. Do not promise refunds.",
        voice="alloy",
        model="gpt-4o-mini",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


# =========================================================================
# TEST 1: Disclosure at 10 seconds -> PASS
# =========================================================================
@pytest.mark.asyncio
async def test_rule1_disclosure_at_10_seconds_pass():
    """
    Test 1: Agent states call is recorded at 10.0 seconds (< 30s threshold).
    Must deterministically return pass=True with structured details.
    """
    call_start = datetime.now(timezone.utc)
    entry = TranscriptEntry(
        id=uuid.uuid4(),
        call_id=uuid.uuid4(),
        speaker="agent",
        text="Thank you for calling Acme. Please note that this call is recorded for quality assurance.",
        relative_time_ms=10000,  # 10.0 seconds
        timestamp=call_start + timedelta(seconds=10.0),
        is_private=False,
    )

    result = compliance_service.evaluate_recording_disclosure(
        call_started_at=call_start,
        transcripts=[entry],
    )

    assert result["pass"] is True
    assert "Recording disclosure detected at 10.0 seconds" in result["details"]


# =========================================================================
# TEST 2: Disclosure at exactly/within 30 seconds -> PASS
# =========================================================================
@pytest.mark.asyncio
async def test_rule1_disclosure_at_exactly_30_seconds_pass():
    """
    Test 2: Agent states call is recorded at exactly 30.0 seconds.
    Boundary condition: <= 30.0s must pass.
    """
    call_start = datetime.now(timezone.utc)
    entry = TranscriptEntry(
        id=uuid.uuid4(),
        call_id=uuid.uuid4(),
        speaker="agent",
        text="This call is being recorded for training purposes.",
        relative_time_ms=30000,  # 30.0 seconds
        timestamp=call_start + timedelta(seconds=30.0),
        is_private=False,
    )

    result = compliance_service.evaluate_recording_disclosure(
        call_started_at=call_start,
        transcripts=[entry],
    )

    assert result["pass"] is True
    assert "Recording disclosure detected at 30.0 seconds" in result["details"]


# =========================================================================
# TEST 3: Disclosure after 30 seconds -> FAIL
# =========================================================================
@pytest.mark.asyncio
async def test_rule1_disclosure_after_30_seconds_fail():
    """
    Test 3: Agent states call is recorded at 31.0 seconds (> 30s threshold).
    Must deterministically return pass=False.
    """
    call_start = datetime.now(timezone.utc)
    entry = TranscriptEntry(
        id=uuid.uuid4(),
        call_id=uuid.uuid4(),
        speaker="agent",
        text="By the way, this call is recorded for quality assurance.",
        relative_time_ms=31000,  # 31.0 seconds
        timestamp=call_start + timedelta(seconds=31.0),
        is_private=False,
    )

    result = compliance_service.evaluate_recording_disclosure(
        call_started_at=call_start,
        transcripts=[entry],
    )

    assert result["pass"] is False
    assert result["details"] == "No valid recording disclosure within first 30 seconds"


# =========================================================================
# TEST 4: No disclosure -> FAIL
# =========================================================================
@pytest.mark.asyncio
async def test_rule1_no_disclosure_fail():
    """
    Test 4: Agent never discloses that the call is being recorded.
    Must return pass=False with structured failure details.
    """
    call_start = datetime.now(timezone.utc)
    entry = TranscriptEntry(
        id=uuid.uuid4(),
        call_id=uuid.uuid4(),
        speaker="agent",
        text="Hello, thank you for reaching Acme Support! How can I assist you today?",
        relative_time_ms=5000,
        timestamp=call_start + timedelta(seconds=5.0),
        is_private=False,
    )

    result = compliance_service.evaluate_recording_disclosure(
        call_started_at=call_start,
        transcripts=[entry],
    )

    assert result["pass"] is False
    assert result["details"] == "No valid recording disclosure within first 30 seconds"


# =========================================================================
# TEST 5: Refund promise -> FAIL + offending line
# =========================================================================
@pytest.mark.asyncio
async def test_rule2_refund_promise_fail_with_offending_line():
    """
    Test 5: Agent promised a refund.
    LLM detects violation and returns pass=False with offending line.
    """
    offending_text = "I apologize for the trouble, I can process a full refund to your card right now."
    entries = [
        TranscriptEntry(
            id=uuid.uuid4(),
            call_id=uuid.uuid4(),
            speaker="agent",
            text="Hello, how can I help you?",
            relative_time_ms=2000,
            is_private=False,
        ),
        TranscriptEntry(
            id=uuid.uuid4(),
            call_id=uuid.uuid4(),
            speaker="agent",
            text=offending_text,
            relative_time_ms=12000,
            is_private=False,
        ),
    ]

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "pass": False,
        "offending_line": offending_text,
    })
    mock_response = MagicMock(choices=[mock_choice])
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await compliance_service.evaluate_refund_policy(
        agent_transcripts=entries,
        custom_client=mock_client,
    )

    assert result["pass"] is False
    assert result["offending_line"] == offending_text


# =========================================================================
# TEST 6: No refund promise -> PASS
# =========================================================================
@pytest.mark.asyncio
async def test_rule2_no_refund_promise_pass():
    """
    Test 6: Agent adhered to policy and did not promise a refund.
    LLM returns pass=True with offending_line=None.
    """
    entries = [
        TranscriptEntry(
            id=uuid.uuid4(),
            call_id=uuid.uuid4(),
            speaker="agent",
            text="Thank you for calling. I can help you troubleshoot your router.",
            relative_time_ms=2000,
            is_private=False,
        ),
        TranscriptEntry(
            id=uuid.uuid4(),
            call_id=uuid.uuid4(),
            speaker="agent",
            text="Please restart your device by holding down the power button for 10 seconds.",
            relative_time_ms=15000,
            is_private=False,
        ),
    ]

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "pass": True,
        "offending_line": None,
    })
    mock_response = MagicMock(choices=[mock_choice])
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await compliance_service.evaluate_refund_policy(
        agent_transcripts=entries,
        custom_client=mock_client,
    )

    assert result["pass"] is True
    assert result["offending_line"] is None


# =========================================================================
# TEST 7: Invalid LLM compliance output -> FAIL (never fakes PASS)
# =========================================================================
@pytest.mark.asyncio
async def test_rule2_invalid_llm_compliance_output():
    """
    Test 7: LLM returns malformed or non-schema JSON output.
    Schema validation fails and must explicitly return pass=False.
    """
    entries = [
        TranscriptEntry(
            id=uuid.uuid4(),
            call_id=uuid.uuid4(),
            speaker="agent",
            text="I can check your balance.",
            relative_time_ms=2000,
            is_private=False,
        )
    ]

    # Sub-case A: Not valid JSON
    mock_client_a = MagicMock()
    mock_choice_a = MagicMock(message=MagicMock(content="Freeform text without JSON"))
    mock_client_a.chat.completions.create = AsyncMock(return_value=MagicMock(choices=[mock_choice_a]))

    result_a = await compliance_service.evaluate_refund_policy(
        agent_transcripts=entries,
        custom_client=mock_client_a,
    )
    assert result_a["pass"] is False
    assert "Invalid LLM compliance output" in result_a["offending_line"]

    # Sub-case B: Valid JSON but missing required fields / schema mismatch
    mock_client_b = MagicMock()
    mock_choice_b = MagicMock(message=MagicMock(content=json.dumps({"status": "unknown"})))
    mock_client_b.chat.completions.create = AsyncMock(return_value=MagicMock(choices=[mock_choice_b]))

    result_b = await compliance_service.evaluate_refund_policy(
        agent_transcripts=entries,
        custom_client=mock_client_b,
    )
    assert result_b["pass"] is False
    assert "Invalid LLM compliance output" in result_b["offending_line"]


# =========================================================================
# TEST 8: Compliance LLM unavailable -> FAIL (never fakes PASS)
# =========================================================================
@pytest.mark.asyncio
async def test_rule2_compliance_llm_unavailable():
    """
    Test 8: LLM provider throws connection timeout or API credentials error.
    Must expose explicit failure/unavailable state and NOT fake PASS.
    """
    entries = [
        TranscriptEntry(
            id=uuid.uuid4(),
            call_id=uuid.uuid4(),
            speaker="agent",
            text="I will look into your request.",
            relative_time_ms=2000,
            is_private=False,
        )
    ]

    # Sub-case A: Network error or exception raised during API call
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("OpenAI API Connection Timeout (504)"))

    result_a = await compliance_service.evaluate_refund_policy(
        agent_transcripts=entries,
        custom_client=mock_client,
    )
    assert result_a["pass"] is False
    assert "Compliance LLM unavailable" in result_a["offending_line"]

    # Sub-case B: No OpenAI client configured / missing API key
    orig_key = settings.OPENAI_API_KEY
    orig_env = os.environ.get("OPENAI_API_KEY")
    try:
        settings.OPENAI_API_KEY = None
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]
        service_no_key = ComplianceService(openai_client=None)
        service_no_key._openai_client = None
        # Ensure it returns unavailable
        result_b = await service_no_key.evaluate_refund_policy(
            agent_transcripts=entries,
            custom_client=None,
        )
        assert result_b["pass"] is False
        assert "Compliance LLM unavailable" in result_b["offending_line"]
    finally:
        settings.OPENAI_API_KEY = orig_key
        if orig_env is not None:
            os.environ["OPENAI_API_KEY"] = orig_env


# =========================================================================
# TEST 9: Duplicate call finalization (Idempotency)
# =========================================================================
@pytest.mark.asyncio
async def test_duplicate_call_finalization_idempotency(db_session: AsyncSession, test_agent: Agent):
    """
    Test 9: Duplicate call finalization.
    Must not:
    - duplicate compliance records
    - corrupt call status
    - repeat expensive compliance unnecessarily
    - duplicate transcript entries
    """
    call_id = uuid.uuid4()
    call = Call(
        id=call_id,
        agent_id=test_agent.id,
        room_name=f"test-idempotency-{call_id}",
        status="ACTIVE",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(call)

    # Add transcript entries
    t1 = TranscriptEntry(
        id=uuid.uuid4(),
        call_id=call_id,
        speaker="agent",
        text="Thank you for calling Acme. This call is being recorded for quality assurance.",
        relative_time_ms=5000,
        is_private=False,
    )
    t2 = TranscriptEntry(
        id=uuid.uuid4(),
        call_id=call_id,
        speaker="customer",
        text="I want my money back for my broken order.",
        relative_time_ms=10000,
        is_private=False,
    )
    t3 = TranscriptEntry(
        id=uuid.uuid4(),
        call_id=call_id,
        speaker="agent",
        text="I understand your frustration, but per company policy I cannot issue a refund. I can offer a replacement.",
        relative_time_ms=16000,
        is_private=False,
    )
    db_session.add_all([t1, t2, t3])
    await db_session.commit()

    # Mock LLM for the initial run
    mock_client = MagicMock()
    mock_choice = MagicMock(message=MagicMock(content=json.dumps({"pass": True, "offending_line": None})))
    mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(choices=[mock_choice]))

    # --- 1st Finalization ---
    result_1 = await compliance_service.run_and_persist_compliance(
        call_id=call_id,
        db=db_session,
        custom_openai_client=mock_client,
    )
    assert result_1 is not None
    assert result_1.recording_rule_pass is True
    assert result_1.refund_rule_pass is True
    assert mock_client.chat.completions.create.call_count == 1

    # Verify Call is ENDED
    stmt_call = select(Call).where(Call.id == call_id)
    refreshed_call = (await db_session.execute(stmt_call)).scalars().first()
    assert refreshed_call.status == "ENDED"
    assert refreshed_call.ended_at is not None

    # Count compliance records
    stmt_comp = select(ComplianceResult).where(ComplianceResult.call_id == call_id)
    comp_records = (await db_session.execute(stmt_comp)).scalars().all()
    assert len(comp_records) == 1
    first_record_id = comp_records[0].id

    # --- 2nd Finalization (Duplicate Call-End) ---
    result_2 = await compliance_service.run_and_persist_compliance(
        call_id=call_id,
        db=db_session,
        custom_openai_client=mock_client,
    )
    assert result_2 is not None
    assert result_2.id == first_record_id
    # CRITICAL: LLM was NOT called again! Expensive compliance was not repeated!
    assert mock_client.chat.completions.create.call_count == 1

    # Verify no duplicate compliance records
    comp_records_after = (await db_session.execute(stmt_comp)).scalars().all()
    assert len(comp_records_after) == 1

    # Verify transcript entries count remained exactly 3
    stmt_trans = select(TranscriptEntry).where(TranscriptEntry.call_id == call_id)
    trans_records = (await db_session.execute(stmt_trans)).scalars().all()
    assert len(trans_records) == 3


# =========================================================================
# GET /calls/{id} INTEGRATION TEST
# =========================================================================
@pytest.mark.asyncio
async def test_get_call_endpoint_exposes_compliance_and_transcripts(
    client: AsyncClient,
    db_session: AsyncSession,
    test_agent: Agent,
):
    """
    Verifies GET /calls/{id} exposes:
    - call status
    - transcript entries (with timestamp, speaker, text, relative_time_ms)
    - recording disclosure result
    - refund promise result
    - latency measurements
    """
    call_id = uuid.uuid4()
    call = Call(
        id=call_id,
        agent_id=test_agent.id,
        room_name=f"test-api-get-{call_id}",
        status="ACTIVE",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(call)

    # Add agent disclosure at 12.4s and user utterance
    t1 = TranscriptEntry(
        id=uuid.uuid4(),
        call_id=call_id,
        speaker="agent",
        text="Thank you for calling. This call is recorded for quality assurance.",
        relative_time_ms=12400,
        is_private=False,
    )
    t2 = TranscriptEntry(
        id=uuid.uuid4(),
        call_id=call_id,
        speaker="user",
        text="Hi, I am checking my order status.",
        relative_time_ms=18000,
        is_private=False,
    )
    # Confidential supervisor whisper (must NOT appear to customer)
    t_whisper = TranscriptEntry(
        id=uuid.uuid4(),
        call_id=call_id,
        speaker="supervisor",
        text="Coach the customer on shipping timelines.",
        relative_time_ms=19000,
        is_private=True,
    )
    db_session.add_all([t1, t2, t_whisper])
    await db_session.commit()

    # Finalize the call via compliance service
    mock_client = MagicMock()
    mock_choice = MagicMock(message=MagicMock(content=json.dumps({"pass": True, "offending_line": None})))
    mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(choices=[mock_choice]))

    await compliance_service.run_and_persist_compliance(
        call_id=call_id,
        db=db_session,
        custom_openai_client=mock_client,
    )

    # Call GET /calls/{id}
    response = await client.get(f"/calls/{call_id}")
    assert response.status_code == 200
    data = response.json()

    # 1. Status
    assert data["status"] == "ENDED"

    # 2. Transcript (contains agent and user turns; supervisor whisper is hidden)
    transcript = data["transcript"]
    assert len(transcript) == 2
    speakers = [entry["speaker"] for entry in transcript]
    assert "agent" in speakers
    assert "user" in speakers
    assert "supervisor" not in speakers
    for entry in transcript:
        assert "timestamp" in entry
        assert "speaker" in entry
        assert "text" in entry
        assert "relative_time_ms" in entry
        assert entry["is_private"] is False

    # 3. Recording disclosure result
    assert data["recording_disclosure"] is not None
    assert data["recording_disclosure"]["pass"] is True
    assert "12.4 seconds" in data["recording_disclosure"]["details"]

    # 4. Refund promise result
    assert data["refund_promise"] is not None
    assert data["refund_promise"]["pass"] is True
    assert data["refund_promise"]["offending_line"] is None

    # 5. Latency measurements field is present
    assert "latency_measurements" in data
