"""Pagamento da mensalidade: dados de cobrança da coach e comprovantes do atleta.

Tabelas NOVAS (create_all cria sozinho). As colunas novas em "user"
(due_day, payment_mode, payment_link) ficam em `_ensure_columns`.
"""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CoachPaymentSettings(SQLModel, table=True):
    """Como a coach recebe: chave Pix (pro "copia e cola") e links de cartão do Asaas."""
    id: Optional[int] = Field(default=None, primary_key=True)
    coach_id: int = Field(foreign_key="user.id", index=True, unique=True)
    pix_key: Optional[str] = None
    # Nome e cidade de quem recebe: o Pix copia e cola exige os dois.
    pix_name: Optional[str] = None
    pix_city: Optional[str] = None
    # Link de cartão por plano: {"experience-3": "https://www.asaas.com/c/...", ...}
    card_links: dict = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=_utc_now)


class Payment(SQLModel, table=True):
    """Um pagamento de mensalidade.

    status: "enviado" (atleta mandou o comprovante, a coach ainda não viu),
    "confirmado" (a coach tocou em "Recebi") ou "recusado" (a coach pediu outro).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    athlete_id: int = Field(foreign_key="user.id", index=True)
    coach_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    due_date: Optional[date] = None  # o vencimento que este pagamento quita
    amount: Optional[float] = None
    method: str = "pix"  # pix | cartao | outro
    receipt_url: Optional[str] = None
    status: str = Field(default="enviado", index=True)
    coach_note: Optional[str] = None  # motivo, quando recusa
    created_at: datetime = Field(default_factory=_utc_now)
    reviewed_at: Optional[datetime] = None
