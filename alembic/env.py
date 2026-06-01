"""Alembic environment.

Configurado para o projeto Coach PAM:
  - URL do banco vem de config.DATABASE_URL (que lê do .env).
  - target_metadata = SQLModel.metadata, alimentada pelo import dos models.
  - autogenerate funciona porque importamos todos os models antes.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Garante que o root do projeto está no path para imports relativos.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- Imports do projeto ----
# Importar config carrega o .env e expõe DATABASE_URL.
from config import DATABASE_URL  # noqa: E402

# Importar models registra todas as tabelas em SQLModel.metadata.
# É CRÍTICO importar tudo aqui — sem isso, autogenerate não vê as tabelas
# e geraria migration "vazia" ou "drop everything".
import models  # noqa: F401, E402

# ---- Config do Alembic ----
config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Roda migrations gerando SQL sem conectar (modo --sql)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Renderiza tipos SQLModel/SQLAlchemy direito nos arquivos de migration.
        render_as_batch=DATABASE_URL.startswith("sqlite"),
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Roda migrations conectando ao banco."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # render_as_batch é necessário pro SQLite suportar ALTER TABLE
            # (ele não tem suporte nativo a vários ALTER que outros bancos têm).
            render_as_batch=DATABASE_URL.startswith("sqlite"),
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
