import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    voice: Mapped[str] = mapped_column(String(100), nullable=False, default="alloy")
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="gpt-4o-mini")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    calls: Mapped[List["Call"]] = relationship(
        "Call",
        back_populates="agent",
        passive_deletes=False,
    )

    def __repr__(self) -> str:
        return f"<Agent(id={self.id}, name='{self.name}', voice='{self.voice}', model='{self.model}')>"


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    room_name: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="CREATED",
        index=True,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATED', 'CONNECTING', 'ACTIVE', 'ENDED', 'FAILED')",
            name="calls_status_check",
        ),
        Index("idx_calls_created_at", created_at.desc()),
    )

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="calls")
    transcript_entries: Mapped[List["TranscriptEntry"]] = relationship(
        "TranscriptEntry",
        back_populates="call",
        cascade="all, delete-orphan",
        order_by="TranscriptEntry.relative_time_ms",
    )
    latency_measurements: Mapped[List["LatencyMeasurement"]] = relationship(
        "LatencyMeasurement",
        back_populates="call",
        cascade="all, delete-orphan",
        order_by="LatencyMeasurement.turn_number",
    )
    compliance_result: Mapped[Optional["ComplianceResult"]] = relationship(
        "ComplianceResult",
        back_populates="call",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Call(id={self.id}, room_name='{self.room_name}', status='{self.status}')>"


class TranscriptEntry(Base):
    __tablename__ = "transcript_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    speaker: Mapped[str] = mapped_column(String(50), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    relative_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        CheckConstraint("relative_time_ms >= 0", name="chk_transcript_relative_time"),
        CheckConstraint(
            "speaker IN ('customer', 'user', 'agent', 'supervisor')",
            name="chk_transcript_speaker",
        ),
        Index("idx_transcripts_relative_time", "call_id", "relative_time_ms"),
    )

    # Relationships
    call: Mapped["Call"] = relationship("Call", back_populates="transcript_entries")

    def __repr__(self) -> str:
        return f"<TranscriptEntry(id={self.id}, call_id={self.call_id}, speaker='{self.speaker}', relative_time_ms={self.relative_time_ms})>"


class LatencyMeasurement(Base):
    __tablename__ = "latency_measurements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    user_stop_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    stt_final_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    llm_first_token_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    tts_first_audio_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    audio_published_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("turn_number >= 0", name="chk_latency_turn_number"),
        UniqueConstraint("call_id", "turn_number", name="uq_latency_call_turn"),
    )

    # Relationships
    call: Mapped["Call"] = relationship("Call", back_populates="latency_measurements")

    def __repr__(self) -> str:
        return f"<LatencyMeasurement(id={self.id}, call_id={self.call_id}, turn_number={self.turn_number})>"


class ComplianceResult(Base):
    __tablename__ = "compliance_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    recording_rule_pass: Mapped[bool] = mapped_column(Boolean, nullable=False)
    recording_rule_details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    refund_rule_pass: Mapped[bool] = mapped_column(Boolean, nullable=False)
    refund_offending_line: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("call_id", name="uq_compliance_call"),
    )

    # Relationships
    call: Mapped["Call"] = relationship("Call", back_populates="compliance_result")

    def __repr__(self) -> str:
        return f"<ComplianceResult(id={self.id}, call_id={self.call_id}, recording_rule_pass={self.recording_rule_pass}, refund_rule_pass={self.refund_rule_pass})>"
