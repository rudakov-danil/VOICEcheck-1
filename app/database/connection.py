"""
Database connection and session management.
Implements async connection pooling for PostgreSQL.
"""

import asyncio
import logging
from typing import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from .models import Base

logger = logging.getLogger(__name__)

# Global engine and sessionmaker
engine = None
SessionLocal = None
ASYNC_DB_URL = None


class DatabaseConfig:
    """
    Configuration database connection settings.
    """

    def __init__(
        self,
        db_url: str,
        pool_size: int = 20,
        max_overflow: int = 30,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
        echo: bool = False
    ):
        """
        Initialize database configuration.

        Args:
            db_url: Database connection URL
            pool_size: Number of connections in the pool
            max_overflow: Maximum overflow connections
            pool_timeout: Timeout for getting connection from pool
            pool_recycle: Connection recycle time in seconds
            echo: Enable SQL logging for debugging
        """
        self.db_url = db_url
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        self.echo = echo


class DatabaseManager:
    """
    Manager for database connections and sessions.
    """

    def __init__(self, config: DatabaseConfig):
        """
        Initialize database manager.

        Args:
            config: Database configuration
        """
        self.config = config
        self._engine = None
        self._session_factory = None

    async def initialize(self) -> None:
        """
        Initialize the database engine and create tables.
        """
        global engine, SessionLocal, ASYNC_DB_URL

        ASYNC_DB_URL = self.config.db_url

        # Create async engine
        self._engine = create_async_engine(
            ASYNC_DB_URL,
            pool_size=self.config.pool_size,
            max_overflow=self.config.max_overflow,
            pool_timeout=self.config.pool_timeout,
            pool_recycle=self.config.pool_recycle,
            echo=self.config.echo,
            future=True,
        )

        # Create session factory
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            future=True,
        )

        # Create all tables
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info("Database initialized successfully")

    async def close(self) -> None:
        """
        Close the database engine.
        """
        if self._engine:
            await self._engine.dispose()
            logger.info("Database engine closed")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get database session with automatic commit/rollback.

        Returns:
            Async database session
        """
        if not self._session_factory:
            raise RuntimeError("Database not initialized")

        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """
        Get raw database connection for specific operations.

        Returns:
            Async database connection
        """
        if not self._engine:
            raise RuntimeError("Database not initialized")

        async with self._engine.connect() as conn:
            yield conn


# Global database manager instance
_db_manager = None


async def init_db(db_url: str) -> None:
    """
    Initialize database with default configuration.

    Args:
        db_url: Database connection URL
    """
    global _db_manager

    config = DatabaseConfig(
        db_url=db_url,
        pool_size=20,
        max_overflow=30,
        pool_timeout=30,
        pool_recycle=3600,
        echo=False  # Set to True for debugging
    )

    _db_manager = DatabaseManager(config)
    await _db_manager.initialize()


async def close_db() -> None:
    """Close database connections."""
    if _db_manager:
        await _db_manager.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Get database session for dependency injection.

    Returns:
        Async database session
    """
    if not _db_manager:
        raise RuntimeError("Database not initialized")

    async with _db_manager.get_session() as session:
        yield session


async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Get raw database connection.

    Returns:
        Async database connection
    """
    if not _db_manager:
        raise RuntimeError("Database not initialized")

    async with _db_manager.get_connection() as conn:
        yield conn


# Health check function
async def health_check() -> dict:
    """
    Perform database health check.

    Returns:
        Health check status
    """
    if not _db_manager:
        return {"status": "unhealthy", "error": "Database not initialized"}

    try:
        async with _db_manager.get_session() as session:
            # Test basic query using SQLAlchemy
            from sqlalchemy import text
            result = await session.execute(text("SELECT 1"))
            if result.scalar() != 1:
                return {"status": "error", "message": "Invalid response from database"}

            return {"status": "healthy", "message": "Database connection successful"}

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


# Utility functions for common operations
async def execute_query(query: str, params: tuple = None) -> list:
    """
    Execute a simple query and return results.

    Args:
        query: SQL query string
        params: Query parameters

    Returns:
        Query results
    """
    async with get_connection() as conn:
        if params:
            return await conn.fetch(query, *params)
        return await conn.fetch(query)


async def execute_transaction(queries: list[tuple[str, tuple]]) -> list:
    """
    Execute multiple queries in a single transaction.

    Args:
        queries: List of (query, params) tuples

    Returns:
        List of results
    """
    async with get_connection() as conn:
        results = []
        async with conn.transaction():
            for query, params in queries:
                result = await conn.fetch(query, *params) if params else await conn.fetch(query)
                results.append(result)
        return results