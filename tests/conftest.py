import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from videre.database.tables import Base

TEST_DATABASE_URL = os.environ.get("VIDERE_TEST_DATABASE_URL", "")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Yield a session against an empty database inside a transaction that is always rolled back."""

    if not TEST_DATABASE_URL:
        if os.environ.get("VIDERE_REQUIRE_DATABASE_TESTS") == "1":
            pytest.fail("VIDERE_TEST_DATABASE_URL is required for database integration tests")
        pytest.skip("set VIDERE_TEST_DATABASE_URL to run database integration tests")

    engine = create_async_engine(TEST_DATABASE_URL)
    connection = await engine.connect()
    transaction = await connection.begin()
    session_factory = async_sessionmaker(bind=connection, expire_on_commit=False)
    async with session_factory() as active_session:
        for table in reversed(Base.metadata.sorted_tables):
            await active_session.execute(delete(table))
        yield active_session
    await transaction.rollback()
    await connection.close()
    await engine.dispose()
