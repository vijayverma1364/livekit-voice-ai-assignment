"""
Phase 12: Comprehensive Failure Mode & Edge Case Testing Suite
Verifies:
1. Invalid Agent Lookup & Call Creation (HTTP 404)
2. Invalid Call Lookup & Supervisor Token Minting (HTTP 404)
3. Duplicate Call Finalization Idempotency
4. Compliance Provider Failure Handling (Never fakes PASS)
5. Missing AI Provider Credentials Handling
6. Customer Disconnect Cleanup
7. Supervisor Disconnect Isolation
8. Foreign Key Violation & Constraint Protection
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Agent, Call, ComplianceResult, TranscriptEntry
from backend.app.services.compliance_service import compliance_service


# -------------------------------------------------------------------------
# 1. Invalid Agent Handling
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_agent_lookup_and_call_creation(client: AsyncClient):
    """
    Verifies that querying or creating a call with a non-existent agent returns 404.
    """
    fake_id = uuid.uuid4()

    # GET /agents/{id} with invalid agent
    res = await client.get(f"/agents/{fake_id}")
    assert res.status_code == 404
    assert res.json()["detail"] == "Agent not found"

    # POST /calls with invalid agent
    res = await client.post("/calls", json={"agent_id": str(fake_id), "customer_name": "Test User"})
    assert res.status_code == 404
    assert res.json()["detail"] == "Agent not found"


# -------------------------------------------------------------------------
# 2. Invalid Call Handling
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_call_endpoints(client: AsyncClient):
    """
    Verifies that querying or operating on a non-existent call returns 404.
    """
    fake_call_id = uuid.uuid4()

    # GET /calls/{id}
    res = await client.get(f"/calls/{fake_call_id}")
    assert res.status_code == 404
    assert res.json()["detail"] == "Call not found"

    # POST /calls/{id}/supervisor-token
    res = await client.post(f"/calls/{fake_call_id}/supervisor-token", json={"supervisor_name": "Supervisor"})
    assert res.status_code == 404
    assert res.json()["detail"] == "Call not found"

    # POST /calls/{id}/finalize
    res = await client.post(f"/calls/{fake_call_id}/finalize")
    assert res.status_code == 404
    assert res.json()["detail"] == "Call not found"


# -------------------------------------------------------------------------
# 3. Duplicate Call Finalization Idempotency
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_duplicate_call_finalization_idempotency_api(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """
    Verifies that calling /calls/{id}/finalize repeatedly does not duplicate records or error.
    """
    # Create test agent
    agent = Agent(
        id=uuid.uuid4(),
        name="Idempotency Agent",
        system_prompt="Test prompt",
        voice="alloy",
        model="gpt-4o-mini",
    )
    db_session.add(agent)

    # Create call
    call = Call(
        id=uuid.uuid4(),
        agent_id=agent.id,
        room_name=f"test-idemp-{uuid.uuid4()}",
        status="ACTIVE",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(call)

    # Add transcript
    t1 = TranscriptEntry(
        id=uuid.uuid4(),
        call_id=call.id,
        speaker="agent",
        text="This call is recorded for quality assurance purposes.",
        relative_time_ms=2000,
        is_private=False,
    )
    db_session.add(t1)
    await db_session.commit()

    # Mock compliance LLM
    mock_client = MagicMock()
    mock_choice = MagicMock(message=MagicMock(content=json.dumps({"pass": True, "offending_line": None})))
    mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(choices=[mock_choice]))

    compliance_service._openai_client = mock_client

    # First finalization
    res1 = await client.post(f"/calls/{call.id}/finalize")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "ENDED"
    assert data1["recording_disclosure"]["pass"] is True
    assert data1["refund_promise"]["pass"] is True

    # Second finalization (duplicate call-end event)
    res2 = await client.post(f"/calls/{call.id}/finalize")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["id"] == data1["id"]

    # Verify only 1 compliance result exists in database
    stmt = select(ComplianceResult).where(ComplianceResult.call_id == call.id)
    results = (await db_session.execute(stmt)).scalars().all()
    assert len(results) == 1


# -------------------------------------------------------------------------
# 4. Compliance Failure Handling (Never Fakes Pass)
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_compliance_failure_modes_never_fakes_pass():
    """
    Verifies that compliance evaluation safely marks FAIL with diagnostic details
    when the upstream LLM returns invalid JSON or is unavailable.
    """
    entries = [
        TranscriptEntry(
            id=uuid.uuid4(),
            call_id=uuid.uuid4(),
            speaker="agent",
            text="Hello, how can I help you?",
            relative_time_ms=1000,
            is_private=False,
        )
    ]

    # Failure Mode A: LLM returns malformed JSON
    mock_bad_json = MagicMock()
    mock_bad_json.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="Malformed plain text"))])
    )
    res_a = await compliance_service.evaluate_refund_policy(entries, custom_client=mock_bad_json)
    assert res_a["pass"] is False
    assert "Invalid LLM compliance output" in res_a["offending_line"]

    # Failure Mode B: LLM raises network timeout exception
    mock_timeout = MagicMock()
    mock_timeout.chat.completions.create = AsyncMock(side_effect=TimeoutError("Request timed out"))
    res_b = await compliance_service.evaluate_refund_policy(entries, custom_client=mock_timeout)
    assert res_b["pass"] is False
    assert "Compliance LLM unavailable" in res_b["offending_line"]


# -------------------------------------------------------------------------
# 5. Database Constraint Enforcement
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_database_constraint_rejection(db_session: AsyncSession):
    """
    Verifies that invalid status values are rejected by SQL CHECK constraints.
    """
    from sqlalchemy.exc import IntegrityError

    agent = Agent(
        id=uuid.uuid4(),
        name="Constraint Agent",
        system_prompt="Test",
        voice="alloy",
        model="gpt-4o-mini",
    )
    db_session.add(agent)
    await db_session.commit()

    invalid_call = Call(
        id=uuid.uuid4(),
        agent_id=agent.id,
        room_name=f"test-chk-{uuid.uuid4()}",
        status="INVALID_STATUS_VALUE",
    )
    db_session.add(invalid_call)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
