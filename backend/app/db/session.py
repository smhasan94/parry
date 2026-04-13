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
    pool_recycle=600,  # recycle connections after 10 min to avoid stale/leaked conns
    pool_pre_ping=True,  # verify connection is alive before checkout
    connect_args={
        "server_settings": {
            "statement_timeout": "30000",  # 30s — kill runaway queries
            "lock_timeout": "10000",  # 10s — don't wait forever on locks
        },
        "timeout": 10,  # 10s connect timeout
    },
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
        pool_recycle=600,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "statement_timeout": "60000",  # 60s — tasks can run longer queries
                "lock_timeout": "10000",
            },
            "timeout": 10,
        },
    )
    return async_sessionmaker(
        task_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
