"""Engine SQLAlchemy + provider de sessão.

Importado por security, routers e main.
"""
from sqlalchemy import inspect, text
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


def _ensure_columns() -> None:
    """Adiciona colunas novas a tabelas já existentes.

    `create_all` cria tabelas que faltam, mas NUNCA faz ALTER em tabelas
    existentes. Como o deploy do Render não roda Alembic, garantimos aqui,
    de forma idempotente, as colunas adicionadas depois da criação da tabela.
    """
    try:
        insp = inspect(engine)
        if insp.has_table("exercise"):
            cols = {c["name"] for c in insp.get_columns("exercise")}
            if "rm_source_exercise_id" not in cols:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE exercise "
                            "ADD COLUMN rm_source_exercise_id INTEGER"
                        )
                    )

        # "user" é palavra reservada no Postgres → precisa de aspas.
        if insp.has_table("user"):
            user_cols = {c["name"] for c in insp.get_columns("user")}
            if "must_change_password" not in user_cols:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            'ALTER TABLE "user" '
                            "ADD COLUMN must_change_password BOOLEAN "
                            "NOT NULL DEFAULT FALSE"
                        )
                    )
    except Exception as exc:  # noqa: BLE001 — não derruba o startup por isso
        print(f"[db] _ensure_columns falhou (ignorado): {exc}")


def create_db_and_tables() -> None:
    """Cria todas as tabelas registradas em SQLModel.metadata."""
    SQLModel.metadata.create_all(engine)
    _ensure_columns()
