from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Index


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AthleteExerciseRMHistory(SQLModel, table=True):
    __tablename__ = "athlete_exercise_rm_history"

    id: Optional[int] = Field(default=None, primary_key=True)

    athlete_id: int = Field(index=True)
    exercise_id: int = Field(index=True)

    rm_value: float  # pode ser float ou int
    effective_date: datetime = Field(default_factory=_utc_now, index=True)

    source: Optional[str] = Field(default="coach")  # opcional
    note: Optional[str] = Field(default=None)

# índice composto (ajuda MUITO pra buscar o último rápido)
Index(
    "ix_rm_history_athlete_exercise_date",
    AthleteExerciseRMHistory.athlete_id,
    AthleteExerciseRMHistory.exercise_id,
    AthleteExerciseRMHistory.effective_date,
)