"""Rotas de mobilidade, diagnóstico inicial, objetivo/focos e contato da coach.

Atleta:
  - GET    /athlete/mobility?day=AAAA-MM-DD      → meus itens + se já marquei no dia
  - POST   /athlete/mobility/{id}/done            → marca como feito no dia
  - DELETE /athlete/mobility/{id}/done?day=...    → desmarca
  - GET    /athlete/diagnosis                     → meu diagnóstico inicial (ou null)
  - GET    /athlete/goal                          → meu objetivo, fases e focos (ou null)
  - GET    /athlete/coach                         → nome e WhatsApp da minha coach

Coach:
  - GET    /coach/athletes/{id}/mobility          → itens do atleta
  - POST   /coach/athletes/{id}/mobility          → adiciona item
  - PATCH  /coach/mobility/{item_id}              → edita item
  - DELETE /coach/mobility/{item_id}              → remove item
  - GET    /coach/athletes/{id}/diagnosis         → diagnóstico do atleta
  - PUT    /coach/athletes/{id}/diagnosis         → cria/atualiza diagnóstico
  - GET    /coach/athletes/{id}/goal              → objetivo, fases e focos do atleta
  - PUT    /coach/athletes/{id}/goal              → cria/atualiza objetivo, fases e focos
  - PUT    /coach/me/whatsapp                     → WhatsApp da própria coach

`day` é opcional: o app manda a data local do aluno, pra não virar o dia
no horário do servidor (UTC). Sem `day`, vale a data do servidor.

O vídeo e o PDF chegam como URL: onde guardar os arquivos ainda vai ser
decidido. O backend só guarda o endereço.
"""
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, SQLModel, select

from db import get_session
from models import InitialDiagnosis, MobilityCompletion, MobilityItem, TrainingGoal, User
from security import require_role

