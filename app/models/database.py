"""SQLAlchemy database engine and session management."""
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL, DATABASE_URL_SYNC

# Async engine for FastAPI
async_engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine for seeding and scraping
sync_engine = create_engine(DATABASE_URL_SYNC, echo=False)
SyncSession = sessionmaker(sync_engine)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency: yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create all tables."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def init_db_sync():
    """Create all tables synchronously (for seeding)."""
    Base.metadata.create_all(sync_engine)
