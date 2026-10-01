-- =============================================================================
-- Migration 001: Initial Schema for Supervised Voice AI Agent
-- Compatible with PostgreSQL 14+
-- =============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------------------------
-- 1. AGENTS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    system_prompt TEXT NOT NULL,
    voice VARCHAR(100) NOT NULL DEFAULT 'alloy',
    model VARCHAR(100) NOT NULL DEFAULT 'gpt-4o-mini',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 2. CALLS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    room_name VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(50) NOT NULL DEFAULT 'CREATED' 
        CHECK (status IN ('CREATED', 'CONNECTING', 'ACTIVE', 'ENDED', 'FAILED')),
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_calls_agent_id ON calls(agent_id);
CREATE INDEX IF NOT EXISTS idx_calls_room_name ON calls(room_name);
CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);
CREATE INDEX IF NOT EXISTS idx_calls_created_at ON calls(created_at DESC);

-- -----------------------------------------------------------------------------
-- 3. TRANSCRIPT_ENTRIES
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transcript_entries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    call_id UUID NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    speaker VARCHAR(50) NOT NULL CHECK (speaker IN ('customer', 'agent', 'supervisor')),
    text TEXT NOT NULL,
    relative_time_ms BIGINT NOT NULL CHECK (relative_time_ms >= 0),
    is_private BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_transcripts_call_id ON transcript_entries(call_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_timestamp ON transcript_entries(timestamp ASC);
CREATE INDEX IF NOT EXISTS idx_transcripts_relative_time ON transcript_entries(call_id, relative_time_ms ASC);

-- -----------------------------------------------------------------------------
-- 4. LATENCY_MEASUREMENTS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS latency_measurements (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    call_id UUID NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    turn_number INTEGER NOT NULL CHECK (turn_number >= 0),
    user_stop_ms BIGINT,
    stt_final_ms BIGINT,
    llm_first_token_ms BIGINT,
    tts_first_audio_ms BIGINT,
    audio_published_ms BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_latency_call_turn UNIQUE (call_id, turn_number)
);

CREATE INDEX IF NOT EXISTS idx_latency_call_id ON latency_measurements(call_id);

-- -----------------------------------------------------------------------------
-- 5. COMPLIANCE_RESULTS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS compliance_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    call_id UUID NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    recording_rule_pass BOOLEAN NOT NULL,
    recording_rule_details JSONB,
    refund_rule_pass BOOLEAN NOT NULL,
    refund_offending_line TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_compliance_call UNIQUE (call_id)
);

CREATE INDEX IF NOT EXISTS idx_compliance_call_id ON compliance_results(call_id);
