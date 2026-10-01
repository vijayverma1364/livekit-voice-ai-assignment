import logging
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.db.models import Agent, Call, ComplianceResult, TranscriptEntry
from backend.app.db.session import get_db
from backend.app.schemas.call import (
    CallCreateRequest,
    CallDetailResponse,
    CallInitResponse,
    CallRead,
    CallStatus,
    RecordingDisclosureResult,
    RefundPromiseResult,
    SupervisorTokenRequest,
    SupervisorTokenResponse,
)
from backend.app.schemas.compliance import ComplianceResultRead
from backend.app.schemas.latency import LatencyMeasurementRead
from backend.app.schemas.transcript import TranscriptEntryRead
from backend.app.services.compliance_service import compliance_service
from backend.app.services.livekit_service import livekit_service

logger = logging.getLogger("routes_calls")
router = APIRouter(prefix="/calls", tags=["Calls"])


@router.post(
    "",
    response_model=CallInitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initiate Voice Call Session",
)
async def create_call(
    payload: CallCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> CallInitResponse:
    """
    Initializes a new voice call session, creates the LiveKit room,
    and returns connection credentials for the customer.
    """
    # Verify the requested agent exists
    stmt = select(Agent).where(Agent.id == payload.agent_id)
    agent = (await db.execute(stmt)).scalars().first()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    # Generate room identifiers
    call_id = uuid.uuid4()
    room_name = payload.room_name or f"call-{call_id}"
    customer_identity = payload.customer_identity or f"customer-{uuid.uuid4().hex[:8]}"

    # Persist the call record before room join so the worker can look it up immediately
    call = Call(
        id=call_id,
        agent_id=agent.id,
        room_name=room_name,
        status="CREATED",
    )
    db.add(call)
    try:
        await db.commit()
        await db.refresh(call)
    except Exception as e:
        await db.rollback()
        logger.error("Failed to persist call to database: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize call record in database",
        )

    # Pre-create the LiveKit room with agent dispatch metadata
    try:
        await livekit_service.create_room(
            room_name=room_name,
            agent_id=agent.id,
        )
    except Exception as e:
        logger.warning("Could not pre-create room on LiveKit (will rely on auto-create): %s", e)

    # Mint customer access token
    try:
        customer_token = livekit_service.generate_customer_token(
            room_name=room_name,
            identity=customer_identity,
            name=payload.customer_name or customer_identity,
        )
    except Exception as e:
        logger.error("Failed to mint LiveKit access token: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate LiveKit customer access token",
        )

    return CallInitResponse(
        call_id=call.id,
        agent_id=agent.id,
        room_name=room_name,
        status=CallStatus(call.status),
        customer_identity=customer_identity,
        livekit_url=livekit_service.ws_url,
        livekit_token=customer_token,
        created_at=call.created_at,
    )


@router.get(
    "/{call_id}",
    response_model=CallDetailResponse,
    summary="Get Call Session Details, Transcripts & Compliance",
)
async def get_call(
    call_id: uuid.UUID,
    include_private: bool = Query(
        False,
        description="If True, includes supervisor private whispers in transcript. Default False for customer privacy.",
    ),
    db: AsyncSession = Depends(get_db),
) -> CallDetailResponse:
    """
    Retrieves complete call details including lifecycle status, timing, transcripts,
    latency metrics, and compliance audit results.
    """
    stmt = (
        select(Call)
        .where(Call.id == call_id)
        .options(
            selectinload(Call.transcript_entries),
            selectinload(Call.latency_measurements),
            selectinload(Call.compliance_result),
        )
    )
    call = (await db.execute(stmt)).scalars().first()

    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    # Filter transcripts based on privacy flag
    transcripts = [
        TranscriptEntryRead.model_validate(entry)
        for entry in call.transcript_entries
        if include_private or not entry.is_private
    ]

    latency_measurements = [
        LatencyMeasurementRead.model_validate(metric)
        for metric in call.latency_measurements
    ]

    compliance_result_obj = call.compliance_result
    if compliance_result_obj is None:
        stmt_comp = select(ComplianceResult).where(ComplianceResult.call_id == call_id)
        compliance_result_obj = (await db.execute(stmt_comp)).scalars().first()

    if compliance_result_obj is None and call.status in ("ENDED", "FAILED") and len(call.transcript_entries) > 0:
        try:
            compliance_result_obj = await compliance_service.run_and_persist_compliance(call_id, db)
        except Exception as e:
            logger.warning("Could not auto-evaluate compliance on call retrieval for %s: %s", call_id, e)

    compliance_result = (
        ComplianceResultRead.model_validate(compliance_result_obj)
        if compliance_result_obj
        else None
    )

    recording_disclosure = None
    refund_promise = None
    if compliance_result_obj:
        rec_details = "Recording disclosure detected" if compliance_result_obj.recording_rule_pass else "No valid recording disclosure within first 30 seconds"
        if compliance_result_obj.recording_rule_details and isinstance(compliance_result_obj.recording_rule_details, dict):
            rec_details = compliance_result_obj.recording_rule_details.get("details", rec_details)

        recording_disclosure = RecordingDisclosureResult(
            **{
                "pass": compliance_result_obj.recording_rule_pass,
                "details": rec_details,
            }
        )
        refund_promise = RefundPromiseResult(
            **{
                "pass": compliance_result_obj.refund_rule_pass,
                "offending_line": compliance_result_obj.refund_offending_line,
            }
        )

    return CallDetailResponse(
        id=call.id,
        agent_id=call.agent_id,
        room_name=call.room_name,
        status=CallStatus(call.status),
        started_at=call.started_at,
        ended_at=call.ended_at,
        created_at=call.created_at,
        transcript=transcripts,
        transcripts=transcripts,
        latency_measurements=latency_measurements,
        compliance_result=compliance_result,
        recording_disclosure=recording_disclosure,
        refund_promise=refund_promise,
    )


@router.post(
    "/{call_id}/finalize",
    response_model=CallDetailResponse,
    summary="Finalize Call, Persist Transcripts, and Run Post-Call Compliance",
)
async def finalize_call(
    call_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CallDetailResponse:
    """
    Finalizes the call: flushes transcripts, runs compliance checks,
    and marks the call ENDED. Safe to call multiple times without side effects.
    """
    stmt = select(Call).where(Call.id == call_id)
    call = (await db.execute(stmt)).scalars().first()
    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    try:
        await compliance_service.run_and_persist_compliance(call_id=call_id, db=db)
    except Exception as e:
        logger.error("Error during call finalization for %s: %s", call_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Call finalization failed: {str(e)}",
        )

    return await get_call(call_id=call_id, include_private=False, db=db)


@router.post(
    "/{call_id}/end",
    response_model=CallDetailResponse,
    summary="End Call and Run Post-Call Compliance",
)
async def end_call(
    call_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CallDetailResponse:
    """Alias for call finalization."""
    return await finalize_call(call_id=call_id, db=db)



@router.post(
    "/{call_id}/supervisor-token",
    response_model=SupervisorTokenResponse,
    summary="Generate Restricted Stealth Supervisor Access Token",
)
async def generate_supervisor_token(
    call_id: uuid.UUID,
    payload: SupervisorTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> SupervisorTokenResponse:
    """
    Generates a stealth supervisor access token with:
    - Audio subscribe ONLY (cannot speak or publish audio track)
    - Data channel publish ONLY (private coaching whispers)
    - Hidden participant flag
    """
    stmt = select(Call).where(Call.id == call_id)
    call = (await db.execute(stmt)).scalars().first()

    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    supervisor_identity = payload.supervisor_identity or f"supervisor-{uuid.uuid4().hex[:8]}"

    try:
        token = livekit_service.generate_supervisor_token(
            room_name=call.room_name,
            identity=supervisor_identity,
            name=payload.supervisor_name or supervisor_identity,
        )
    except Exception as e:
        logger.error("Failed to generate supervisor token: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate supervisor access token",
        )

    return SupervisorTokenResponse(
        call_id=call.id,
        room_name=call.room_name,
        supervisor_identity=supervisor_identity,
        livekit_url=livekit_service.ws_url,
        livekit_token=token,
    )


@router.get(
    "",
    response_model=List[CallRead],
    summary="List Recent Call Sessions",
)
async def list_calls(
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> List[CallRead]:
    """
    Lists recent call sessions for supervisor overview.
    """
    stmt = select(Call).order_by(Call.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())
