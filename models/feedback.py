"""Models de acompanhamento: check-in semanal, vídeos/correções e plano do atleta.

Todas são tabelas NOVAS, então `SQLModel.metadata.create_all` cria sozinho no
deploy (não precisa de ALTER em `_ensure_columns`).
"""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Column, Index, UniqueConstraint
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WeeklyCheckin(SQLModel, table=True):
    """Check-in que o atleta responde na segunda (um por semana).

    `kind`:
      - "inicio_mes": semana 1 / virada de mês (pergunta sobre RM novo etc.)
      - "semanal": semanas 2 a 4
    `answers` guarda as respostas como {pergunta_id: valor} — o app decide as
    perguntas; o backend só deriva os sinais que a coach filtra (dor, atenção).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    athlete_id: int = Field(foreign_key="user.id", index=True)
    coach_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    week_start: date = Field(index=True)  # segunda-feira da semana
    kind: str = "semanal"
    answers: dict = Field(default_factory=dict, sa_column=Column(JSON))
    has_pain: bool = False
    pain_note: Optional[str] = None
    needs_attention: bool = False
    athlete_note: Optional[str] = None
    coach_seen_at: Optional[datetime] = None
    coach_reply: Optional[str] = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    __table_args__ = (
        UniqueConstraint("athlete_id", "week_start", name="uq_checkin_athlete_week"),
    )


class VideoSubmission(SQLModel, table=True):
    """Vídeo de um exercício enviado pelo atleta para a coach corrigir."""
    id: Optional[int] = Field(default=None, primary_key=True)
    athlete_id: int = Field(foreign_key="user.id", index=True)
    coach_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    training_sheet_id: Optional[int] = Field(default=None, index=True)
    week_number: Optional[int] = None
    day: Optional[str] = None
    exercise_name: str
    video_url: str
    athlete_note: Optional[str] = None
    # Para o "antes e depois": vídeo novo gravado em cima de uma correção.
    compare_to_id: Optional[int] = Field(default=None, foreign_key="videosubmission.id")
    status: str = Field(default="pendente", index=True)  # pendente | corrigido
    corrected_at: Optional[datetime] = None
    # Quando o atleta tocou em "Entendi, vou aplicar hoje".
    acknowledged_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utc_now)

    __table_args__ = (
        Index("ix_video_coach_status", "coach_id", "status", "created_at"),
    )


class VideoCorrection(SQLModel, table=True):
    """Um apontamento da coach num vídeo (pode haver vários por vídeo)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    submission_id: int = Field(foreign_key="videosubmission.id", index=True)
    title: str  # ex.: "Cotovelo travado antes de sentar"
    detail: Optional[str] = None
    timestamp_sec: Optional[float] = None  # "Ver no vídeo · 0:04"
    audio_url: Optional[str] = None  # "Ouvir · 0:18"
    audio_duration_sec: Optional[float] = None
    is_focus: bool = False  # selo FOCO
    # Desenho da coach sobre o quadro pausado: lista de formas com coordenadas
    # de 0 a 1 em relação ao vídeo, ex. {"t": "line", "c": "#FF4D4D", "p": [[x,y],[x,y]]}.
    drawing: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=_utc_now)


class AthletePlan(SQLModel, table=True):
    """Plano contratado pelo atleta (aparece na aba "Eu")."""
    id: Optional[int] = Field(default=None, primary_key=True)
    athlete_id: int = Field(foreign_key="user.id", index=True, unique=True)
    plan_name: str  # ex.: "Experience" | "Mês avulso"
    months_total: Optional[int] = None  # 6 no Experience; None no avulso
    monthly_price: Optional[float] = None
    show_price_to_athlete: bool = True
    start_date: date = Field(default_factory=date.today)
    notes: Optional[str] = None
    updated_at: datetime = Field(default_factory=_utc_now)
