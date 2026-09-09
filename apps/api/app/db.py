import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(
    os.getenv("DATA_DIR")
    or (Path(__file__).resolve().parents[3] / "data" / "development")
)
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL and os.getenv("POSTGRES_HOST"):
    DATABASE_URL = URL.create(
        "postgresql+psycopg",
        username=os.getenv("POSTGRES_USER", "arena"),
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ["POSTGRES_HOST"],
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "arena"),
    )
if not DATABASE_URL:
    DATABASE_URL = f"sqlite:///{DATA_DIR / 'platform.db'}"
engine = create_engine(
    DATABASE_URL,
    connect_args=(
        {"check_same_thread": False} if str(DATABASE_URL).startswith("sqlite") else {}
    ),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as db:
        yield db
