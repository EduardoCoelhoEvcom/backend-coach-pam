"""Models de exercícios e categorias da biblioteca."""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExerciseType(str, Enum):
    lpo = "lpo"
    accessory = "accessory"


class ExerciseCategory(SQLModel, table=True):
    """Categoria/subcategoria de exercícios.

    coach_id == None significa categoria global (visível pra todos os coaches).
    parent_id permite subcategorias.
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    # null = global, senão pertence a um coach
    coach_id: Optional[int] = Field(default=None, index=True)

    # "lpo" ou "accessory"
    type: str = Field(index=True)

    name: str
    sort_order: int = 0

    parent_id: Optional[int] = Field(
        default=None,
        foreign_key="exercisecategory.id",
        index=True,
    )

    is_active: bool = True
    created_at: datetime = Field(default_factory=_utc_now)


class Exercise(SQLModel, table=True):
    """Exercício individual dentro de uma categoria.

    coach_id == None = exercício global. Caso contrário, só o coach que
    criou consegue enxergar/editar.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    coach_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    category_id: int = Field(foreign_key="exercisecategory.id", index=True)

    name: str
    type: str  # "lpo" | "accessory"
    rm_source_default: Optional[str] = None

    # Quando definido, este movimento "puxa" o RM de outro movimento.
    # null = usa o RM próprio (registrado para este exercise_id).
    rm_source_exercise_id: Optional[int] = Field(
        default=None,
        foreign_key="exercise.id",
        index=True,
    )

    allow_weight_default: bool = True
    is_active: bool = True

    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
