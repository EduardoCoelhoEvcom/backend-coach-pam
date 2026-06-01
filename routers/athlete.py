"""Rotas do atleta:

  - /athlete/exercise-rms (GET, POST batch)
  - /athlete/exercise-rms/current (GET)
  - /athlete/exercise-rms/current/all (GET)
  - /athlete/exercise-rms/history (GET)
  - /athlete/save-day-execution (POST)
  - /athlete/training-sheets (GET)
  - /athlete/training-sheets/{sheet_id} (GET)
  - /athlete/training-sheets/{sheet_id}/executions (GET)
  - /athlete/progress (GET)
  - /athlete/complete-day (POST)
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, or_
from sqlmodel import Session, select

logger = logging.getLogger(__name__)

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
    AthleteProgressResponse,
    CompleteDayRequest,
    ExerciseRMCurrentItem,
    SaveDayExecutionRequest,
    SetExecutionOut,
    SetRMBatch,
    TrainingSheetDetail,
    TrainingSheetRead,
)
from security import require_role
from services.training_plan import normalize_plan_for_sheet

router = APIRouter(tags=["athlete"])


# ---------- Helper ----------
def _compute_athlete_progress(
    athlete_id: int, session: Session
) -> AthleteProgressResponse:
    stmt = (
        select(TrainingDayCompletion)
        .where(TrainingDayCompletion.athlete_id == athlete_id)
        .order_by(TrainingDayCompletion.date_completed.desc())
    )
    completions = session.exec(stmt).all()

    if not completions:
        return AthleteProgressResponse(
            total_completed_days=0,
            completed_today=False,
            streak_days=0,
        )

    today = date.today()
    dates = {c.date_completed for c in completions}
    completed_today = today in dates

    streak = 0
    if completed_today:
        streak = 1
        current = today
        while True:
            prev = current - timedelta(days=1)
            if prev in dates:
                streak += 1
                current = prev
            else:
                break

    return AthleteProgressResponse(
        total_completed_days=len(dates),
        completed_today=completed_today,
        streak_days=streak,
    )


# ============================================================
# RMs
# ============================================================
@router.get("/athlete/exercise-rms/current")
def athlete_get_current_rm(
    exercise_id: int,
    athlete: User = Depends(require_role("athlete")),
    session: Session = Depends(get_session),
):
    stmt = (
        select(AthleteExerciseRMHistory)
        .where(AthleteExerciseRMHistory.athlete_id == athlete.id)
        .where(AthleteExerciseRMHistory.exercise_id == exercise_id)
        .order_by(desc(AthleteExerciseRMHistory.effective_date))
        .limit(1)
    )
    row = session.exec(stmt).first()
    return {"rm_value": row.rm_value if row else None}


@router.get("/athlete/exercise-rms/current/all")
def athlete_get_current_all(
    athlete: User = Depends(require_role("athlete")),
    session: Session = Depends(get_session),
):
    stmt = (
        select(AthleteExerciseRMHistory)
        .where(AthleteExerciseRMHistory.athlete_id == athlete.id)
        .order_by(desc(AthleteExerciseRMHistory.effective_date))
    )
    rows = session.exec(stmt).all()

    latest: dict[int, float] = {}
    for r in rows:
        if r.exercise_id not in latest:
            latest[r.exercise_id] = r.rm_value
    return latest


@router.get("/athlete/exercise-rms/history")
def athlete_get_history(
    exercise_id: int,
    athlete: User = Depends(require_role("athlete")),
    session: Session = Depends(get_session),
):
    stmt = (
        select(AthleteExerciseRMHistory)
        .where(AthleteExerciseRMHistory.athlete_id == athlete.id)
        .where(AthleteExerciseRMHistory.exercise_id == exercise_id)
        .order_by(AthleteExerciseRMHistory.effective_date.asc())
    )
    rows = session.exec(stmt).all()
    return [{"rm_value": r.rm_value, "effective_date": r.effective_date} for r in rows]


@router.get("/athlete/exercise-rms", response_model=List[ExerciseRMCurrentItem])
def athlete_get_my_exercise_rms(
    athlete: User = Depends(require_role("athlete")),
    session: Session = Depends(get_session),
):
    exs = session.exec(
        select(Exercise)
        .where(Exercise.is_active == True)
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
        .where(AthleteExerciseRMHistory.athlete_id == athlete.id)
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

    out: List[ExerciseRMCurrentItem] = []
    for e in exs:
        row = latest_map.get(e.id)
        out.append(
            ExerciseRMCurrentItem(
                exercise_id=e.id,
                exercise_name=e.name,
                category_id=e.category_id,
                type=e.type,
                rm_value=row.rm_value if row else None,
                effective_date=row.effective_date if row else None,
            )
        )

    return out


@router.post("/athlete/exercise-rms")
def athlete_set_rms(
    body: SetRMBatch,
    athlete: User = Depends(require_role("athlete")),
    session: Session = Depends(get_session),
):
    """Salva RMs em lote.

    Anti-spam: se o novo RM for igual ao último, não cria registro.
    NOTA: Existia outra rota POST /athlete/exercise-rms (single item) duplicada,
    nunca executada (FastAPI registra a primeira). Foi removida no refactor.
    """
    now = datetime.now(timezone.utc)

    for item in body.items:
        stmt = (
            select(AthleteExerciseRMHistory)
            .where(AthleteExerciseRMHistory.athlete_id == athlete.id)
            .where(AthleteExerciseRMHistory.exercise_id == item.exercise_id)
            .order_by(desc(AthleteExerciseRMHistory.effective_date))
            .limit(1)
        )
        last = session.exec(stmt).first()
        if last and abs(float(last.rm_value) - float(item.rm_value)) < 1e-6:
            continue

        row = AthleteExerciseRMHistory(
            athlete_id=athlete.id,
            exercise_id=item.exercise_id,
            rm_value=item.rm_value,
            effective_date=item.effective_date or now,
            source="athlete",
        )
        session.add(row)

    session.commit()
    return {"ok": True}


# ============================================================
# Planilhas
# ============================================================
@router.get("/athlete/training-sheets", response_model=List[TrainingSheetRead])
def athlete_training_sheets(
    athlete: User = Depends(require_role("athlete")),
    session: Session = Depends(get_session),
):
    today = date.today()
    visible_until = today + timedelta(days=2)

    stmt = (
        select(TrainingSheet)
        .where(TrainingSheet.athlete_id == athlete.id)
        .where(
            or_(
                TrainingSheet.start_date == None,
                TrainingSheet.start_date <= visible_until,
            )
        )
        .order_by(
            TrainingSheet.start_date.desc(),
            TrainingSheet.created_at.desc(),
        )
    )
    return session.exec(stmt).all()


@router.get("/athlete/training-sheets/{sheet_id}", response_model=TrainingSheetDetail)
def get_athlete_training_sheet_detail(
    sheet_id: int,
    athlete: User = Depends(require_role("athlete")),
    session: Session = Depends(get_session),
):
    sheet = session.get(TrainingSheet, sheet_id)
    if (not sheet) or (sheet.athlete_id != athlete.id):
        raise HTTPException(status_code=404, detail="Planilha não encontrada")

    raw_plan = sheet.plan
    if isinstance(raw_plan, str):
        try:
            raw_plan = json.loads(raw_plan)
        except Exception:
            raw_plan = {"weeks": []}

    raw_plan = normalize_plan_for_sheet(
        session, coach_id=sheet.coach_id, raw_plan=raw_plan
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


@router.get(
    "/athlete/training-sheets/{sheet_id}/executions",
    response_model=List[SetExecutionOut],
)
def athlete_list_sheet_executions(
    sheet_id: int,
    athlete: User = Depends(require_role("athlete")),
    session: Session = Depends(get_session),
):
    sheet = session.get(TrainingSheet, sheet_id)
    if not sheet or sheet.athlete_id != athlete.id:
        raise HTTPException(
            status_code=404,
            detail="Planilha não encontrada para este atleta.",
        )

    stmt = (
        select(TrainingSetExecution)
        .where(
            TrainingSetExecution.training_sheet_id == sheet_id,
            TrainingSetExecution.athlete_id == athlete.id,
        )
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


# ============================================================
# Execuções e progresso
# ============================================================
@router.post("/athlete/save-day-execution")
def save_day_execution(
    body: SaveDayExecutionRequest,
    athlete: User = Depends(require_role("athlete")),
    session: Session = Depends(get_session),
):
    sheet = session.get(TrainingSheet, body.training_sheet_id)
    if not sheet or sheet.athlete_id != athlete.id:
        raise HTTPException(
            status_code=404,
            detail="Planilha não encontrada para este atleta.",
        )

    today = date.today()

    # apaga execuções do dia (idempotente)
    stmt = select(TrainingSetExecution).where(
        TrainingSetExecution.athlete_id == athlete.id,
        TrainingSetExecution.training_sheet_id == body.training_sheet_id,
        TrainingSetExecution.week_number == body.week_number,
        TrainingSetExecution.day == body.day,
        TrainingSetExecution.date_completed == today,
    )
    rows = session.exec(stmt).all()
    for r in rows:
        session.delete(r)
    session.commit()

    now = datetime.now(timezone.utc)

    for s in (body.sets or []):
        diff = None
        if s.used_kg is not None and s.prescribed_kg is not None:
            diff = float(s.used_kg) - float(s.prescribed_kg)

        row = TrainingSetExecution(
            athlete_id=athlete.id,
            training_sheet_id=body.training_sheet_id,
            week_number=body.week_number,
            day=body.day,
            date_completed=today,
            exercise_name=s.exercise_name,
            series_index=s.series_index,
            prescribed_percent=s.prescribed_percent,
            prescribed_kg=s.prescribed_kg,
            used_kg=s.used_kg,
            diff_kg=diff,
            created_at=now,
            updated_at=now,
        )
        session.add(row)

    session.commit()
    return {"ok": True, "saved_sets": len(body.sets or [])}


@router.get("/athlete/progress", response_model=AthleteProgressResponse)
def get_athlete_progress(
    athlete: User = Depends(require_role("athlete")),
    session: Session = Depends(get_session),
):
    return _compute_athlete_progress(athlete.id, session)


@router.post("/athlete/complete-day", response_model=AthleteProgressResponse)
async def complete_day(
    body: CompleteDayRequest,
    athlete: User = Depends(require_role("athlete")),
    session: Session = Depends(get_session),
):
    logger.info(
        "complete_day",
        extra={
            "athlete_id": athlete.id,
            "training_sheet_id": body.training_sheet_id,
            "week_number": body.week_number,
            "day": body.day,
            "sets_count": None if body.sets is None else len(body.sets),
        },
    )

    sheet = session.get(TrainingSheet, body.training_sheet_id)
    if not sheet or sheet.athlete_id != athlete.id:
        raise HTTPException(
            status_code=404,
            detail="Planilha não encontrada para este atleta.",
        )

    today = date.today()

    # 1) se vier sets → sobrescreve as execuções de HOJE pra esse sheet/semana/dia
    if body.sets is not None:
        delete_stmt = select(TrainingSetExecution).where(
            TrainingSetExecution.athlete_id == athlete.id,
            TrainingSetExecution.training_sheet_id == body.training_sheet_id,
            TrainingSetExecution.week_number == body.week_number,
            TrainingSetExecution.day == body.day,
            TrainingSetExecution.date_completed == today,
        )
        existing_rows = session.exec(delete_stmt).all()
        for r in existing_rows:
            session.delete(r)
        session.commit()

        now = datetime.now(timezone.utc)
        for s in body.sets:
            diff = None
            if s.used_kg is not None and s.prescribed_kg is not None:
                diff = float(s.used_kg) - float(s.prescribed_kg)

            row = TrainingSetExecution(
                athlete_id=athlete.id,
                training_sheet_id=body.training_sheet_id,
                week_number=body.week_number,
                day=body.day,
                date_completed=today,
                exercise_name=s.exercise_name,
                series_index=s.series_index,
                prescribed_percent=s.prescribed_percent,
                prescribed_kg=s.prescribed_kg,
                used_kg=s.used_kg,
                diff_kg=diff,
                created_at=now,
                updated_at=now,
            )
            session.add(row)

        session.commit()

    # 2) marca conclusão do dia (idempotente por data)
    stmt = select(TrainingDayCompletion).where(
        TrainingDayCompletion.athlete_id == athlete.id,
        TrainingDayCompletion.training_sheet_id == body.training_sheet_id,
        TrainingDayCompletion.week_number == body.week_number,
        TrainingDayCompletion.day == body.day,
        TrainingDayCompletion.date_completed == today,
    )
    existing = session.exec(stmt).first()

    if not existing:
        completion = TrainingDayCompletion(
            athlete_id=athlete.id,
            training_sheet_id=body.training_sheet_id,
            week_number=body.week_number,
            day=body.day,
            date_completed=today,
        )
        session.add(completion)
        session.commit()

    return _compute_athlete_progress(athlete.id, session)
