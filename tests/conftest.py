from typing import AsyncGenerator
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.config import settings
from backend.app.db.session import get_db
from backend.app.main import app

# Test engine uses NullPool to prevent connection sharing across asyncio event loops in tests
test_engine = create_async_engine(
    settings.async_database_url,
    poolclass=NullPool,
    echo=False,
)

import pytest
from agent.src.db import db_client

TestAsyncSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


@pytest.fixture(autouse=True)
def configure_agent_db_pool():
    """
    Ensures db_client uses NullPool during pytest execution
    to prevent connection sharing across individual test event loops.
    """
    db_client.reconfigure_pool(NullPool)
    yield


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestAsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Test client for FastAPI that reuses the isolated test db_session.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