router = APIRouter(tags=["coaching"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owned_athlete(session: Session, coach: User, athlete_id: int) -> User:
    athlete = session.get(User, athlete_id)
    if not athlete or athlete.role != "athlete":
        raise HTTPException(status_code=404, detail="Atleta não encontrado.")
    if athlete.coach_id != coach.id:
        raise HTTPException(status_code=403, detail="Este atleta não pertence a você.")
    return athlete


def _clean(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    return text.strip() or None


def _clean_url(url: Optional[str]) -> Optional[str]:
    url = _clean(url)
    if url and not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="O link precisa começar com http:// ou https://.")
    return url


# ============================================================
# Schemas
# ============================================================
class MobilityIn(SQLModel):
    name: str
    dose: Optional[str] = None
    video_url: Optional[str] = None
    position: Optional[int] = None


class MobilityPatch(SQLModel):
    name: Optional[str] = None
    dose: Optional[str] = None
    video_url: Optional[str] = None
    position: Optional[int] = None


class MobilityOut(SQLModel):
    id: int
    athlete_id: int
    name: str
    dose: Optional[str]
    video_url: Optional[str]
    position: int


class AthleteMobilityOut(MobilityOut):
    done: bool  # já marcou como feito no dia pedido


class MobilityDayIn(SQLModel):
    day: Optional[date] = None


class DiagnosisIn(SQLModel):
    strengths: Optional[str] = None
    adjustments: Optional[str] = None
    mobility: Optional[str] = None
    pdf_url: Optional[str] = None
    diagnosed_on: Optional[date] = None


class DiagnosisOut(SQLModel):
    athlete_id: int
    strengths: Optional[str]
    adjustments: Optional[str]
    mobility: Optional[str]
    pdf_url: Optional[str]
    diagnosed_on: date
    updated_at: datetime


def _mobility_out(item: MobilityItem) -> MobilityOut:
    return MobilityOut(
        id=item.id,
        athlete_id=item.athlete_id,
        name=item.name,
        dose=item.dose,
        video_url=item.video_url,
        position=item.position,
    )


def _items_of(session: Session, athlete_id: int) -> List[MobilityItem]:
    return list(
        session.exec(
            select(MobilityItem)
            .where(MobilityItem.athlete_id == athlete_id)
            .order_by(MobilityItem.position, MobilityItem.id)
        ).all()
    )


def _diagnosis_out(d: InitialDiagnosis) -> DiagnosisOut:
    return DiagnosisOut(
        athlete_id=d.athlete_id,
        strengths=d.strengths,
        adjustments=d.adjustments,
        mobility=d.mobility,
        pdf_url=d.pdf_url,
        diagnosed_on=d.diagnosed_on,
        updated_at=d.updated_at,
    )


# ============================================================
# Atleta — mobilidade
# ============================================================
@router.get("/athlete/mobility", response_model=List[AthleteMobilityOut])
def athlete_list_mobility(
    day: Optional[date] = Query(default=None),
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    day = day or date.today()
    items = _items_of(session, athlete.id)
    done_ids = set(
        session.exec(
            select(MobilityCompletion.item_id).where(
                MobilityCompletion.athlete_id == athlete.id,
                MobilityCompletion.done_on == day,
            )
        ).all()
    )
    return [
        AthleteMobilityOut(**_mobility_out(i).model_dump(), done=i.id in done_ids)
        for i in items
    ]


def _my_item(session: Session, athlete: User, item_id: int) -> MobilityItem:
    item = session.get(MobilityItem, item_id)
    if not item or item.athlete_id != athlete.id:
        raise HTTPException(status_code=404, detail="Mobilidade não encontrada.")
    return item


@router.post("/athlete/mobility/{item_id}/done", response_model=AthleteMobilityOut)
def athlete_mark_mobility(
    item_id: int,
    payload: Optional[MobilityDayIn] = None,
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    item = _my_item(session, athlete, item_id)
    day = (payload.day if payload else None) or date.today()
    exists = session.exec(
        select(MobilityCompletion).where(
            MobilityCompletion.item_id == item.id,
            MobilityCompletion.done_on == day,
        )
    ).first()
    if not exists:  # marcar duas vezes não duplica
        session.add(MobilityCompletion(item_id=item.id, athlete_id=athlete.id, done_on=day))
        session.commit()
    return AthleteMobilityOut(**_mobility_out(item).model_dump(), done=True)


@router.delete("/athlete/mobility/{item_id}/done", response_model=AthleteMobilityOut)
def athlete_unmark_mobility(
    item_id: int,
    day: Optional[date] = Query(default=None),
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    item = _my_item(session, athlete, item_id)
    day = day or date.today()
    for row in session.exec(
        select(MobilityCompletion).where(
            MobilityCompletion.item_id == item.id,
            MobilityCompletion.done_on == day,
        )
    ).all():
        session.delete(row)
    session.commit()
    return AthleteMobilityOut(**_mobility_out(item).model_dump(), done=False)


# ============================================================
# Atleta — diagnóstico
# ============================================================
@router.get("/athlete/diagnosis", response_model=Optional[DiagnosisOut])
def athlete_get_diagnosis(
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    d = session.exec(
        select(InitialDiagnosis).where(InitialDiagnosis.athlete_id == athlete.id)
    ).first()
    return _diagnosis_out(d) if d else None


# ============================================================
# Coach — mobilidade
# ============================================================
@router.get("/coach/athletes/{athlete_id}/mobility", response_model=List[MobilityOut])
def coach_list_mobility(
    athlete_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    _owned_athlete(session, coach, athlete_id)
    return [_mobility_out(i) for i in _items_of(session, athlete_id)]


@router.post("/coach/athletes/{athlete_id}/mobility", response_model=MobilityOut)
def coach_add_mobility(
    athlete_id: int,
    payload: MobilityIn,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    _owned_athlete(session, coach, athlete_id)
    name = _clean(payload.name)
    if not name:
        raise HTTPException(status_code=422, detail="Dê um nome pra mobilidade.")
    position = payload.position
    if position is None:  # vai pro fim da lista
        items = _items_of(session, athlete_id)
        position = (max(i.position for i in items) + 1) if items else 0
    item = MobilityItem(
        athlete_id=athlete_id,
        coach_id=coach.id,
        name=name,
        dose=_clean(payload.dose),
        video_url=_clean_url(payload.video_url),
        position=position,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return _mobility_out(item)


def _coach_item(session: Session, coach: User, item_id: int) -> MobilityItem:
    item = session.get(MobilityItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Mobilidade não encontrada.")
    _owned_athlete(session, coach, item.athlete_id)
    return item


@router.patch("/coach/mobility/{item_id}", response_model=MobilityOut)
def coach_edit_mobility(
    item_id: int,
    payload: MobilityPatch,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    item = _coach_item(session, coach, item_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        name = _clean(data["name"])
        if not name:
            raise HTTPException(status_code=422, detail="Dê um nome pra mobilidade.")
        item.name = name
    if "dose" in data:
        item.dose = _clean(data["dose"])
    if "video_url" in data:
        item.video_url = _clean_url(data["video_url"])
    if data.get("position") is not None:
        item.position = data["position"]
    item.updated_at = _now()
    session.add(item)
    session.commit()
    session.refresh(item)
    return _mobility_out(item)


@router.delete("/coach/mobility/{item_id}")
def coach_delete_mobility(
    item_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    item = _coach_item(session, coach, item_id)
    for row in session.exec(
        select(MobilityCompletion).where(MobilityCompletion.item_id == item.id)
    ).all():
        session.delete(row)
    session.flush()
    session.delete(item)
    session.commit()
    return {"ok": True}


# ============================================================
# Coach — diagnóstico
# ============================================================
@router.get("/coach/athletes/{athlete_id}/diagnosis", response_model=Optional[DiagnosisOut])
def coach_get_diagnosis(
    athlete_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    _owned_athlete(session, coach, athlete_id)
    d = session.exec(
        select(InitialDiagnosis).where(InitialDiagnosis.athlete_id == athlete_id)
    ).first()
    return _diagnosis_out(d) if d else None


@router.put("/coach/athletes/{athlete_id}/diagnosis", response_model=DiagnosisOut)
def coach_set_diagnosis(
    athlete_id: int,
    payload: DiagnosisIn,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    _owned_athlete(session, coach, athlete_id)
    d = session.exec(
        select(InitialDiagnosis).where(InitialDiagnosis.athlete_id == athlete_id)
    ).first()
    if d is None:
        d = InitialDiagnosis(athlete_id=athlete_id)
    d.coach_id = coach.id
    d.strengths = _clean(payload.strengths)
    d.adjustments = _clean(payload.adjustments)
    d.mobility = _clean(payload.mobility)
    d.pdf_url = _clean_url(payload.pdf_url)
    if payload.diagnosed_on:
        d.diagnosed_on = payload.diagnosed_on
    d.updated_at = _now()
    session.add(d)
    session.commit()
    session.refresh(d)
    return _diagnosis_out(d)


# ============================================================
# Objetivo e focos (aba "Plano")
# ============================================================
class FocusItem(SQLModel):
    title: str
    detail: Optional[str] = None


class GoalIn(SQLModel):
    objective: Optional[str] = None
    target: Optional[str] = None
    phases: List[str] = []
    focuses: List[FocusItem] = []
    coach_note: Optional[str] = None


class GoalOut(SQLModel):
    athlete_id: int
    objective: Optional[str]
    target: Optional[str]
    phases: List[str]
    focuses: List[FocusItem]
    coach_note: Optional[str]
    updated_at: datetime


def _goal_out(g: TrainingGoal) -> GoalOut:
    return GoalOut(
        athlete_id=g.athlete_id,
        objective=g.objective,
        target=g.target,
        phases=list(g.phases or []),
        focuses=[FocusItem(**f) for f in (g.focuses or [])],
        coach_note=g.coach_note,
        updated_at=g.updated_at,
    )


def _goal_of(session: Session, athlete_id: int) -> Optional[TrainingGoal]:
    return session.exec(
        select(TrainingGoal).where(TrainingGoal.athlete_id == athlete_id)
    ).first()


@router.get("/athlete/goal", response_model=Optional[GoalOut])
def athlete_get_goal(
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    g = _goal_of(session, athlete.id)
    return _goal_out(g) if g else None


@router.get("/coach/athletes/{athlete_id}/goal", response_model=Optional[GoalOut])
def coach_get_goal(
    athlete_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    _owned_athlete(session, coach, athlete_id)
    g = _goal_of(session, athlete_id)
    return _goal_out(g) if g else None


@router.put("/coach/athletes/{athlete_id}/goal", response_model=GoalOut)
def coach_set_goal(
    athlete_id: int,
    payload: GoalIn,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    _owned_athlete(session, coach, athlete_id)
    g = _goal_of(session, athlete_id) or TrainingGoal(athlete_id=athlete_id)
    g.coach_id = coach.id
    g.objective = _clean(payload.objective)
    g.target = _clean(payload.target)
    g.phases = [p.strip() for p in payload.phases if p and p.strip()]
    g.focuses = [
        {"title": f.title.strip(), "detail": _clean(f.detail)}
        for f in payload.focuses
        if f.title and f.title.strip()
    ]
    g.coach_note = _clean(payload.coach_note)
    g.updated_at = _now()
    session.add(g)
    session.commit()
    session.refresh(g)
    return _goal_out(g)


# ============================================================
# Contato da coach (botão do WhatsApp na aba "Eu")
# ============================================================
class CoachContactOut(SQLModel):
    name: Optional[str] = None
    whatsapp: Optional[str] = None


class WhatsappIn(SQLModel):
    whatsapp: Optional[str] = None


@router.get("/athlete/coach", response_model=CoachContactOut)
def athlete_get_coach(
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    coach = session.get(User, athlete.coach_id) if athlete.coach_id else None
    if not coach:
        return CoachContactOut()
    return CoachContactOut(name=coach.name, whatsapp=coach.whatsapp)


@router.put("/coach/me/whatsapp", response_model=CoachContactOut)
def coach_set_own_whatsapp(
    payload: WhatsappIn,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    coach.whatsapp = _clean(payload.whatsapp)
    session.add(coach)
    session.commit()
    session.refresh(coach)
    return CoachContactOut(name=coach.name, whatsapp=coach.whatsapp)
