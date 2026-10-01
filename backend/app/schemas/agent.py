import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class AgentBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Agent human-readable name")
    system_prompt: str = Field(..., min_length=1, description="Agent system instructions")
    voice: str = Field(default="alloy", min_length=1, max_length=100, description="TTS voice identifier")
    model: str = Field(default="gpt-4o-mini", min_length=1, max_length=100, description="LLM model identifier")


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    system_prompt: Optional[str] = Field(None, min_length=1)
    voice: Optional[str] = Field(None, min_length=1, max_length=100)
    model: Optional[str] = Field(None, min_length=1, max_length=100)


class AgentRead(AgentBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
