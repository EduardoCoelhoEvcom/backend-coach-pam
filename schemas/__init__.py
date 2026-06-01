"""Pacote de schemas compartilhados (Pydantic / SQLModel non-table).

Schemas específicos de um único router permanecem dentro do próprio router.
Aqui ficam apenas os que são consumidos por mais de um lugar.
"""
from .rm import (
    ExerciseRMCurrentItem,
    ExerciseRMSetBody,
    SetExerciseRMBody,
    SetMyExerciseRMBody,
    SetRMBatch,
    SetRMBatchBody,
    SetRMBatchItem,
    SetRMBody,
    SetRMItem,
)
from .training import (
    AthleteProgressResponse,
    CompleteDayRequest,
    DuplicateTrainingSheetRequest,
    SaveDayExecutionRequest,
    SetExecutionIn,
    SetExecutionOut,
    TrainingPlanUpdate,
    TrainingSheetCreate,
    TrainingSheetDatesUpdate,
    TrainingSheetDetail,
    TrainingSheetRead,
)

__all__ = [
    # rm
    "ExerciseRMCurrentItem",
    "ExerciseRMSetBody",
    "SetRMBody",
    "SetRMBatchItem",
    "SetRMBatchBody",
    "SetRMItem",
    "SetRMBatch",
    "SetExerciseRMBody",
    "SetMyExerciseRMBody",
    # training
    "TrainingSheetCreate",
    "TrainingSheetRead",
    "TrainingSheetDetail",
    "TrainingPlanUpdate",
    "TrainingSheetDatesUpdate",
    "DuplicateTrainingSheetRequest",
    "SetExecutionIn",
    "SetExecutionOut",
    "CompleteDayRequest",
    "SaveDayExecutionRequest",
    "AthleteProgressResponse",
]
