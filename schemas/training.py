"""Schemas relacionados a planilhas de treino, execuções e progresso."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import field_validator
from sqlmodel import SQLModel


def _coerce_optional_float(v):
    """Aceita número, string vazia, string com vírgula ou lixo.

    Campo em branco ("") ou texto não-numérico vira None em vez de derrubar
    a requisição com erro 422. Aceita também vírgula decimal (110,5).
    """
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip().replace(",", ".")
        if v == "":
            return None
        try:
            return float(v)
        except ValueError:
            return None
    return v


class TrainingSheetCreate(SQLModel):
    athlete_id: int
    title: str
    weeks: int = 4
    same_weeks: bool = True
    plan: Optional[dict] = None
    start_date: date


class TrainingSheetRead(SQLModel):
    id: int
    athlete_id: int
    coach_id: int
    title: str
    weeks: int
    same_weeks: bool
    created_at: datetime
    start_date: date
    end_date: date


class TrainingSheetDetail(SQLModel):
    id: int
    title: str
    athlete_id: int
    coach_id: int
    weeks: int
    same_weeks: bool
    plan: dict
    start_date: date
    end_date: date
    created_at: datetime


class TrainingPlanUpdate(SQLModel):
    plan: dict


class TrainingSheetDatesUpdate(SQLModel):
    start_date: date


class DuplicateTrainingSheetRequest(SQLModel):
    target_athlete_id: int
    start_date: date


# ----- Execuções -----
class SetExecutionIn(SQLModel):
    exercise_name: str
    series_index: int
    prescribed_percent: Optional[float] = None
    prescribed_kg: Optional[float] = None
    used_kg: Optional[float] = None

    # Campo em branco / texto / vírgula não derruba mais o salvar do treino.
    @field_validator(
        "prescribed_percent", "prescribed_kg", "used_kg", mode="before"
    )
    @classmethod
    def _empty_to_none(cls, v):
        return _coerce_optional_float(v)


class SetExecutionOut(SQLModel):
    id: int
    athlete_id: int
    training_sheet_id: int
    week_number: int
    day: str
    date_completed: date
    exercise_name: str
    series_index: int
    prescribed_percent: Optional[float] = None
    prescribed_kg: Optional[float] = None
    used_kg: Optional[float] = None
    diff_kg: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class CompleteDayRequest(SQLModel):
    training_sheet_id: int
    week_number: int
    day: str
    sets: Optional[List[SetExecutionIn]] = None


class SaveDayExecutionRequest(SQLModel):
    training_sheet_id: int
    week_number: int
    day: str
    sets: List[SetExecutionIn]


class AthleteProgressResponse(SQLModel):
    total_completed_days: int
    completed_today: bool
    streak_days: int
