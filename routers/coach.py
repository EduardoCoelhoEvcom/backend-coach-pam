"""Rotas do coach.

Inclui:
  - /coach/athletes (GET, POST)
  - /coach/athletes/{athlete_id}/exercise-rms (GET, POST)
  - /coach/athletes/{athlete_id}/exercise-rms/current (GET)
  - /coach/athletes/{athlete_id}/exercise-rms/current/all (GET)
  - /coach/athletes/{athlete_id}/exercise-rms/history (GET)
  - /coach/dashboard (GET)
  - /coach/training-sheets (GET, POST)
  - /coach/training-sheets/{sheet_id} (GET)
  - /coach/training-sheets/{sheet_id}/dates (PATCH)
  - /coach/training-sheets/{sheet_id}/plan (PUT)
  - /coach/training-sheets/{sheet_id}/duplicate (POST)
  - /coach/training-sheets/{sheet_id}/executions (GET)
"""
import json
from datetime import date, datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import EmailStr
from sqlalchemy import desc, func
from sqlmodel import Session, SQLModel, select

from db import get_session
from models import (
    AthleteExerciseRMHistory,
    Exercise,
    TrainingDayCompletion,
    TrainingSetExecution,
    TrainingSheet,
    User,
)
from schemas import (
    DuplicateTrainingSheetRequest,
    ExerciseRMCurrentItem,
    ExerciseRMSetBody,
    SetExecutionOut,
    TrainingPlanUpdate,
    TrainingSheetCreate,
    TrainingSheetDatesUpdate,
    TrainingSheetDetail,
    TrainingSheetRead,
)
from security import get_password_hash, require_role
from services.training_plan import (
    build_default_plan,
    compute_end_date,
    normalize_plan_for_sheet,
)

router = APIRouter(tags=["coach"])


# ---------- Schemas locais ----------
class CoachDashboardResponse(SQLModel):
    athletes_total: int
    sheets_total: int
    executions_total: int
    executions_today: int
    days_completed_today: int
    days_completed_total: int


class UserRead(SQLModel):
    id: int
    name: str
    email: str


class AthleteCreate(SQLModel):
    name: str
    email: EmailStr
    password: str


class AthleteRead(SQLModel):
    id: int
    name: str
    email: str
    role: str


