import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.compliance import ComplianceResultRead
from backend.app.schemas.latency import LatencyMeasurementRead
from backend.app.schemas.transcript import TranscriptEntryRead


class CallStatus(str, Enum):
    CREATED = "CREATED"
    CONNECTING = "CONNECTING"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    FAILED = "FAILED"


class CallBase(BaseModel):
    agent_id: uuid.UUID
    room_name: str = Field(..., min_length=1, max_length=255, description="Unique LiveKit room name")
    status: CallStatus = Field(default=CallStatus.CREATED, description="Current call lifecycle status")


class CallCreateRequest(BaseModel):
    agent_id: uuid.UUID = Field(..., description="ID of the agent profile to bind to this call")
    room_name: Optional[str] = Field(None, min_length=1, max_length=255, description="Optional custom LiveKit room name")
    customer_identity: Optional[str] = Field(None, min_length=1, max_length=255, description="Optional custom customer participant identity")
    customer_name: Optional[str] = Field(None, min_length=1, max_length=255, description="Optional customer display name")


class CallCreate(CallBase):
    started_at: Optional[datetime] = None


class CallUpdate(BaseModel):
    status: Optional[CallStatus] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class CallRead(CallBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: datetime


class CallInitResponse(BaseModel):
    call_id: uuid.UUID
    agent_id: uuid.UUID
    room_name: str
    status: CallStatus
    customer_identity: str
    livekit_url: str
    livekit_token: str
    created_at: datetime


class SupervisorTokenRequest(BaseModel):
    supervisor_identity: Optional[str] = Field(None, min_length=1, max_length=255, description="Supervisor identity")
    supervisor_name: Optional[str] = Field(None, min_length=1, max_length=255, description="Supervisor display name")


class SupervisorTokenResponse(BaseModel):
    call_id: uuid.UUID
    room_name: str
    supervisor_identity: str
    livekit_url: str
    livekit_token: str


class RecordingDisclosureResult(BaseModel):
    pass_: bool = Field(..., alias="pass")
    details: str

    model_config = ConfigDict(populate_by_name=True)


class RefundPromiseResult(BaseModel):
    pass_: bool = Field(..., alias="pass")
    offending_line: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class CallDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    room_name: str
    status: CallStatus
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: datetime
    transcript: List[TranscriptEntryRead] = Field(default_factory=list)
    transcripts: List[TranscriptEntryRead] = Field(default_factory=list)
    latency_measurements: List[LatencyMeasurementRead] = Field(default_factory=list)
    compliance_result: Optional[ComplianceResultRead] = None
    recording_disclosure: Optional[RecordingDisclosureResult] = None
    refund_promise: Optional[RefundPromiseResult] = None
