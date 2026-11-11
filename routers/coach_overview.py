"""Visão geral da coach (telas Início e Atletas) e notas privadas por atleta.

  - GET /coach/overview                 → tudo que o Início e a lista de atletas mostram
  - GET /coach/athletes/{id}/notes      → notas privadas (só a coach vê)
  - PUT /coach/athletes/{id}/notes      → salva as notas

A "etiqueta" de cada atleta segue a ordem de prioridade do protótipo:
"Não entrou ainda" > "Alerta" (check-in pedindo atenção e ainda não visto) >
"Planilha vence" (termina em até 7 dias ou já terminou) > "Falta RM"
(a planilha usa um movimento sem RM) > "Sem planilha" > "Em dia".
"""
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel, select

from db import get_session
from models import (
    AthleteExerciseRMHistory,
    CoachNote,
    Exercise,
    TrainingSetExecution,
    TrainingSheet,
    User,
    VideoSubmission,
    WeeklyCheckin,
)
from security import require_role
from services.clock import br_date_of, today_br

router = APIRouter(tags=["coach-overview"])

ENDING_DAYS = 7  # "Planilha vence": termina em até 7 dias
IDLE_DAYS = 4  # "Sem treino há N dias" a partir de 4 dias


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


# ============================================================
# Schemas
# ============================================================
class SheetSummary(SQLModel):
    id: int
    title: str
    start_date: date
    end_date: date
    weeks: int
    current_week: int  # 1..weeks (0 = ainda não começou)


class CheckinSummary(SQLModel):
    id: int
    needs_attention: bool
    has_pain: bool
    seen: bool


class AthleteOverview(SQLModel):
    id: int
    name: str
    email: str
    whatsapp: Optional[str] = None
    must_change_password: bool = False
    sheet: Optional[SheetSummary] = None
    tag: str
    tag_kind: str  # ok | attention | alert | neutral
    missing_rm: bool = False
    sheet_ending: bool = False
    last_training: Optional[date] = None
    days_without_training: Optional[int] = None
    trained_today: bool = False
    video_today: bool = False
    videos_pending: int = 0
    # Séries marcadas como "errou" ou "não fez" nos últimos 7 dias.
    missed_sets_week: int = 0
    checkin: Optional[CheckinSummary] = None


class CoachInfo(SQLModel):
    name: str
    whatsapp: Optional[str] = None


class CheckinStats(SQLModel):
    answered: int
    total: int
    alerts: int
    pain: int
    low: int  # desempenho ou sono baixo (≤ 4)


class OverviewOut(SQLModel):
    coach: CoachInfo
    today: date
    week_start: date
    athletes: List[AthleteOverview]
    videos_pending: int
    sheets_ending: int
    checkins: CheckinStats


class NotesIn(SQLModel):
    text: str = ""


class NotesOut(SQLModel):
    text: str
    updated_at: Optional[datetime] = None


# ============================================================
# Helpers
# ============================================================
def _current_sheet(sheets: List[TrainingSheet], today: date) -> Optional[TrainingSheet]:
    active = [s for s in sheets if s.start_date <= today <= s.end_date]
    pool = active or sheets
    if not pool:
        return None
    return sorted(pool, key=lambda s: s.start_date, reverse=True)[0]


def _plan_rm_ids(plan: dict) -> Set[int]:
    """Ids dos movimentos que dão o RM de cada exercício LPO da planilha."""
    ids: Set[int] = set()
    for w in (plan or {}).get("weeks", []) or []:
        for d in w.get("days", []) or []:
            exs = d.get("lpo_exercises")
            if not isinstance(exs, list):
                exs = d.get("exercises") or []
            for ex in exs:
                ref = ex.get("rm_exercise_id") if ex.get("is_complex") else ex.get("exercise_id")
                if isinstance(ref, int):
                    ids.add(ref)
    return ids


def _low(c: WeeklyCheckin) -> bool:
    a = c.answers or {}
    for k in ("desempenho", "sono"):
        v = a.get(k)
        if isinstance(v, (int, float)) and v <= 4:
            return True
    return False


