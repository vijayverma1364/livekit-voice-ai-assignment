import asyncio
import logging
from sqlalchemy import select
from backend.app.db.models import Agent
from backend.app.db.session import AsyncSessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed")

ACME_SUPPORT_PROMPT = """You are Acme Support Agent, a professional customer support voice assistant for Acme Inc.

Key Behavioral Guidelines:
1. Professional Demeanor: Speak politely, warmly, and concisely. Keep answers conversational and under 2-3 sentences.
2. Mandatory Recording Disclosure: The initial greeting and recording disclosure ("Thank you for calling Acme Support. Please note that this call is recorded for quality assurance. How can I help you today?") is already automatically voiced to the customer upon connecting. NEVER repeat the greeting or recording disclosure again. Listen carefully to all of the customer's context and answer their inquiry directly.
3. Strict Refund Policy: You must NEVER promise, commit to, or guarantee refunds or financial credits. Direct refund requests to written submission at support@acme.com for policy evaluation. Promotional discounts or courtesy coupon codes (such as a 10% discount when approved or instructed) are permitted.
4. Supervisor Whisper Adherence: If you receive a private supervisor instruction (e.g. to offer a 10% discount), you must follow and apply it immediately in your upcoming response. Supervisor coaching instructions take precedence over general restrictions.
5. Supervisor Stealth Guarantee: NEVER mention, reference, or acknowledge the presence of a supervisor, eavesdropping, or coaching to the customer.
"""


async def seed_agent() -> Agent:
    """
    Seeds the default fictional Acme Support Agent into PostgreSQL if not already present.
    """
    async with AsyncSessionLocal() as session:
        # Check if already exists
        stmt = select(Agent).where(Agent.name == "Acme Support Agent")
        result = await session.execute(stmt)
        existing = result.scalars().first()

        if existing:
            logger.info("Acme Support Agent already exists with ID: %s", existing.id)
            existing.system_prompt = ACME_SUPPORT_PROMPT
            existing.voice = "alloy"
            existing.model = "gpt-4o-mini"
            await session.commit()
            await session.refresh(existing)
            return existing

        agent = Agent(
            name="Acme Support Agent",
            system_prompt=ACME_SUPPORT_PROMPT,
            voice="alloy",
            model="gpt-4o-mini",
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        logger.info("Successfully seeded Acme Support Agent with ID: %s", agent.id)
        return agent


if __name__ == "__main__":
    asyncio.run(seed_agent())
