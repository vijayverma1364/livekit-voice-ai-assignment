import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class ComplianceResultBase(BaseModel):
    call_id: uuid.UUID
    recording_rule_pass: bool = Field(..., description="Whether recording disclosure was made within 30s")
    recording_rule_details: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata such as disclosure offset")
    refund_rule_pass: bool = Field(..., description="Whether refund guarantee policy was respected")
    refund_offending_line: Optional[str] = Field(None, description="Offending utterance line if failed")


class ComplianceResultCreate(ComplianceResultBase):
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class ComplianceResultRead(ComplianceResultBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    checked_at: datetime