# ============================================================
# Rotas
# ============================================================
@router.get("/coach/overview", response_model=OverviewOut)
def coach_overview(
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    today = today_br()
    week = _monday(today)
    athletes = session.exec(
        select(User).where(User.role == "athlete", User.coach_id == coach.id).order_by(User.name)
    ).all()
    ids = [a.id for a in athletes] or [-1]

    sheets_by: Dict[int, List[TrainingSheet]] = {}
    for s in session.exec(select(TrainingSheet).where(TrainingSheet.athlete_id.in_(ids))).all():
        sheets_by.setdefault(s.athlete_id, []).append(s)

    # RMs e herança de RM (variação → principal)
    has_rm: Dict[int, Set[int]] = {}
    for r in session.exec(
        select(AthleteExerciseRMHistory).where(AthleteExerciseRMHistory.athlete_id.in_(ids))
    ).all():
        has_rm.setdefault(r.athlete_id, set()).add(r.exercise_id)
    source_of = {
        e.id: e.rm_source_exercise_id
        for e in session.exec(select(Exercise).where(Exercise.rm_source_exercise_id != None)).all()  # noqa: E711
    }

    # Último dia com série marcada
    last_by: Dict[int, date] = {}
    missed_by: Dict[int, int] = {}
    week_ago = today - timedelta(days=7)
    for e in session.exec(
        select(TrainingSetExecution).where(
            TrainingSetExecution.athlete_id.in_(ids),
            TrainingSetExecution.status != None,  # noqa: E711
        )
    ).all():
        if e.athlete_id not in last_by or e.date_completed > last_by[e.athlete_id]:
            last_by[e.athlete_id] = e.date_completed
        if e.status in ("errou", "nao_fez") and e.date_completed and e.date_completed >= week_ago:
            missed_by[e.athlete_id] = missed_by.get(e.athlete_id, 0) + 1

    videos = session.exec(select(VideoSubmission).where(VideoSubmission.athlete_id.in_(ids))).all()
    checkins = {
        c.athlete_id: c
        for c in session.exec(
            select(WeeklyCheckin).where(WeeklyCheckin.athlete_id.in_(ids), WeeklyCheckin.week_start == week)
        ).all()
    }

    out: List[AthleteOverview] = []
    for a in athletes:
        sheet = _current_sheet(sheets_by.get(a.id, []), today)
        summary = None
        missing_rm = False
        ending = False
        if sheet:
            if today < sheet.start_date:
                cw = 0
            else:
                cw = min((today - sheet.start_date).days // 7 + 1, sheet.weeks)
            summary = SheetSummary(
                id=sheet.id, title=sheet.title, start_date=sheet.start_date,
                end_date=sheet.end_date, weeks=sheet.weeks, current_week=cw,
            )
            ending = sheet.end_date <= today + timedelta(days=ENDING_DAYS)
            mine = has_rm.get(a.id, set())
            for ref in _plan_rm_ids(sheet.plan):
                main = source_of.get(ref) or ref
                if main not in mine and ref not in mine:
                    missing_rm = True
                    break

        c = checkins.get(a.id)
        csum = (
            CheckinSummary(id=c.id, needs_attention=c.needs_attention, has_pain=c.has_pain, seen=c.coach_seen_at is not None)
            if c else None
        )
        last = last_by.get(a.id)
        mine_videos = [v for v in videos if v.athlete_id == a.id]

        if a.must_change_password:
            tag, kind = "Não entrou ainda", "attention"
        elif c and c.needs_attention and c.coach_seen_at is None:
            tag, kind = "Alerta", "alert"
        elif ending and sheet:
            tag, kind = "Planilha vence", "alert"
        elif missing_rm:
            tag, kind = "Falta RM", "attention"
        elif not sheet:
            tag, kind = "Sem planilha", "neutral"
        else:
            tag, kind = "Em dia", "ok"

        out.append(AthleteOverview(
            id=a.id, name=a.name, email=a.email, whatsapp=a.whatsapp,
            must_change_password=a.must_change_password,
            sheet=summary, tag=tag, tag_kind=kind, missing_rm=missing_rm, sheet_ending=ending,
            last_training=last,
            days_without_training=(today - last).days if last else None,
            trained_today=last == today,
            video_today=any(br_date_of(v.created_at) == today for v in mine_videos if v.created_at),
            videos_pending=sum(1 for v in mine_videos if v.status == "pendente"),
            missed_sets_week=missed_by.get(a.id, 0),
            checkin=csum,
        ))

    answered = list(checkins.values())
    return OverviewOut(
        coach=CoachInfo(name=coach.name, whatsapp=coach.whatsapp),
        today=today,
        week_start=week,
        athletes=out,
        videos_pending=sum(1 for v in videos if v.status == "pendente"),
        sheets_ending=sum(1 for x in out if x.sheet_ending and x.sheet),
        checkins=CheckinStats(
            answered=len(answered),
            total=len(athletes),
            alerts=sum(1 for c in answered if c.needs_attention and c.coach_seen_at is None),
            pain=sum(1 for c in answered if c.has_pain),
            low=sum(1 for c in answered if _low(c)),
        ),
    )


def _owned(session: Session, coach: User, athlete_id: int) -> User:
    athlete = session.get(User, athlete_id)
    if not athlete or athlete.role != "athlete":
        raise HTTPException(status_code=404, detail="Atleta não encontrado.")
    if athlete.coach_id != coach.id:
        raise HTTPException(status_code=403, detail="Este atleta não pertence a você.")
    return athlete


@router.get("/coach/athletes/{athlete_id}/notes", response_model=NotesOut)
def coach_get_notes(
    athlete_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    _owned(session, coach, athlete_id)
    n = session.exec(select(CoachNote).where(CoachNote.athlete_id == athlete_id)).first()
    return NotesOut(text=n.text, updated_at=n.updated_at) if n else NotesOut(text="")


@router.put("/coach/athletes/{athlete_id}/notes", response_model=NotesOut)
def coach_set_notes(
    athlete_id: int,
    payload: NotesIn,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    _owned(session, coach, athlete_id)
    n = session.exec(select(CoachNote).where(CoachNote.athlete_id == athlete_id)).first()
    if n is None:
        n = CoachNote(athlete_id=athlete_id)
    n.coach_id = coach.id
    n.text = payload.text or ""
    n.updated_at = datetime.now(timezone.utc)
    session.add(n)
    session.commit()
    session.refresh(n)
    return NotesOut(text=n.text, updated_at=n.updated_at)
