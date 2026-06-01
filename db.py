"""Engine SQLAlchemy + provider de sessão.

Importado por security, routers e main.
"""
from sqlmodel import Session, SQLModel, create_engine

from config import DATABASE_URL

# Render/Heroku às vezes entregam a URL com prefixo "postgres://",
# que o SQLAlchemy 2.0 não aceita. Normaliza para "postgresql://".
_db_url = DATABASE_URL
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(_db_url, echo=False)


def get_session():
    """Dependency do FastAPI: yields uma Session por request."""
    with Session(engine) as session:
        yield session


def create_db_and_tables() -> None:
    """Cria todas as tabelas registradas em SQLModel.metadata."""
    SQLModel.metadata.create_all(engine)
