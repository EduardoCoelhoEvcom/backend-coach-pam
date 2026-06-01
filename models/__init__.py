"""Pacote de modelos SQLModel.

Importar daqui garante que SQLModel.metadata.create_all veja todas as tabelas.
"""
from .exercise import Exercise, ExerciseCategory, ExerciseType
from .refresh_token import RefreshToken
from .rm_history import AthleteExerciseRMHistory
from .training import TrainingDayCompletion, TrainingSetExecution, TrainingSheet
from .user import User, get_user_by_email

__all__ = [
    "User",
    "get_user_by_email",
    "AthleteExerciseRMHistory",
    "TrainingSheet",
    "TrainingDayCompletion",
    "TrainingSetExecution",
    "Exercise",
    "ExerciseCategory",
    "ExerciseType",
    "RefreshToken",
]
