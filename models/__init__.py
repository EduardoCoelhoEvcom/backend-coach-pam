"""Pacote de modelos SQLModel.

Importar daqui garante que SQLModel.metadata.create_all veja todas as tabelas.
"""
from .coaching import (
    LIBRARY_KINDS,
    MOBILITY_JOINTS,
    WARMUP_CATEGORIES,
    CoachNote,
    InitialDiagnosis,
    MobilityCompletion,
    MobilityItem,
    MobilityLibraryItem,
    TrainingGoal,
)
from .exercise import Exercise, ExerciseCategory, ExerciseType
from .feedback import AthletePlan, VideoCorrection, VideoSubmission, WeeklyCheckin
from .payment import CoachPaymentSettings, Payment
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
    "WeeklyCheckin",
    "VideoSubmission",
    "VideoCorrection",
    "AthletePlan",
    "MobilityItem",
    "MobilityLibraryItem",
    "MOBILITY_JOINTS",
    "WARMUP_CATEGORIES",
    "LIBRARY_KINDS",
    "MobilityCompletion",
    "InitialDiagnosis",
    "TrainingGoal",
    "CoachNote",
    "CoachPaymentSettings",
    "Payment",
]
