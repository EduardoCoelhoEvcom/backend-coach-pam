"""Rotas de catálogo de exercícios.

Inclui:
  - GET /athlete/exercise-library
  - GET /coach/exercise-library
  - POST /coach/exercise-categories
  - POST /coach/exercises
  - PATCH /coach/exercises/{id}
  - DELETE /coach/exercises/{id}
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session, SQLModel, select

from db import get_session
from models import Exercise, ExerciseCategory, TrainingSheet, User
from security import require_role

router = APIRouter(tags=["exercises"])


# ---------- Schemas ----------
class ExerciseCategoryCreate(SQLModel):
    name: str
    type: str  # "lpo" | "accessory"
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None


class ExerciseCreate(SQLModel):
    category_id: int
    name: str
    rm_source_default: Optional[str] = None
    # null = RM próprio; senão, puxa o RM de outro movimento (id do exercício).
    rm_source_exercise_id: Optional[int] = None
    allow_weight_default: bool = True


class ExercisePatch(SQLModel):
    name: Optional[str] = None
    category_id: Optional[int] = None
    rm_source_default: Optional[str] = None
    rm_source_exercise_id: Optional[int] = None
    allow_weight_default: Optional[bool] = None
    is_active: Optional[bool] = None


class ExerciseCategoryRead(SQLModel):
    id: int
    coach_id: Optional[int]
    name: str
    sort_order: int


class ExerciseRead(SQLModel):
    id: int
    name: str
    rm_source_default: Optional[str] = None
    rm_source_exercise_id: Optional[int] = None
    allow_weight_default: bool = True
    is_active: bool = True
    coach_id: Optional[int] = None
    category_id: int


class ExerciseCategoryNode(SQLModel):
    id: int
    name: str
    type: str  # "lpo" | "accessory"
    coach_id: Optional[int] = None
    parent_id: Optional[int] = None
    sort_order: int = 0
    is_active: bool = True

    subcategories: List["ExerciseCategoryNode"] = []
    exercises: List[ExerciseRead] = []


ExerciseCategoryNode.model_rebuild()


# ---------- Helpers ----------
def _build_category_tree(
    cats: List[ExerciseCategory],
    exs: List[Exercise],
) -> List[ExerciseCategoryNode]:
    """Monta a árvore (categorias raiz + subcategorias + exercícios)."""
    nodes: dict[int, ExerciseCategoryNode] = {}
    for c in cats:
        nodes[c.id] = ExerciseCategoryNode(
            id=c.id,
            name=c.name,
            type=c.type,
            coach_id=c.coach_id,
            parent_id=c.parent_id,
            sort_order=c.sort_order,
            is_active=c.is_active,
            subcategories=[],
            exercises=[],
        )

    for e in exs:
        if e.category_id not in nodes:
            continue
        nodes[e.category_id].exercises.append(
            ExerciseRead(
                id=e.id,
                name=e.name,
                rm_source_default=e.rm_source_default,
                rm_source_exercise_id=e.rm_source_exercise_id,
                allow_weight_default=e.allow_weight_default,
                is_active=e.is_active,
                coach_id=e.coach_id,
                category_id=e.category_id,
            )
        )

    roots: list[ExerciseCategoryNode] = []
    for n in nodes.values():
        if n.parent_id and n.parent_id in nodes:
            nodes[n.parent_id].subcategories.append(n)
        else:
            roots.append(n)

    def sort_tree(arr: list[ExerciseCategoryNode]):
        arr.sort(key=lambda x: (x.sort_order or 0, x.name.lower()))
        for a in arr:
            sort_tree(a.subcategories)

    sort_tree(roots)
    return roots


def _validate_rm_source_exercise(
    session: Session,
    coach: User,
    rm_source_exercise_id: Optional[int],
    self_id: Optional[int] = None,
) -> None:
    """Garante que o movimento referenciado existe, é acessível e não é ele mesmo."""
    if rm_source_exercise_id is None:
        return
    if self_id is not None and rm_source_exercise_id == self_id:
        raise HTTPException(
            status_code=400,
            detail="Um movimento não pode puxar o RM de si mesmo.",
        )
    ref = session.get(Exercise, rm_source_exercise_id)
    if not ref or not ref.is_active:
        raise HTTPException(
            status_code=404, detail="Movimento de referência não encontrado."
        )
    if ref.coach_id is not None and ref.coach_id != coach.id:
        raise HTTPException(
            status_code=403, detail="Sem acesso ao movimento de referência."
        )


# ---------- Routes ----------
@router.get("/athlete/exercise-library", response_model=List[ExerciseCategoryNode])
def athlete_exercise_library(
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    # coaches que treinam esse atleta (via planilhas)
    coach_ids = session.exec(
        select(func.distinct(TrainingSheet.coach_id))
        .where(TrainingSheet.athlete_id == athlete.id)
    ).all()
    coach_ids = [cid for cid in coach_ids if cid is not None]

    # categorias visíveis: globais + das coaches desse atleta
    cats = session.exec(
        select(ExerciseCategory).where(
            ExerciseCategory.is_active == True,
            (ExerciseCategory.coach_id == None) |
            (ExerciseCategory.coach_id.in_(coach_ids) if coach_ids else False)
        ).order_by(ExerciseCategory.sort_order.asc(), ExerciseCategory.name.asc())
    ).all()

    cat_ids = [c.id for c in cats]

    exs = session.exec(
        select(Exercise).where(
            Exercise.is_active == True,
            Exercise.category_id.in_(cat_ids),
            (Exercise.coach_id == None) |
            (Exercise.coach_id.in_(coach_ids) if coach_ids else False)
        ).order_by(Exercise.name.asc())
    ).all()

    return _build_category_tree(cats, exs)


@router.get("/coach/exercise-library", response_model=List[ExerciseCategoryNode])
def coach_exercise_library(
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    # categorias globais + do coach
    cats = session.exec(
        select(ExerciseCategory).where(
            ExerciseCategory.is_active == True,
            (ExerciseCategory.coach_id == None) | (ExerciseCategory.coach_id == coach.id),
        ).order_by(ExerciseCategory.sort_order.asc(), ExerciseCategory.name.asc())
    ).all()

    cat_ids = [c.id for c in cats]
    exs = session.exec(
        select(Exercise).where(
            Exercise.is_active == True,
            Exercise.category_id.in_(cat_ids),
            (Exercise.coach_id == None) | (Exercise.coach_id == coach.id),
        ).order_by(Exercise.name.asc())
    ).all()

    return _build_category_tree(cats, exs)


@router.post("/coach/exercise-categories", response_model=ExerciseCategoryNode)
def coach_create_category(
    payload: ExerciseCategoryCreate,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome é obrigatório.")
    if payload.type not in ("lpo", "accessory"):
        raise HTTPException(status_code=400, detail="type inválido.")

    if payload.parent_id is not None:
        parent = session.get(ExerciseCategory, payload.parent_id)
        if not parent or not parent.is_active:
            raise HTTPException(status_code=404, detail="Categoria pai não encontrada.")
        if not (parent.coach_id is None or parent.coach_id == coach.id):
            raise HTTPException(status_code=403, detail="Sem acesso à categoria pai.")
        if parent.type != payload.type:
            raise HTTPException(
                status_code=400,
                detail="Subcategoria deve ter o mesmo type da categoria pai.",
            )

    sort_order = int(payload.sort_order) if payload.sort_order is not None else 0

    cat = ExerciseCategory(
        coach_id=coach.id,
        type=payload.type,
        name=name,
        parent_id=payload.parent_id,
        sort_order=sort_order,
        is_active=True,
    )
    session.add(cat)
    session.commit()
    session.refresh(cat)

    return ExerciseCategoryNode(
        id=cat.id,
        name=cat.name,
        type=cat.type,
        coach_id=cat.coach_id,
        parent_id=cat.parent_id,
        sort_order=cat.sort_order,
        is_active=cat.is_active,
        subcategories=[],
        exercises=[],
    )


@router.post("/coach/exercises")
def coach_create_exercise(
    payload: ExerciseCreate,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome do exercício é obrigatório.")

    cat = session.get(ExerciseCategory, payload.category_id)
    if not cat or not cat.is_active:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")

    if cat.coach_id is not None and cat.coach_id != coach.id:
        raise HTTPException(status_code=403, detail="Você não pode usar essa categoria.")

    # RM puxado de outro movimento só faz sentido para LPO.
    rm_source_exercise_id = (
        payload.rm_source_exercise_id if cat.type == "lpo" else None
    )
    _validate_rm_source_exercise(session, coach, rm_source_exercise_id)

    now = datetime.now(timezone.utc)

    ex = Exercise(
        coach_id=coach.id,
        category_id=payload.category_id,
        name=name,
        type=cat.type,
        rm_source_default=payload.rm_source_default if cat.type == "lpo" else None,
        rm_source_exercise_id=rm_source_exercise_id,
        allow_weight_default=payload.allow_weight_default,
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    session.add(ex)
    session.commit()
    session.refresh(ex)

    return ExerciseRead(
        id=ex.id,
        name=ex.name,
        rm_source_default=ex.rm_source_default,
        rm_source_exercise_id=ex.rm_source_exercise_id,
        allow_weight_default=ex.allow_weight_default,
        is_active=ex.is_active,
        coach_id=ex.coach_id,
        category_id=ex.category_id,
    )


@router.patch("/coach/exercises/{exercise_id}", response_model=ExerciseRead)
def coach_patch_exercise(
    exercise_id: int,
    payload: ExercisePatch,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    ex = session.get(Exercise, exercise_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Exercício não encontrado.")
    if ex.coach_id != coach.id:
        raise HTTPException(
            status_code=403,
            detail="Você só pode editar exercícios do seu coach.",
        )

    data = payload.dict(exclude_unset=True)

    if "category_id" in data:
        cat = session.get(ExerciseCategory, data["category_id"])
        if not cat or not cat.is_active:
            raise HTTPException(status_code=404, detail="Categoria não encontrada.")
        if not (cat.coach_id is None or cat.coach_id == coach.id):
            raise HTTPException(status_code=403, detail="Sem acesso à categoria.")
        ex.category_id = data["category_id"]

    if "name" in data:
        ex.name = (data["name"] or "").strip()

    if "rm_source_default" in data:
        ex.rm_source_default = data["rm_source_default"]

    if "rm_source_exercise_id" in data:
        _validate_rm_source_exercise(
            session, coach, data["rm_source_exercise_id"], self_id=ex.id
        )
        ex.rm_source_exercise_id = data["rm_source_exercise_id"]

    if "allow_weight_default" in data:
        ex.allow_weight_default = bool(data["allow_weight_default"])

    if "is_active" in data:
        ex.is_active = bool(data["is_active"])

    ex.updated_at = datetime.now(timezone.utc)

    session.add(ex)
    session.commit()
    session.refresh(ex)

    return ExerciseRead(
        id=ex.id,
        name=ex.name,
        rm_source_default=ex.rm_source_default,
        rm_source_exercise_id=ex.rm_source_exercise_id,
        allow_weight_default=ex.allow_weight_default,
        is_active=ex.is_active,
        coach_id=ex.coach_id,
        category_id=ex.category_id,
    )


@router.delete("/coach/exercises/{exercise_id}")
def coach_archive_exercise(
    exercise_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    ex = session.get(Exercise, exercise_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Exercício não encontrado.")
    if ex.coach_id != coach.id:
        raise HTTPException(
            status_code=403,
            detail="Você só pode arquivar exercícios do seu próprio catálogo.",
        )

    ex.is_active = False
    ex.updated_at = datetime.now(timezone.utc)
    session.add(ex)
    session.commit()
    return {"ok": True}
