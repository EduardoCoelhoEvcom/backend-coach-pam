"""Schemas relacionados a 1RM (Repetition Maximum) por exercício."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel
from sqlmodel import SQLModel


class ExerciseRMCurrentItem(BaseModel):
    """RM atual + metadados do exercício, usado em listas no app."""
    exercise_id: int
    exercise_name: str
    category_id: int
    type: str  # "lpo" | "accessory"
    rm_value: Optional[float] = None
    effective_date: Optional[datetime] = None


class ExerciseRMSetBody(BaseModel):
    """Body para coach setar RM de um atleta em um exercício específico."""
    exercise_id: int
    rm_value: float
    effective_date: Optional[datetime] = None


class SetRMBody(BaseModel):
    exercise_id: int
    rm_value: float
    effective_date: Optional[datetime] = None


class SetRMBatchItem(BaseModel):
    exercise_id: int
    rm_value: float


class SetRMBatchBody(BaseModel):
    items: List[SetRMBatchItem]
    effective_date: Optional[datetime] = None


class SetRMItem(BaseModel):
    exercise_id: int
    rm_value: float
    effective_date: Optional[datetime] = None


class SetRMBatch(BaseModel):
    items: List[SetRMItem]


class SetExerciseRMBody(BaseModel):
    exercise_id: int
    rm_value: float
    effective_date: Optional[datetime] = None


class SetMyExerciseRMBody(BaseModel):
    exercise_id: int
    rm_value: float
    effective_date: Optional[datetime] = None
