"""Modelo RefreshToken — armazena hash de refresh tokens longos.

Estratégia:
  - O token em si é um string aleatório (secrets.token_urlsafe(32)).
  - O backend NUNCA guarda o token plain — só o SHA256 (`token_hash`).
  - Quando o cliente envia o refresh em /auth/refresh, o backend hasha o
    valor recebido e busca pelo hash. Token rotation: o token antigo é
    revogado e um novo é emitido a cada refresh.
  - Logout marca `revoked_at` no token, sem deletar a linha (auditoria).
"""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_token"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    token_hash: str = Field(index=True, unique=True)
    expires_at: datetime
    revoked_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utc_now)
