import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Agent
from backend.app.db.session import get_db
from backend.app.schemas.agent import AgentCreate, AgentRead

router = APIRouter(prefix="/agents", tags=["Agents"])


@router.post(
    "",
    response_model=AgentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Voice AI Agent Configuration",
)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
) -> AgentRead:
    """
    Creates and persists a new AI Agent profile with custom system prompts,
    voice attributes, and model selection.
    """
    agent = Agent(
        name=payload.name,
        system_prompt=payload.system_prompt,
        voice=payload.voice,
        model=payload.model,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.get(
    "/{agent_id}",
    response_model=AgentRead,
    summary="Get Agent Configuration by ID",
)
async def get_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AgentRead:
    """
    Retrieves an existing Agent profile by its UUID.
    """
    stmt = select(Agent).where(Agent.id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalars().first()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    return agent


@router.get(
    "",
    response_model=List[AgentRead],
    summary="List All Agent Configurations",
)
async def list_agents(
    db: AsyncSession = Depends(get_db),
) -> List[AgentRead]:
    """
    Lists all available Agent configurations.
    """
    stmt = select(Agent).order_by(Agent.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())
