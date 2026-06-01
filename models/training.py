"""Models de treino: planilhas, dias concluídos e execuções de séries."""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Column, Index
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TrainingSheet(SQLModel, table=True):
    """Planilha de treino criada pelo coach para um atleta."""
    id: Optional[int] = Field(default=None, primary_key=True)
    # Indexes: athlete_id (lookup do atleta) e coach_id (lookup do coach)
    athlete_id: int = Field(foreign_key="user.id", index=True)
    coach_id: int = Field(foreign_key="user.id", index=True)
    title: str
    weeks: int = 4
    same_weeks: bool = True
    plan: dict = Field(default_factory=dict, sa_column=Column(JSON))
    start_date: date = Field(default_factory=date.today)
    end_date: date
    created_at: datetime = Field(default_factory=_utc_now)


class TrainingDayCompletion(SQLModel, table=True):
    """Marca de que o atleta concluiu um dia específico de uma semana."""
    id: Optional[int] = Field(default=None, primary_key=True)
    athlete_id: int = Field(index=True)
    training_sheet_id: int = Field(index=True)
    week_number: int
    day: str
    date_completed: date = Field(default_factory=date.today, index=True)
    created_at: datetime = Field(default_factory=_utc_now)

    # Índice composto: a query mais comum filtra por todos esses campos juntos
    # ao verificar idempotência de complete-day (cf. routers/athlete.py).
    __table_args__ = (
        Index(
            "ix_traincomp_athlete_sheet_day",
            "athlete_id", "training_sheet_id", "week_number", "day", "date_completed",
        ),
    )


class TrainingSetExecution(SQLModel, table=True):
    """Execução real de uma série (salva quando o atleta conclui o dia)."""
    id: Optional[int] = Field(default=None, primary_key=True)

    athlete_id: int = Field(index=True)
    training_sheet_id: int = Field(index=True)

    week_number: int
    day: str
    date_completed: date = Field(default_factory=date.today)

    exercise_name: str
    series_index: int

    prescribed_percent: Optional[float] = None
    prescribed_kg: Optional[float] = None
    used_kg: Optional[float] = None
    diff_kg: Optional[float] = None

    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    # Índice composto: cobre a query de listar execuções de um sheet
    # (routers/coach.py::coach_list_sheet_executions e
    # routers/athlete.py::athlete_list_sheet_executions),
    # que filtra por training_sheet_id e ordena por date_completed/week_number.
    __table_args__ = (
        Index(
            "ix_setexec_sheet_date",
            "training_sheet_id", "date_completed", "week_number",
        ),
        Index(
            "ix_setexec_athlete_sheet_day",
            "athlete_id", "training_sheet_id", "week_number", "day", "date_completed",
        ),
    )
