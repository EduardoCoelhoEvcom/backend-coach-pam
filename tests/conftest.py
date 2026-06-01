"""Pytest fixtures pro backend Coach PAM.

Estratégia:
  - Cada teste usa um banco SQLite em arquivo temporário (criado/dropado
    por teste). Isolamento total entre testes.
  - O FastAPI tem `get_session` sobrescrito pra usar nossa engine de teste.
  - O seed inicial NÃO roda — fixtures criam usuários sob demanda.
  - Fixtures `coach_client` / `athlete_client` retornam TestClients já
    autenticados com Bearer token.
"""
from __future__ import annotations

import os
import tempfile
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# IMPORTANTE: importar models antes do app pra registrar todas as tabelas
import models  # noqa: F401
from db import get_session
from main import app
from models import User
from rate_limit import limiter
from security import get_password_hash, create_access_token
from datetime import timedelta


# Desabilita rate limiting em testes — caso contrário, executar a suite
# várias vezes seguidas estoura o limite de 5 registers/hora por IP.
limiter.enabled = False


# ============================================================
# Engine de teste — arquivo temp, isolado por teste
# ============================================================
@pytest.fixture()
def db_path() -> Generator[str, None, None]:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="coachpam_test_")
    os.close(fd)
    try:
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture()
def engine(db_path):
    """Engine SQLite em arquivo temp. Tabelas criadas a cada teste."""
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


@pytest.fixture()
def session(engine) -> Generator[Session, None, None]:
    """Sessão SQLModel pra criar fixtures (usuários, planilhas, etc)."""
    with Session(engine) as s:
        yield s


# ============================================================
# Override do get_session do FastAPI pra usar nossa engine
# ============================================================
@pytest.fixture()
def _override_get_session(engine) -> Generator[None, None, None]:
    """Override compartilhado entre todos os clients no teste.
    Aplica uma vez por teste; é seguro pedir múltiplos clients depois."""
    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    try:
        yield
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def client(_override_get_session) -> Generator[TestClient, None, None]:
    """TestClient sem auth."""
    with TestClient(app) as c:
        yield c


# ============================================================
# Usuários de teste
# ============================================================
def _make_user(session: Session, *, name: str, email: str, role: str) -> User:
    user = User(
        name=name,
        email=email,
        password_hash=get_password_hash("test123"),
        role=role,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture()
def coach_user(session) -> User:
    return _make_user(session, name="Coach Test", email="coach@test.com", role="coach")


@pytest.fixture()
def athlete_user(session) -> User:
    return _make_user(session, name="Atleta Test", email="atleta@test.com", role="athlete")


def _token_for(user: User) -> str:
    return create_access_token(
        data={"sub": user.id, "role": user.role},
        expires_delta=timedelta(minutes=60),
    )


@pytest.fixture()
def coach_token(coach_user) -> str:
    return _token_for(coach_user)


@pytest.fixture()
def athlete_token(athlete_user) -> str:
    return _token_for(athlete_user)


@pytest.fixture()
def coach_client(_override_get_session, coach_token) -> Generator[TestClient, None, None]:
    """TestClient autenticado como coach.

    Importante: cria SEU PRÓPRIO TestClient (não compartilha com `client` ou
    `athlete_client`). Sem isso, dois clients no mesmo teste sobrescreveriam
    o header de auth um do outro.
    """
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {coach_token}"
        yield c


@pytest.fixture()
def athlete_client(_override_get_session, athlete_token) -> Generator[TestClient, None, None]:
    """TestClient autenticado como atleta. Instância isolada."""
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {athlete_token}"
        yield c
