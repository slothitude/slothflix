import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from slothflix.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    f"sqlite+aiosqlite:///{settings.cache_db_path}",
    echo=False,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
