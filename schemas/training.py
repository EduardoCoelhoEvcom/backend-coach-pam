"""Schemas relacionados a planilhas de treino, execuções e progresso."""
from datetime import date, datetime
from typing import List, Optional

from sqlmodel import SQLModel


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
