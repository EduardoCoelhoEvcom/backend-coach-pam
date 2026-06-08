"""Model User + helper de busca por email."""
from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import Field, Session, SQLModel, select


def _utc_now() -> datetime:
    """Helper local pra default_factory — substitui datetime.utcnow (deprecated)."""
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(index=True, unique=True)
    password_hash: str
    role: str
    status_pagamento: str = "ok"
    vencimento: Optional[date] = None
    created_at: datetime = Field(default_factory=_utc_now)
    # True quando a senha atual é temporária (gerada no "esqueci a senha").
    # O app força a troca no próximo login enquanto isto estiver True.
    must_change_password: bool = Field(default=False)


def get_user_by_email(email: str, session: Session) -> Optional[User]:
    """Busca usuário por email. Retorna None se não existir."""
    statement = select(User).where(User.email == email)
    return session.exec(statement).first()
