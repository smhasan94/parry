from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# Main engine — used by the FastAPI app, which has a single
# long-lived event loop per worker process.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=20,
    max_overflow=10,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


def make_task_session_factory() -> async_sessionmaker[AsyncSession]:
    """Build a fresh engine + session factory for a Celery task.

    Celery's prefork pool runs each task on its own ``asyncio.run()``,
    which creates a new event loop per task. The module-level
    ``engine`` / ``async_session_factory`` are bound to whichever
    loop first touched them and blow up on reuse with
    "Task attached to a different loop". Creating a disposable
    engine per task sidesteps the problem entirely.

    The caller is responsible for disposing of the engine when
    finished — read ``factory.kw["bind"]`` to get the engine and
    call ``await engine.dispose()`` in a finally block.
    """
    task_engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=1,
        max_overflow=2,
    )
    return async_sessionmaker(
        task_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
