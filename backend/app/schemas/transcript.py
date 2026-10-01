import uuid
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class SpeakerType(str, Enum):
    USER = "user"
    CUSTOMER = "customer"
    AGENT = "agent"
    SUPERVISOR = "supervisor"


class TranscriptEntryBase(BaseModel):
    call_id: uuid.UUID
    speaker: SpeakerType
    text: str = Field(..., min_length=1, description="Utterance text")
    relative_time_ms: int = Field(..., ge=0, description="Offset in milliseconds from call start")
    is_private: bool = Field(default=False, description="Flag for private supervisor whisper")


class TranscriptEntryCreate(TranscriptEntryBase):
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TranscriptEntryRead(TranscriptEntryBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    timestamp: datetime
