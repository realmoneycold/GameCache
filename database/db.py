from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from config import settings

# Fallback URL if settings not available
DATABASE_URL = settings.DATABASE_URL if settings else "postgresql+asyncpg://postgres:postgres@localhost:5432/gamehub"

# Auto-detect if PostgreSQL is online; fallback to SQLite if offline
import socket
from urllib.parse import urlparse, urlunparse

# Parse and clean URL for PostgreSQL dialect connection compatibility (e.g. asyncpg ssl)
connect_args = {}
if DATABASE_URL.startswith("postgresql"):
    try:
        parsed = urlparse(DATABASE_URL)
        if "sslmode=require" in parsed.query or "neon.tech" in parsed.netloc:
            connect_args["ssl"] = True
        
        # Rebuild URL without query parameters to avoid asyncpg unexpected argument crashes
        DATABASE_URL = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            "",  # clear query parameters
            parsed.fragment
        ))
    except Exception as e:
        print(f"⚠️ Error parsing DATABASE_URL: {e}")

def is_db_available(url: str) -> bool:
    try:
        clean_url = url.replace("postgresql+asyncpg://", "http://")
        parsed = urlparse(clean_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        s = socket.create_connection((host, port), timeout=2.0)
        s.close()
        return True
    except Exception:
        return False

if not is_db_available(DATABASE_URL):
    print("⚠️ PostgreSQL database is offline! Falling back to local SQLite database: gamehub.db")
    DATABASE_URL = "sqlite+aiosqlite:///gamehub.db"
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        future=True,
    )
else:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        future=True,
        pool_size=10,
        max_overflow=20,
        connect_args=connect_args,
    )

# Async sessionmaker
async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Declarative Base Class
class Base(DeclarativeBase):
    pass

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency or helper to acquire an asynchronous session.
    Automatically handles rollback on exceptions and closes the session.
    """
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
