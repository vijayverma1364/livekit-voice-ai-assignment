import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.config import settings
from backend.app.db.models import Call, ComplianceResult, TranscriptEntry

logger = logging.getLogger("backend.compliance_service")

# Regex pattern for deterministic detection of recording disclosure in agent speech
DISCLOSURE_PATTERNS = [
    re.compile(r"\b(this\s+call|the\s+call|our\s+call|call|conversation|session)\b.*\b(recorded|recording|monitored)\b", re.IGNORECASE),
    re.compile(r"\b(recorded|recording|monitored)\b.*\b(this\s+call|the\s+call|our\s+call|call|conversation|session)\b", re.IGNORECASE),
    re.compile(r"\brecorded\s+for\s+(quality|training|assurance)\b", re.IGNORECASE),
    re.compile(r"\bcall\s+is\s+(being\s+)?recorded\b", re.IGNORECASE),
    re.compile(r"\brecording\s+(this\s+|the\s+)?call\b", re.IGNORECASE),
]


class RecordingDisclosureOutput(BaseModel):
    pass_: bool = Field(..., alias="pass")
    details: str

    model_config = ConfigDict(populate_by_name=True)


class RefundComplianceOutput(BaseModel):
    pass_: bool = Field(..., alias="pass")
    offending_line: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


REFUND_AUDIT_SYSTEM_PROMPT = """You are a strict compliance auditor for customer support calls.
Your sole task is to check whether the support agent promised, offered, or guaranteed a refund to the customer.

Strict Policy: "The agent must not promise a refund."

Rules:
1. Examine all agent utterances provided in the transcript.
2. If the agent promised, guaranteed, or offered a refund (e.g. "I will issue a full refund", "We will refund your payment", "I can refund your money", "I promise you a refund"):
   Output JSON:
   {
     "pass": false,
     "offending_line": "<exact line spoken by the agent containing the refund promise>"
   }
3. If the agent did NOT promise or offer any refund (including if they refused a refund, offered troubleshooting, replacement, discount, or never mentioned refunds):
   Output JSON:
   {
     "pass": true,
     "offending_line": null
   }
4. You must output ONLY a valid JSON object matching this schema. Do not include markdown codeblocks or extra text.
"""