# ============================================================
# Atletas
# ============================================================
@router.get("/coach/athletes", response_model=List[UserRead])
def list_athletes(
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    stmt = select(User).where(User.role == "athlete")
    return session.exec(stmt).all()


@router.post("/coach/athletes", response_model=AthleteRead)
def create_athlete_for_coach(
    payload: AthleteCreate,
    session: Session = Depends(get_session),
    current_coach: User = Depends(require_role("coach")),
):
    from models import get_user_by_email
    existing = get_user_by_email(payload.email.strip().lower(), session)
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Já existe um usuário com esse e-mail.",
        )

    user = User(
        name=payload.name.strip(),
        email=payload.email.strip().lower(),
        password_hash=get_password_hash(payload.password),
        role="athlete",
        status_pagamento="ok",
        vencimento=date.today() + timedelta(days=30),
        coach_id=current_coach.id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    return AthleteRead(id=user.id, name=user.name, email=user.email, role=user.role)


# ============================================================
# RMs por atleta
# ============================================================
@router.post("/coach/athletes/{athlete_id}/exercise-rms")
def coach_set_exercise_rm(
    athlete_id: int,
    body: ExerciseRMSetBody,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    athlete = session.get(User, athlete_id)
    if not athlete or athlete.role != "athlete":
        raise HTTPException(status_code=404, detail="Atleta não encontrado.")

    ex = session.get(Exercise, body.exercise_id)
    if not ex or not ex.is_active:
        raise HTTPException(status_code=404, detail="Exercício não encontrado.")
    if ex.coach_id is not None and ex.coach_id != coach.id:
        raise HTTPException(status_code=403, detail="Sem acesso a este exercício.")

    eff = body.effective_date or datetime.now(timezone.utc)

    last = session.exec(
        select(AthleteExerciseRMHistory)
        .where(AthleteExerciseRMHistory.athlete_id == athlete_id)
        .where(AthleteExerciseRMHistory.exercise_id == body.exercise_id)
        .order_by(desc(AthleteExerciseRMHistory.effective_date))
        .limit(1)
    ).first()

    # anti-duplicação: mesmo valor + mesmo dia → não cria
    if last is not None:
        same_value = abs(float(last.rm_value) - float(body.rm_value)) < 1e-6
        same_day = last.effective_date.date() == eff.date()
        if same_value and same_day:
            return {
                "ok": True,
                "created": False,
                "reason": "same_value_same_day",
                "id": last.id,
            }

    row = AthleteExerciseRMHistory(
        athlete_id=athlete_id,
        exercise_id=body.exercise_id,
        rm_value=float(body.rm_value),
        effective_date=eff,
        source="coach",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"ok": True, "created": True, "id": row.id}


@router.get("/coach/athletes/{athlete_id}/exercise-rms/current")
def get_current_exercise_rm(
    athlete_id: int,
    exercise_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    stmt = (
        select(AthleteExerciseRMHistory)
        .where(AthleteExerciseRMHistory.athlete_id == athlete_id)
        .where(AthleteExerciseRMHistory.exercise_id == exercise_id)
        .order_by(desc(AthleteExerciseRMHistory.effective_date))
        .limit(1)
    )
    row = session.exec(stmt).first()
    return {"rm_value": row.rm_value if row else None}


@router.get("/coach/athletes/{athlete_id}/exercise-rms/current/all")
def get_current_all_exercise_rms(
    athlete_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    stmt = (
        select(AthleteExerciseRMHistory)
        .where(AthleteExerciseRMHistory.athlete_id == athlete_id)
        .order_by(desc(AthleteExerciseRMHistory.effective_date))
    )
    rows = session.exec(stmt).all()

    latest: dict[int, float] = {}
    for r in rows:
        if r.exercise_id not in latest:
            latest[r.exercise_id] = r.rm_value

    # Movimentos que puxam o RM de outro herdam o valor do referenciado.
    pulling = session.exec(
        select(Exercise).where(
            Exercise.is_active == True,
            Exercise.rm_source_exercise_id != None,  # noqa: E711
        )
    ).all()
    for e in pulling:
        ref = latest.get(e.rm_source_exercise_id)
        if ref is not None:
            latest[e.id] = ref
    return latest


@router.get("/coach/athletes/{athlete_id}/exercise-rms/history")
def get_exercise_rm_history(
    athlete_id: int,
    exercise_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    stmt = (
        select(AthleteExerciseRMHistory)
        .where(AthleteExerciseRMHistory.athlete_id == athlete_id)
        .where(AthleteExerciseRMHistory.exercise_id == exercise_id)
        .order_by(AthleteExerciseRMHistory.effective_date)
    )
    rows = session.exec(stmt).all()
    return [{"rm_value": r.rm_value, "effective_date": r.effective_date} for r in rows]


@router.get(
    "/coach/athletes/{athlete_id}/exercise-rms",
    response_model=List[ExerciseRMCurrentItem],
)
def coach_get_athlete_exercise_rms(
    athlete_id: int = Path(..., ge=1),
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    athlete = session.get(User, athlete_id)
    if not athlete or athlete.role != "athlete":
        raise HTTPException(status_code=404, detail="Atleta não encontrado.")

    exs = session.exec(
        select(Exercise)
        .where(
            Exercise.is_active == True,
            (Exercise.coach_id == None) | (Exercise.coach_id == coach.id),
        )
        .order_by(Exercise.name.asc())
    ).all()

    if not exs:
        return []

    ex_ids = [e.id for e in exs if e.id is not None]

    sub = (
        select(
            AthleteExerciseRMHistory.exercise_id,
            func.max(AthleteExerciseRMHistory.effective_date).label("max_dt"),
        )
        .where(AthleteExerciseRMHistory.athlete_id == athlete_id)
        .where(AthleteExerciseRMHistory.exercise_id.in_(ex_ids))
        .group_by(AthleteExerciseRMHistory.exercise_id)
        .subquery()
    )

    latest_rows = session.exec(
        select(AthleteExerciseRMHistory)
        .join(
            sub,
            (AthleteExerciseRMHistory.exercise_id == sub.c.exercise_id)
            & (AthleteExerciseRMHistory.effective_date == sub.c.max_dt),
        )
    ).all()

    latest_map = {r.exercise_id: r for r in latest_rows}
    own_value = {eid: r.rm_value for eid, r in latest_map.items()}

    out: List[ExerciseRMCurrentItem] = []
    for e in exs:
        row = latest_map.get(e.id)
        # Se o movimento puxa o RM de outro, usa o valor do referenciado.
        if e.rm_source_exercise_id:
            rm_value = own_value.get(e.rm_source_exercise_id)
            eff = None
        else:
            rm_value = row.rm_value if row else None
            eff = row.effective_date if row else None
        out.append(
            ExerciseRMCurrentItem(
                exercise_id=e.id,
                exercise_name=e.name,
                category_id=e.category_id,
                type=e.type,
                rm_value=rm_value,
                effective_date=eff,
            )
        )

    return out


# ============================================================
# Dashboard
# ============================================================
@router.get("/coach/dashboard", response_model=CoachDashboardResponse)
def coach_dashboard(
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    today = date.today()

    athletes_total = session.exec(
        select(func.count(func.distinct(TrainingSheet.athlete_id)))
        .where(TrainingSheet.coach_id == coach.id)
    ).one() or 0

    sheets_total = session.exec(
        select(func.count(TrainingSheet.id))
        .where(TrainingSheet.coach_id == coach.id)
    ).one() or 0

    executions_total = session.exec(
        select(func.count(TrainingSetExecution.id))
        .where(TrainingSetExecution.training_sheet_id.in_(
            select(TrainingSheet.id).where(TrainingSheet.coach_id == coach.id)
        ))
    ).one() or 0

    executions_today = session.exec(
        select(func.count(TrainingSetExecution.id))
        .where(
            TrainingSetExecution.date_completed == today,
            TrainingSetExecution.training_sheet_id.in_(
                select(TrainingSheet.id).where(TrainingSheet.coach_id == coach.id)
            ),
        )
    ).one() or 0

    days_completed_today = session.exec(
        select(func.count(TrainingDayCompletion.id))
        .where(
            TrainingDayCompletion.date_completed == today,
            TrainingDayCompletion.training_sheet_id.in_(
                select(TrainingSheet.id).where(TrainingSheet.coach_id == coach.id)
            ),
        )
    ).one() or 0

    days_completed_total = session.exec(
        select(func.count(TrainingDayCompletion.id))
        .where(
            TrainingDayCompletion.training_sheet_id.in_(
                select(TrainingSheet.id).where(TrainingSheet.coach_id == coach.id)
            )
        )
    ).one() or 0

    return CoachDashboardResponse(
        athletes_total=int(athletes_total),
        sheets_total=int(sheets_total),
        executions_total=int(executions_total),
        executions_today=int(executions_today),
        days_completed_today=int(days_completed_today),
        days_completed_total=int(days_completed_total),
    )


# ============================================================
# Planilhas
# ============================================================
@router.post("/coach/training-sheets", response_model=TrainingSheetRead)
def create_training_sheet(
    payload: TrainingSheetCreate,
    current_coach: User = Depends(require_role("coach")),
    session: Session = Depends(get_session),
):
    athlete = session.get(User, payload.athlete_id)
    if not athlete or athlete.role != "athlete":
        raise HTTPException(status_code=400, detail="Atleta inválido")

    start = payload.start_date
    if not start:
        raise HTTPException(status_code=400, detail="start_date é obrigatório.")

    end = compute_end_date(start, payload.weeks)
    plan_dict = payload.plan or build_default_plan(payload.weeks, payload.same_weeks)

    sheet = TrainingSheet(
        athlete_id=payload.athlete_id,
        coach_id=current_coach.id,
        title=payload.title,
        weeks=payload.weeks,
        same_weeks=payload.same_weeks,
        plan=plan_dict,
        start_date=start,
        end_date=end,
    )
    session.add(sheet)
    session.commit()
    session.refresh(sheet)
    return sheet


@router.get("/coach/training-sheets", response_model=List[TrainingSheetRead])
def list_training_sheets(
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    stmt = select(TrainingSheet).where(TrainingSheet.coach_id == coach.id)
    return session.exec(stmt).all()


@router.get("/coach/training-sheets/{sheet_id}", response_model=TrainingSheetDetail)
def get_training_sheet_detail(
    sheet_id: int,
    current_coach: User = Depends(require_role("coach")),
    session: Session = Depends(get_session),
):
    sheet = session.get(TrainingSheet, sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Planilha não encontrada")
    if sheet.coach_id != current_coach.id:
        raise HTTPException(status_code=403, detail="Acesso negado a esta planilha")

    if not sheet.plan:
        sheet.plan = build_default_plan(sheet.weeks or 4, sheet.same_weeks)
        session.add(sheet)
        session.commit()
        session.refresh(sheet)

    raw_plan = sheet.plan
    if isinstance(raw_plan, str):
        try:
            raw_plan = json.loads(raw_plan)
        except Exception:
            raw_plan = {"weeks": []}

    raw_plan = normalize_plan_for_sheet(
        session, coach_id=current_coach.id, raw_plan=raw_plan
    )

    return TrainingSheetDetail(
        id=sheet.id,
        title=sheet.title,
        athlete_id=sheet.athlete_id,
        coach_id=sheet.coach_id,
        weeks=sheet.weeks,
        same_weeks=sheet.same_weeks,
        plan=raw_plan,
        created_at=sheet.created_at,
        start_date=sheet.start_date,
        end_date=sheet.end_date,
    )


@router.patch(
    "/coach/training-sheets/{sheet_id}/dates",
    response_model=TrainingSheetRead,
)
def update_training_sheet_dates(
    sheet_id: int,
    payload: TrainingSheetDatesUpdate,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    sheet = session.get(TrainingSheet, sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Planilha não encontrada")
    if sheet.coach_id != coach.id:
        raise HTTPException(status_code=403, detail="Acesso negado a esta planilha")

    sheet.start_date = payload.start_date
    sheet.end_date = compute_end_date(sheet.start_date, sheet.weeks)
    session.add(sheet)
    session.commit()
    session.refresh(sheet)
    return sheet


@router.put("/coach/training-sheets/{sheet_id}/plan")
def update_training_sheet_plan(
    sheet_id: int,
    payload: TrainingPlanUpdate,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    sheet = session.get(TrainingSheet, sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Planilha não encontrada")
    if sheet.coach_id != coach.id:
        raise HTTPException(status_code=403, detail="Acesso negado a esta planilha")

    normalized = normalize_plan_for_sheet(
        session, coach_id=coach.id, raw_plan=payload.plan
    )

    missing = []
    for w in normalized.get("weeks") or []:
        for d in w.get("days") or []:
            for ex in d.get("lpo_exercises") or []:
                name = (ex.get("name") or "").strip()
                is_complex = bool(ex.get("is_complex"))

                if is_complex:
                    if not ex.get("rm_exercise_id"):
                        missing.append({
                            "week": w.get("week_number"),
                            "day": d.get("day"),
                            "exercise": name,
                            "reason": "complex_missing_rm_exercise_id",
                        })
                else:
                    if not ex.get("exercise_id"):
                        missing.append({
                            "week": w.get("week_number"),
                            "day": d.get("day"),
                            "exercise": name,
                            "reason": "missing_exercise_id",
                        })

    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Há exercícios LPO sem exercise_id "
                           "(ou complex sem rm_exercise_id).",
                "items": missing,
            },
        )

    sheet.plan = normalized
    session.add(sheet)
    session.commit()
    return {"ok": True}


@router.post(
    "/coach/training-sheets/{sheet_id}/duplicate",
    response_model=TrainingSheetRead,
)
def duplicate_training_sheet(
    sheet_id: int,
    payload: DuplicateTrainingSheetRequest,
    session: Session = Depends(get_session),
    current_coach: User = Depends(require_role("coach")),
):
    original = session.get(TrainingSheet, sheet_id)
    if not original:
        raise HTTPException(
            status_code=404,
            detail="Planilha original não encontrada.",
        )
    if original.coach_id != current_coach.id:
        raise HTTPException(
            status_code=403,
            detail="Você não tem acesso a esta planilha.",
        )

    target_athlete = session.get(User, payload.target_athlete_id)
    if not target_athlete or target_athlete.role != "athlete":
        raise HTTPException(status_code=400, detail="Atleta de destino inválido.")

    raw_plan = original.plan
    if isinstance(raw_plan, str):
        try:
            raw_plan = json.loads(raw_plan)
        except Exception:
            raw_plan = {"weeks": []}

    start = payload.start_date
    end = compute_end_date(start, original.weeks or 4)

    new_sheet = TrainingSheet(
        athlete_id=target_athlete.id,
        coach_id=current_coach.id,
        title=original.title,
        weeks=original.weeks,
        same_weeks=original.same_weeks,
        plan=raw_plan,
        start_date=start,
        end_date=end,
    )
    session.add(new_sheet)
    session.commit()
    session.refresh(new_sheet)
    return new_sheet


@router.get(
    "/coach/training-sheets/{sheet_id}/executions",
    response_model=List[SetExecutionOut],
)
def coach_list_sheet_executions(
    sheet_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    sheet = session.get(TrainingSheet, sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Planilha não encontrada")
    if sheet.coach_id != coach.id:
        raise HTTPException(status_code=403, detail="Acesso negado a esta planilha")

    stmt = (
        select(TrainingSetExecution)
        .where(TrainingSetExecution.training_sheet_id == sheet_id)
        .order_by(
            TrainingSetExecution.date_completed.asc(),
            TrainingSetExecution.week_number.asc(),
        )
    )
    rows = session.exec(stmt).all()

    return [
        SetExecutionOut(
            id=r.id,
            athlete_id=r.athlete_id,
            training_sheet_id=r.training_sheet_id,
            week_number=r.week_number,
            day=r.day,
            date_completed=r.date_completed,
            exercise_name=r.exercise_name,
            series_index=r.series_index,
            prescribed_percent=r.prescribed_percent,
            prescribed_kg=r.prescribed_kg,
            used_kg=r.used_kg,
            diff_kg=r.diff_kg,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
