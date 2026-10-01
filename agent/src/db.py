import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, select, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agent.src.config import settings

logger = logging.getLogger("agent.db")


# Define lightweight database models for worker operations to avoid inter-service coupling
class Base(DeclarativeBase):
    pass


class DBAgent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    voice: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)


class DBCall(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    room_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DBTranscriptEntry(Base):
    __tablename__ = "transcript_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    call_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    speaker: Mapped[str] = mapped_column(String(50), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    relative_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class DBLatencyMeasurement(Base):
    __tablename__ = "latency_measurements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    call_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    user_stop_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    stt_final_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    llm_first_token_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    tts_first_audio_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    audio_published_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


# Typed DTOs
@dataclass
class AgentConfig:
    id: uuid.UUID
    name: str
    system_prompt: str
    voice: str
    model: str


@dataclass
class CallRecord:
    id: uuid.UUID
    agent_id: uuid.UUID
    room_name: str
    status: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


class AgentDatabase:
    def __init__(self, db_url: Optional[str] = None, poolclass: Optional[Any] = None):
        self.url = db_url or settings.async_database_url
        engine_kwargs: dict[str, Any] = {"echo": False}
        if poolclass is not None:
            engine_kwargs["poolclass"] = poolclass
        else:
            from sqlalchemy.pool import NullPool
            engine_kwargs["poolclass"] = NullPool

        self.engine = create_async_engine(self.url, **engine_kwargs)
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    def reconfigure_pool(self, poolclass: Any) -> None:
        """
        Reconfigures the connection engine with a custom poolclass (e.g. NullPool for tests).
        """
        self.engine = create_async_engine(self.url, poolclass=poolclass, echo=False)
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """
        Provides an async session context manager with automatic rollback on exception.
        """
        async with self.session_factory() as s:
            try:
                yield s
            except Exception:
                await s.rollback()
                raise

    async def load_agent_config(self, agent_id: uuid.UUID) -> Optional[AgentConfig]:
        """
        Loads the agent configuration (name, system_prompt, voice, model)
        from PostgreSQL by agent UUID.
        """
        async with self.session() as s:
            stmt = select(DBAgent).where(DBAgent.id == agent_id)
            result = await s.execute(stmt)
            agent_row = result.scalars().first()
            if not agent_row:
                logger.warning("No agent found in database with ID: %s", agent_id)
                return None
            return AgentConfig(
                id=agent_row.id,
                name=agent_row.name,
                system_prompt=agent_row.system_prompt,
                voice=agent_row.voice,
                model=agent_row.model,
            )

    async def get_call_by_room(self, room_name: str) -> Optional[CallRecord]:
        """
        Fetches the Call record from database using the unique room name.
        """
        async with self.session() as s:
            stmt = select(DBCall).where(DBCall.room_name == room_name)
            result = await s.execute(stmt)
            call_row = result.scalars().first()
            if not call_row:
                logger.warning("No call record found in database for room: %s", room_name)
                return None
            return CallRecord(
                id=call_row.id,
                agent_id=call_row.agent_id,
                room_name=call_row.room_name,
                status=call_row.status,
                started_at=call_row.started_at,
                ended_at=call_row.ended_at,
            )

    async def update_call_status(
        self,
        call_id: uuid.UUID,
        status: str,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
    ) -> bool:
        """
        Updates the lifecycle status of a Call in PostgreSQL.
        """
        async with self.session() as s:
            try:
                values = {"status": status}
                if started_at is not None:
                    values["started_at"] = started_at
                if ended_at is not None:
                    values["ended_at"] = ended_at

                stmt = update(DBCall).where(DBCall.id == call_id).values(**values)
                result = await s.execute(stmt)
                await s.commit()
                logger.info("Updated call %s status to '%s'", call_id, status)
                return result.rowcount > 0
            except Exception as e:
                await s.rollback()
                logger.error("Failed to update call %s status to '%s': %s", call_id, status, e)
                raise

    async def save_transcript_entry(
        self,
        call_id: uuid.UUID,
        speaker: str,
        text: str,
        relative_time_ms: int,
        is_private: bool = False,
    ) -> uuid.UUID:
        """
        Persists a single dialogue turn into transcript_entries.
        """
        clamped_relative_time_ms = max(0, int(relative_time_ms))
        async with self.session() as s:
            try:
                entry = DBTranscriptEntry(
                    id=uuid.uuid4(),
                    call_id=call_id,
                    speaker=speaker,
                    text=text,
                    relative_time_ms=clamped_relative_time_ms,
                    is_private=is_private,
                )
                s.add(entry)
                await s.commit()
                logger.debug(
                    "Saved transcript turn for call %s [%s] (+%dms): %s",
                    call_id, speaker, clamped_relative_time_ms, text[:40],
                )
                return entry.id
            except Exception as e:
                await s.rollback()
                logger.error("Failed to save transcript entry for call %s: %s", call_id, e)
                raise

    async def save_latency_measurement(
        self,
        call_id: uuid.UUID,
        turn_number: int,
        user_stop_ms: Optional[int] = None,
        stt_final_ms: Optional[int] = None,
        llm_first_token_ms: Optional[int] = None,
        tts_first_audio_ms: Optional[int] = None,
        audio_published_ms: Optional[int] = None,
    ) -> uuid.UUID:
        """
        Idempotently persists or updates a turn's latency measurement in latency_measurements.
        Handles unique constraint on (call_id, turn_number) by updating existing record if present.
        """
        async with self.session() as s:
            try:
                stmt = select(DBLatencyMeasurement).where(
                    DBLatencyMeasurement.call_id == call_id,
                    DBLatencyMeasurement.turn_number == turn_number,
                )
                res = await s.execute(stmt)
                existing = res.scalars().first()

                if existing:
                    if user_stop_ms is not None:
                        existing.user_stop_ms = user_stop_ms
                    if stt_final_ms is not None:
                        existing.stt_final_ms = stt_final_ms
                    if llm_first_token_ms is not None:
                        existing.llm_first_token_ms = llm_first_token_ms
                    if tts_first_audio_ms is not None:
                        existing.tts_first_audio_ms = tts_first_audio_ms
                    if audio_published_ms is not None:
                        existing.audio_published_ms = audio_published_ms
                    await s.commit()
                    logger.debug(
                        "Updated latency measurement for call %s turn %d",
                        call_id, turn_number,
                    )
                    return existing.id
                else:
                    new_meas = DBLatencyMeasurement(
                        id=uuid.uuid4(),
                        call_id=call_id,
                        turn_number=turn_number,
                        user_stop_ms=user_stop_ms,
                        stt_final_ms=stt_final_ms,
                        llm_first_token_ms=llm_first_token_ms,
                        tts_first_audio_ms=tts_first_audio_ms,
                        audio_published_ms=audio_published_ms,
                    )
                    s.add(new_meas)
                    await s.commit()
                    logger.debug(
                        "Inserted latency measurement for call %s turn %d",
                        call_id, turn_number,
                    )
                    return new_meas.id
            except Exception as e:
                await s.rollback()
                logger.error("Failed to save latency measurement for call %s: %s", call_id, e)
                raise

    async def get_latency_measurements(self, call_id: uuid.UUID) -> list[DBLatencyMeasurement]:
        """
        Fetches all latency measurements for a given call, ordered by turn_number.
        """
        async with self.session() as s:
            stmt = (
                select(DBLatencyMeasurement)
                .where(DBLatencyMeasurement.call_id == call_id)
                .order_by(DBLatencyMeasurement.turn_number)
            )
            res = await s.execute(stmt)
            return list(res.scalars().all())

    async def close(self) -> None:
        """
        Disposes of database connection pool on shutdown.
        """
        await self.engine.dispose()


# Global DB client instance for the agent process
db_client = AgentDatabase()
