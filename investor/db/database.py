from sqlmodel import Session, SQLModel, create_engine

from investor.config import settings

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},  # needed for SQLite + multi-thread
)


def create_db() -> None:
    """Create all tables. Safe to call multiple times (no-op if tables exist)."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    """Return a new database session. Caller is responsible for closing it."""
    return Session(engine)
