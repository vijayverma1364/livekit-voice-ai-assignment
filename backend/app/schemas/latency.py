import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, computed_field


class LatencyMeasurementBase(BaseModel):
    call_id: uuid.UUID
    turn_number: int = Field(..., ge=0, description="Sequential dialogue turn index")
    user_stop_ms: Optional[int] = Field(None, ge=0, description="Timestamp VAD detected user stopped speaking")
    stt_final_ms: Optional[int] = Field(None, ge=0, description="Timestamp STT emitted final transcript")
    llm_first_token_ms: Optional[int] = Field(None, ge=0, description="Timestamp first LLM token arrived")
    tts_first_audio_ms: Optional[int] = Field(None, ge=0, description="Timestamp first TTS audio chunk ready")
    audio_published_ms: Optional[int] = Field(None, ge=0, description="Timestamp audio chunk published to room")


class LatencyMeasurementCreate(LatencyMeasurementBase):
    pass


class LatencyMeasurementRead(LatencyMeasurementBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime

    @computed_field
    @property
    def stt_latency_ms(self) -> Optional[int]:
        if self.stt_final_ms is not None and self.user_stop_ms is not None:
            return max(0, self.stt_final_ms - self.user_stop_ms)
        return None

    @computed_field
    @property
    def llm_first_token_latency_ms(self) -> Optional[int]:
        if self.llm_first_token_ms is not None and self.stt_final_ms is not None:
            return max(0, self.llm_first_token_ms - self.stt_final_ms)
        return None

    @computed_field
    @property
    def tts_first_audio_latency_ms(self) -> Optional[int]:
        if self.tts_first_audio_ms is not None and self.llm_first_token_ms is not None:
            return max(0, self.tts_first_audio_ms - self.llm_first_token_ms)
        return None

    @computed_field
    @property
    def publish_latency_ms(self) -> Optional[int]:
        if self.audio_published_ms is not None and self.tts_first_audio_ms is not None:
            return max(0, self.audio_published_ms - self.tts_first_audio_ms)
        return None

    @computed_field
    @property
    def overall_latency_ms(self) -> Optional[int]:
        if self.audio_published_ms is not None and self.user_stop_ms is not None:
            return max(0, self.audio_published_ms - self.user_stop_ms)
        return None