class ComplianceService:
    """
    Dedicated service handling post-call compliance audits:
    - Rule 1 (Deterministic): Recording disclosure within first 30 seconds.
    - Rule 2 (LLM-Assisted): No refund promise policy.
    - Persistence and idempotency guarantees.
    """

    def __init__(self, openai_client: Optional[AsyncOpenAI] = None):
        self._openai_client = openai_client

    def _get_openai_client(self) -> Optional[AsyncOpenAI]:
        if self._openai_client is not None:
            return self._openai_client
        api_key = settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY")
        if api_key and api_key.strip():
            self._openai_client = AsyncOpenAI(api_key=api_key.strip())
            return self._openai_client
        return None

    def is_recording_disclosure_utterance(self, text: str) -> bool:
        """
        Determines whether a spoken agent utterance contains a valid recording disclosure.
        """
        clean_text = text.strip()
        if not clean_text:
            return False
        for pattern in DISCLOSURE_PATTERNS:
            if pattern.search(clean_text):
                return True
        return False

    def evaluate_recording_disclosure(
        self,
        call_started_at: Optional[datetime],
        transcripts: List[TranscriptEntry],
    ) -> Dict[str, Any]:
        """
        Deterministic Rule 1 evaluation:
        Checks whether the agent informed the caller that the call is being recorded
        within the first 30 seconds of the call.
        MUST NOT use an LLM.
        """
        # Filter for agent utterances (case-insensitive speaker check, not private supervisor whisper)
        agent_turns = [
            t for t in transcripts
            if getattr(t, "speaker", "").lower() == "agent" and not getattr(t, "is_private", False)
        ]

        first_disclosure_offset: Optional[float] = None

        for turn in agent_turns:
            if self.is_recording_disclosure_utterance(turn.text):
                # Calculate elapsed time in seconds from call start
                offset_s: float = 0.0

                # Check timestamp difference if both call_started_at and turn.timestamp are present
                if call_started_at and getattr(turn, "timestamp", None):
                    diff = (turn.timestamp - call_started_at).total_seconds()
                    # If timestamp difference is positive and relative_time_ms is not explicitly higher
                    if diff > 0 and (not getattr(turn, "relative_time_ms", None) or turn.relative_time_ms == 0):
                        offset_s = max(0.0, diff)
                    elif getattr(turn, "relative_time_ms", None) is not None and turn.relative_time_ms >= 0:
                        offset_s = turn.relative_time_ms / 1000.0
                    else:
                        offset_s = max(0.0, diff)
                elif getattr(turn, "relative_time_ms", None) is not None and turn.relative_time_ms >= 0:
                    offset_s = turn.relative_time_ms / 1000.0
                elif call_started_at and getattr(turn, "timestamp", None):
                    offset_s = max(0.0, (turn.timestamp - call_started_at).total_seconds())

                first_disclosure_offset = offset_s
                break

        if first_disclosure_offset is not None and first_disclosure_offset <= 30.0:
            details_str = f"Recording disclosure detected at {first_disclosure_offset:.1f} seconds"
            return {"pass": True, "details": details_str}
        else:
            return {"pass": False, "details": "No valid recording disclosure within first 30 seconds"}

    async def evaluate_refund_policy(
        self,
        agent_transcripts: List[TranscriptEntry],
        custom_client: Optional[AsyncOpenAI] = None,
    ) -> Dict[str, Any]:
        """
        LLM Rule 2 evaluation:
        Evaluates whether the agent promised a refund in the call transcript.
        Strictly validated using Pydantic.
        Never fakes PASS if the LLM is unavailable or produces invalid output.
        """
        # Filter agent utterances
        agent_lines = [
            t.text.strip()
            for t in agent_transcripts
            if getattr(t, "speaker", "").lower() == "agent"
            and not getattr(t, "is_private", False)
            and t.text.strip()
        ]

        if not agent_lines:
            # If agent spoke no words, no refund was promised
            return {"pass": True, "offending_line": None}

        client = custom_client or self._get_openai_client()
        if client is None:
            logger.error("Rule 2 Compliance: LLM client is unavailable (missing OPENAI_API_KEY).")
            return {
                "pass": False,
                "offending_line": "Compliance LLM unavailable: Missing OPENAI_API_KEY",
            }

        transcript_prompt = "\n".join(f"- {line}" for line in agent_lines)

        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": REFUND_AUDIT_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Please audit the following agent transcript:\n\n{transcript_prompt}",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            raw_content = response.choices[0].message.content or ""
        except Exception as exc:
            logger.error("Rule 2 Compliance: LLM request failed: %s", exc)
            return {
                "pass": False,
                "offending_line": f"Compliance LLM unavailable: {exc}",
            }

        # Parse and validate structured output
        try:
            parsed_json = json.loads(raw_content)
            validated = RefundComplianceOutput.model_validate(parsed_json)
            return validated.model_dump(by_alias=True)
        except (json.JSONDecodeError, ValidationError) as val_err:
            logger.error("Rule 2 Compliance: LLM returned invalid structured output: %s (Raw: '%s')", val_err, raw_content)
            return {
                "pass": False,
                "offending_line": f"Invalid LLM compliance output: {val_err}",
            }

    async def run_and_persist_compliance(
        self,
        call_id: uuid.UUID,
        db: AsyncSession,
        custom_openai_client: Optional[AsyncOpenAI] = None,
    ) -> ComplianceResult:
        """
        Executes the compliance evaluation for a call and persists the result.
        Guaranteed idempotent:
        - If compliance result already exists, immediately returns existing record.
        - Does NOT repeat expensive compliance evaluation or duplicate records.
        - Transitions call status to ENDED if not already marked.
        """
        # 1. Fetch Call with transcript entries and existing compliance result
        stmt = (
            select(Call)
            .where(Call.id == call_id)
            .options(
                selectinload(Call.transcript_entries),
                selectinload(Call.compliance_result),
            )
        )
        result = await db.execute(stmt)
        call = result.scalars().first()

        if not call:
            raise ValueError(f"Call with ID {call_id} not found in database.")

        # Idempotency check: directly query ComplianceResult to prevent re-evaluation
        stmt_comp = select(ComplianceResult).where(ComplianceResult.call_id == call_id)
        existing_comp = (await db.execute(stmt_comp)).scalars().first()
        if existing_comp is not None:
            logger.info("Call %s: Compliance already evaluated. Returning existing record.", call_id)
            if call.status != "ENDED":
                call.status = "ENDED"
                if not call.ended_at:
                    call.ended_at = datetime.now(timezone.utc)
                await db.commit()
            return existing_comp

        # 2. Run Rule 1 (Deterministic Recording Disclosure within 30s)
        rec_result = self.evaluate_recording_disclosure(
            call_started_at=call.started_at,
            transcripts=call.transcript_entries,
        )

        # 3. Run Rule 2 (LLM Refund Promise Audit)
        refund_result = await self.evaluate_refund_policy(
            agent_transcripts=call.transcript_entries,
            custom_client=custom_openai_client,
        )

        # 4. Persist ComplianceResult to database
        compliance_record = ComplianceResult(
            id=uuid.uuid4(),
            call_id=call.id,
            recording_rule_pass=rec_result["pass"],
            recording_rule_details={"details": rec_result["details"]},
            refund_rule_pass=refund_result["pass"],
            refund_offending_line=refund_result.get("offending_line"),
            checked_at=datetime.now(timezone.utc),
        )
        db.add(compliance_record)

        # 5. Transition call status to ENDED
        call.status = "ENDED"
        if not call.ended_at:
            call.ended_at = datetime.now(timezone.utc)

        try:
            await db.commit()
            await db.refresh(compliance_record)
            logger.info(
                "Call %s: Successfully finalized and persisted compliance result (Recording: %s, Refund: %s)",
                call_id, rec_result["pass"], refund_result["pass"],
            )
            return compliance_record
        except IntegrityError:
            # Handle concurrent finalization race condition gracefully
            await db.rollback()
            stmt_retry = select(ComplianceResult).where(ComplianceResult.call_id == call_id)
            existing = (await db.execute(stmt_retry)).scalars().first()
            if existing:
                return existing
            raise


# Global singleton compliance service instance
compliance_service = ComplianceService()
