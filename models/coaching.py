"""Models de mobilidade por atleta, diagnóstico inicial e objetivo/focos.

Todas são tabelas NOVAS, então `SQLModel.metadata.create_all` cria sozinho no
deploy (não precisa de ALTER em `_ensure_columns`).
"""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MobilityItem(SQLModel, table=True):
    """Exercício de mobilidade que a coach cadastra para um atleta."""
    id: Optional[int] = Field(default=None, primary_key=True)
    athlete_id: int = Field(foreign_key="user.id", index=True)
    coach_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    name: str  # ex.: "Mobilidade de tornozelo na parede"
    dose: Optional[str] = None  # séries/tempo, ex.: "2x10/10" ou "2x30\""
    video_url: Optional[str] = None  # link do YouTube
    position: int = 0  # ordem na lista
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class MobilityCompletion(SQLModel, table=True):
    """O atleta marcou um item de mobilidade como feito num dia."""
    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="mobilityitem.id", index=True)
    athlete_id: int = Field(foreign_key="user.id", index=True)
    done_on: date = Field(index=True)
    created_at: datetime = Field(default_factory=_utc_now)

    __table_args__ = (
        UniqueConstraint("item_id", "done_on", name="uq_mobility_item_day"),
    )


class InitialDiagnosis(SQLModel, table=True):
    """Diagnóstico inicial que a coach faz do atleta (aba "Plano")."""
    id: Optional[int] = Field(default=None, primary_key=True)
    athlete_id: int = Field(foreign_key="user.id", index=True, unique=True)
    coach_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    strengths: Optional[str] = None  # "Pontos fortes"
    adjustments: Optional[str] = None  # "O que vamos ajustar"
    mobility: Optional[str] = None  # "Mobilidade"
    pdf_url: Optional[str] = None  # "Ver diagnóstico completo (PDF)" — por enquanto URL
    diagnosed_on: date = Field(default_factory=date.today)  # "Feito pela Coach Pâm em 06/10"
    updated_at: datetime = Field(default_factory=_utc_now)


class TrainingGoal(SQLModel, table=True):
    """Objetivo e focos do atleta (aba "Plano"), definidos pela coach."""
    id: Optional[int] = Field(default=None, primary_key=True)
    athlete_id: int = Field(foreign_key="user.id", index=True, unique=True)
    coach_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    objective: Optional[str] = None  # "Competir pela primeira vez no LPO"
    target: Optional[str] = None  # "Meta: [competição] · [mês/ano]"
    # Fases por mês, na ordem: ["Base técnica", "Força", "Específico pra prova"]
    phases: list = Field(default_factory=list, sa_column=Column(JSON))
    # Focos técnicos: [{"title": "...", "detail": "..."}]
    focuses: list = Field(default_factory=list, sa_column=Column(JSON))
    coach_note: Optional[str] = None  # "Recado da coach"
    updated_at: datetime = Field(default_factory=_utc_now)


class CoachNote(SQLModel, table=True):
    """Notas privadas da coach sobre um atleta (só a coach vê)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    athlete_id: int = Field(foreign_key="user.id", index=True, unique=True)
    coach_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    text: str = ""
    updated_at: datetime = Field(default_factory=_utc_now)
