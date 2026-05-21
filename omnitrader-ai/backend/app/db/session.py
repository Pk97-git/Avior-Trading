from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, echo=False)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

# Alias used by background services
async_session_factory = AsyncSessionLocal


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# Alias used by API endpoints
async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session
