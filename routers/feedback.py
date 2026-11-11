"""Rotas de acompanhamento (check-ins, correções de vídeo e plano do atleta).

Atleta:
  - GET  /athlete/checkins/current          → check-in desta semana (ou null) + tipo esperado
  - POST /athlete/checkins                  → responde/atualiza o check-in da semana
  - GET  /athlete/checkins                  → histórico
  - POST /athlete/videos                    → envia vídeo de um exercício
  - GET  /athlete/videos                    → meus vídeos + correções
  - GET  /athlete/corrections/pending       → card "Antes de começar" (corrigidos e não lidos)
  - POST /athlete/videos/{id}/ack           → "Entendi, vou aplicar hoje"
  - GET  /athlete/plan                      → plano contratado (aba "Eu")

Coach:
  - GET  /coach/checkins?week_start=AAAA-MM-DD → check-ins da semana + quem falta
  - POST /coach/checkins/{id}/seen          → marca como visto (resposta opcional)
  - GET  /coach/videos?status=pendente      → fila de vídeos
  - POST /coach/videos/{id}/corrections     → envia correções (marca como corrigido)
  - GET  /coach/athletes/{id}/plan          → plano do atleta
  - PUT  /coach/athletes/{id}/plan          → define/atualiza plano

Os arquivos (vídeo e áudio) chegam como URL: o upload em si fica num storage
externo (ver README da PR). O backend só guarda o endereço.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlmodel import Session, SQLModel, select

from db import get_session
from models import (
    AthletePlan,
    User,
    VideoCorrection,
    VideoSubmission,
    WeeklyCheckin,
)
from security import require_role
from services.clock import today_br
from services.notify import notify_coach

router = APIRouter(tags=["feedback"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _owned_athlete(session: Session, coach: User, athlete_id: int) -> User:
    athlete = session.get(User, athlete_id)
    if not athlete or athlete.role != "athlete":
        raise HTTPException(status_code=404, detail="Atleta não encontrado.")
    if athlete.coach_id != coach.id:
        raise HTTPException(status_code=403, detail="Este atleta não pertence a você.")
    return athlete


# ============================================================
# Schemas
# ============================================================
class CheckinIn(SQLModel):
    kind: Optional[str] = None  # "inicio_mes" | "semanal"; None = o backend decide
    answers: Dict = {}
    has_pain: bool = False
    pain_note: Optional[str] = None
    needs_attention: bool = False
    athlete_note: Optional[str] = None


class CheckinOut(SQLModel):
    id: int
    athlete_id: int
    athlete_name: Optional[str] = None
    week_start: date
    kind: str
    answers: Dict
    has_pain: bool
    pain_note: Optional[str]
    needs_attention: bool
    athlete_note: Optional[str]
    coach_seen_at: Optional[datetime]
    coach_reply: Optional[str]
    created_at: datetime


class CurrentCheckinOut(SQLModel):
    week_start: date
    expected_kind: str
    checkin: Optional[CheckinOut]


class CoachCheckinsOut(SQLModel):
    week_start: date
    answered: List[CheckinOut]
    missing: List[Dict]  # [{id, name}]


class SeenIn(SQLModel):
    reply: Optional[str] = None


class VideoIn(SQLModel):
    exercise_name: str
    video_url: str
    training_sheet_id: Optional[int] = None
    week_number: Optional[int] = None
    day: Optional[str] = None
    athlete_note: Optional[str] = None
    compare_to_id: Optional[int] = None


class CorrectionIn(SQLModel):
    title: str
    detail: Optional[str] = None
    timestamp_sec: Optional[float] = None
    audio_url: Optional[str] = None
    audio_duration_sec: Optional[float] = None
    is_focus: bool = False
    drawing: Optional[list] = None


_SHAPES = {"line", "circle", "free", "arrow"}


def _clean_drawing(raw) -> Optional[list]:
    """Aceita só formas conhecidas, com pontos entre 0 e 1 (limita tamanho)."""
    if not isinstance(raw, list):
        return None
    out = []
    for sh in raw[:40]:
        if not isinstance(sh, dict) or sh.get("t") not in _SHAPES:
            continue
        pts = []
        for p in (sh.get("p") or [])[:400]:
            try:
                x, y = float(p[0]), float(p[1])
            except (TypeError, ValueError, IndexError):
                continue
            pts.append([round(min(1.0, max(0.0, x)), 4), round(min(1.0, max(0.0, y)), 4)])
        if len(pts) < 2:
            continue
        color = str(sh.get("c") or "#FF4D4D")[:9]
        if not color.startswith("#"):
            color = "#FF4D4D"
        out.append({"t": sh["t"], "c": color, "p": pts})
    return out or None


class CorrectionsIn(SQLModel):
    corrections: List[CorrectionIn]


class CorrectionOut(CorrectionIn):
    id: int


class VideoOut(SQLModel):
    id: int
    athlete_id: int
    athlete_name: Optional[str] = None
    exercise_name: str
    video_url: str
    training_sheet_id: Optional[int]
    week_number: Optional[int]
    day: Optional[str]
    athlete_note: Optional[str]
    compare_to_id: Optional[int]
    status: str
    corrected_at: Optional[datetime]
    acknowledged_at: Optional[datetime]
    created_at: datetime
    corrections: List[CorrectionOut] = []


class PlanIn(SQLModel):
    plan_name: str
    months_total: Optional[int] = None
    monthly_price: Optional[float] = None
    show_price_to_athlete: bool = True
    start_date: Optional[date] = None
    notes: Optional[str] = None


class PlanOut(SQLModel):
    plan_name: str
    months_total: Optional[int]
    current_month: int
    monthly_price: Optional[float]
    start_date: date
    notes: Optional[str]


# ============================================================
# Helpers de serialização
# ============================================================
def _checkin_out(c: WeeklyCheckin, name: Optional[str] = None) -> CheckinOut:
    return CheckinOut(**c.model_dump(), athlete_name=name)


def _video_out(session: Session, v: VideoSubmission, name: Optional[str] = None) -> VideoOut:
    corr = session.exec(
        select(VideoCorrection)
        .where(VideoCorrection.submission_id == v.id)
        .order_by(VideoCorrection.is_focus.desc(), VideoCorrection.id)
    ).all()
    return VideoOut(
        **v.model_dump(),
        athlete_name=name,
        corrections=[CorrectionOut(**c.model_dump()) for c in corr],
    )


def _expected_kind(session: Session, athlete_id: int, week_start: date) -> str:
    """Semana 1 do mês (ou primeiro check-in) → "inicio_mes"; senão "semanal"."""
    if week_start.day <= 7:
        return "inicio_mes"
    has_any = session.exec(
        select(WeeklyCheckin.id).where(WeeklyCheckin.athlete_id == athlete_id)
    ).first()
    return "semanal" if has_any else "inicio_mes"


def _months_between(start: date, today: date) -> int:
    return (today.year - start.year) * 12 + (today.month - start.month) - (
        1 if today.day < start.day else 0
    )


# ============================================================
# Atleta — check-ins
# ============================================================
@router.get("/athlete/checkins/current", response_model=CurrentCheckinOut)
def athlete_current_checkin(
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    week = _monday(today_br())
    c = session.exec(
        select(WeeklyCheckin).where(
            WeeklyCheckin.athlete_id == athlete.id, WeeklyCheckin.week_start == week
        )
    ).first()
    return CurrentCheckinOut(
        week_start=week,
        expected_kind=c.kind if c else _expected_kind(session, athlete.id, week),
        checkin=_checkin_out(c) if c else None,
    )


@router.post("/athlete/checkins", response_model=CheckinOut)
def athlete_submit_checkin(
    payload: CheckinIn,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    week = _monday(today_br())
    c = session.exec(
        select(WeeklyCheckin).where(
            WeeklyCheckin.athlete_id == athlete.id, WeeklyCheckin.week_start == week
        )
    ).first()
    if c is None:
        c = WeeklyCheckin(
            athlete_id=athlete.id,
            coach_id=athlete.coach_id,
            week_start=week,
            kind=payload.kind or _expected_kind(session, athlete.id, week),
        )
    elif payload.kind:
        c.kind = payload.kind
    c.answers = payload.answers or {}
    c.has_pain = payload.has_pain
    c.pain_note = (payload.pain_note or "").strip() or None if payload.has_pain else None
    c.needs_attention = payload.needs_attention or payload.has_pain
    c.athlete_note = (payload.athlete_note or "").strip() or None
    c.updated_at = _now()
    # Editou depois que a coach viu → volta pra "não visto".
    c.coach_seen_at = None
    session.add(c)
    session.commit()
    session.refresh(c)
    first = (athlete.name or "Atleta").split(" ")[0]
    if c.has_pain:
        body = f"{first} marcou dor" + (f": {c.pain_note}" if c.pain_note else ".")
    elif c.needs_attention:
        body = f"{first} respondeu com nota baixa. Vale olhar."
    else:
        body = f"{first} respondeu o check-in da semana."
    background.add_task(notify_coach, "Check-in novo", body, "warning" if c.needs_attention else "clipboard")
    return _checkin_out(c)


@router.get("/athlete/checkins", response_model=List[CheckinOut])
def athlete_list_checkins(
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    rows = session.exec(
        select(WeeklyCheckin)
        .where(WeeklyCheckin.athlete_id == athlete.id)
        .order_by(WeeklyCheckin.week_start.desc())
    ).all()
    return [_checkin_out(c) for c in rows]


# ============================================================
# Atleta — vídeos e correções
# ============================================================
class UploadUrlIn(SQLModel):
    filename: Optional[str] = None  # ex.: "agachamento.mov" (só pra extensão)
    content_type: str = "video/mp4"
    size_bytes: Optional[int] = None


class UploadUrlOut(SQLModel):
    put_url: str
    public_url: str
    key: str
    expires_in: int
    max_bytes: int


@router.post("/athlete/videos/upload-url", response_model=UploadUrlOut)
def athlete_video_upload_url(
    payload: UploadUrlIn,
    athlete: User = Depends(require_role("athlete")),
):
    """Gera URL pre-assinada pro app subir vídeo direto pro R2.

    O app:
      1. Chama este endpoint
      2. Faz PUT no `put_url` com o arquivo binário no body (header
         Content-Type igual ao enviado aqui)
      3. Depois chama POST /athlete/videos com `public_url` como `video_url`
    """
    from config import VIDEO_MAX_MB
    from services.storage import (
        is_r2_configured,
        make_video_key,
        presigned_put_url,
        public_url_for,
    )

    if not is_r2_configured():
        raise HTTPException(
            status_code=503,
            detail="Upload de vídeo temporariamente indisponível. Avise o admin.",
        )

    max_bytes = VIDEO_MAX_MB * 1024 * 1024
    if payload.size_bytes is not None and payload.size_bytes > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Vídeo passa de {VIDEO_MAX_MB} MB. Comprime ou corta e tenta de novo.",
        )

    key = make_video_key(athlete.id, payload.filename)
    put_url = presigned_put_url(key, content_type=payload.content_type, expires_in=300)
    return UploadUrlOut(
        put_url=put_url,
        public_url=public_url_for(key),
        key=key,
        expires_in=300,
        max_bytes=max_bytes,
    )


@router.post("/athlete/videos", response_model=VideoOut)
def athlete_send_video(
    payload: VideoIn,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    if not payload.video_url.strip() or not payload.exercise_name.strip():
        raise HTTPException(status_code=422, detail="Informe o exercício e o vídeo.")
    if payload.compare_to_id is not None:
        prev = session.get(VideoSubmission, payload.compare_to_id)
        if not prev or prev.athlete_id != athlete.id:
            raise HTTPException(status_code=404, detail="Vídeo anterior não encontrado.")
    v = VideoSubmission(
        athlete_id=athlete.id,
        coach_id=athlete.coach_id,
        **payload.model_dump(),
    )
    v.exercise_name = v.exercise_name.strip()
    v.video_url = v.video_url.strip()
    session.add(v)
    session.commit()
    session.refresh(v)
    first = (athlete.name or "Atleta").split(" ")[0]
    background.add_task(
        notify_coach, "Vídeo novo pra corrigir", f"{first} mandou {v.exercise_name}.", "movie_camera"
    )
    return _video_out(session, v)


@router.get("/athlete/videos", response_model=List[VideoOut])
def athlete_list_videos(
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    rows = session.exec(
        select(VideoSubmission)
        .where(VideoSubmission.athlete_id == athlete.id)
        .order_by(VideoSubmission.created_at.desc())
    ).all()
    return [_video_out(session, v) for v in rows]


@router.get("/athlete/corrections/pending", response_model=List[VideoOut])
def athlete_pending_corrections(
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    rows = session.exec(
        select(VideoSubmission)
        .where(
            VideoSubmission.athlete_id == athlete.id,
            VideoSubmission.status == "corrigido",
            VideoSubmission.acknowledged_at.is_(None),
        )
        .order_by(VideoSubmission.corrected_at.desc())
    ).all()
    return [_video_out(session, v) for v in rows]


@router.post("/athlete/videos/{video_id}/ack", response_model=VideoOut)
def athlete_ack_video(
    video_id: int,
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    v = session.get(VideoSubmission, video_id)
    if not v or v.athlete_id != athlete.id:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    if v.acknowledged_at is None:
        v.acknowledged_at = _now()
        session.add(v)
        session.commit()
        session.refresh(v)
    return _video_out(session, v)


@router.get("/athlete/plan", response_model=Optional[PlanOut])
def athlete_get_plan(
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    p = session.exec(select(AthletePlan).where(AthletePlan.athlete_id == athlete.id)).first()
    if not p:
        return None
    out = _plan_out(p)
    if not p.show_price_to_athlete:
        out.monthly_price = None
    return out


def _plan_out(p: AthletePlan) -> PlanOut:
    current = max(1, _months_between(p.start_date, today_br()) + 1)
    if p.months_total:
        current = min(current, p.months_total)
    return PlanOut(
        plan_name=p.plan_name,
        months_total=p.months_total,
        current_month=current,
        monthly_price=p.monthly_price,
        start_date=p.start_date,
        notes=p.notes,
    )


# ============================================================
# Coach — check-ins
# ============================================================
@router.get("/coach/checkins", response_model=CoachCheckinsOut)
def coach_list_checkins(
    week_start: Optional[date] = Query(default=None),
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    week = _monday(week_start or today_br())
    athletes = session.exec(
        select(User).where(User.role == "athlete", User.coach_id == coach.id)
    ).all()
    names = {a.id: a.name for a in athletes}
    rows = session.exec(
        select(WeeklyCheckin).where(
            WeeklyCheckin.week_start == week,
            WeeklyCheckin.athlete_id.in_(list(names) or [-1]),
        )
    ).all()
    # Quem precisa de atenção primeiro, depois os não vistos.
    rows = sorted(
        rows,
        key=lambda c: (not c.needs_attention, c.coach_seen_at is not None, names.get(c.athlete_id, "")),
    )
    answered_ids = {c.athlete_id for c in rows}
    return CoachCheckinsOut(
        week_start=week,
        answered=[_checkin_out(c, names.get(c.athlete_id)) for c in rows],
        missing=[
            {"id": a.id, "name": a.name}
            for a in sorted(athletes, key=lambda a: a.name)
            if a.id not in answered_ids
        ],
    )


@router.post("/coach/checkins/{checkin_id}/seen", response_model=CheckinOut)
def coach_mark_checkin_seen(
    checkin_id: int,
    payload: SeenIn,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    c = session.get(WeeklyCheckin, checkin_id)
    if not c:
        raise HTTPException(status_code=404, detail="Check-in não encontrado.")
    athlete = _owned_athlete(session, coach, c.athlete_id)
    c.coach_seen_at = _now()
    if payload.reply is not None:
        c.coach_reply = payload.reply.strip() or None
    session.add(c)
    session.commit()
    session.refresh(c)
    return _checkin_out(c, athlete.name)


# ============================================================
# Coach — vídeos
# ============================================================
@router.post("/coach/audio/upload-url", response_model=UploadUrlOut)
def coach_audio_upload_url(
    payload: UploadUrlIn,
    coach: User = Depends(require_role("coach")),
):
    """URL pre-assinada pra coach subir o áudio da correção direto pro R2.

    Mesmo fluxo do vídeo do atleta: o app faz PUT no `put_url` com o áudio
    (Content-Type igual ao enviado aqui) e manda o `public_url` como
    `audio_url` em POST /coach/videos/{id}/corrections.
    """
    from config import AUDIO_MAX_MB
    from services.storage import (
        AUDIO_EXT_BY_TYPE,
        is_r2_configured,
        make_audio_key,
        presigned_put_url,
        public_url_for,
    )

    base_type = (payload.content_type or "").split(";")[0].strip().lower()
    if base_type not in AUDIO_EXT_BY_TYPE:
        raise HTTPException(status_code=422, detail="Formato de áudio não aceito.")
    if not is_r2_configured():
        raise HTTPException(
            status_code=503,
            detail="Envio de áudio temporariamente indisponível. Avise o admin.",
        )
    max_bytes = AUDIO_MAX_MB * 1024 * 1024
    if payload.size_bytes is not None and payload.size_bytes > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Áudio passa de {AUDIO_MAX_MB} MB. Grava um áudio mais curto.",
        )
    key = make_audio_key(coach.id, base_type)
    put_url = presigned_put_url(key, content_type=base_type, expires_in=300)
    return UploadUrlOut(
        put_url=put_url,
        public_url=public_url_for(key),
        key=key,
        expires_in=300,
        max_bytes=max_bytes,
    )


# ============================================================
# Coach — fila de vídeos
# ============================================================
@router.get("/coach/videos", response_model=List[VideoOut])
def coach_list_videos(
    status: Optional[str] = Query(default="pendente"),
    athlete_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    athletes = session.exec(
        select(User).where(User.role == "athlete", User.coach_id == coach.id)
    ).all()
    names = {a.id: a.name for a in athletes}
    stmt = select(VideoSubmission).where(VideoSubmission.athlete_id.in_(list(names) or [-1]))
    if status:
        stmt = stmt.where(VideoSubmission.status == status)
    if athlete_id is not None:
        stmt = stmt.where(VideoSubmission.athlete_id == athlete_id)
    # Fila: mais antigo primeiro (quem esperou mais é atendido antes).
    stmt = stmt.order_by(VideoSubmission.created_at.asc())
    return [_video_out(session, v, names.get(v.athlete_id)) for v in session.exec(stmt).all()]


@router.post("/coach/videos/{video_id}/corrections", response_model=VideoOut)
def coach_send_corrections(
    video_id: int,
    payload: CorrectionsIn,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    v = session.get(VideoSubmission, video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    athlete = _owned_athlete(session, coach, v.athlete_id)
    if not payload.corrections:
        raise HTTPException(status_code=422, detail="Inclua pelo menos uma correção.")
    for item in payload.corrections:
        if not item.title.strip():
            raise HTTPException(status_code=422, detail="Toda correção precisa de um título.")
        data = item.model_dump()
        data["drawing"] = _clean_drawing(data.get("drawing"))
        session.add(VideoCorrection(submission_id=v.id, **data))
    v.status = "corrigido"
    v.corrected_at = _now()
    v.acknowledged_at = None  # correção nova → aparece de novo pro atleta
    session.add(v)
    session.commit()
    session.refresh(v)
    return _video_out(session, v, athlete.name)


@router.post("/coach/files/pdf-upload-url", response_model=UploadUrlOut)
def coach_pdf_upload_url(
    payload: UploadUrlIn,
    coach: User = Depends(require_role("coach")),
):
    """URL pra coach subir um PDF (ex.: diagnóstico técnico) direto pro R2."""
    import secrets

    import services.storage as storage

    if (payload.content_type or "").split(";")[0].strip().lower() != "application/pdf":
        raise HTTPException(status_code=422, detail="Envie um arquivo PDF.")
    if not storage.is_r2_configured():
        raise HTTPException(status_code=503, detail="Envio de arquivo temporariamente indisponível. Avise o admin.")
    if payload.size_bytes and payload.size_bytes > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="O PDF passa de 25 MB. Tente um arquivo menor.")
    key = f"docs/{coach.id}/{secrets.token_hex(8)}.pdf"
    return UploadUrlOut(
        put_url=storage.presigned_put_url(key, "application/pdf", expires_in=900),
        public_url=storage.public_url_for(key),
        key=key,
        expires_in=900,
        max_bytes=25 * 1024 * 1024,
    )


# ============================================================
# Coach — ficha do atleta: histórico de check-ins e exclusões
# ============================================================
@router.get("/coach/athletes/{athlete_id}/checkins", response_model=List[CheckinOut])
def coach_athlete_checkins(
    athlete_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    """Todos os check-ins do atleta, do mais novo pro mais antigo."""
    athlete = _owned_athlete(session, coach, athlete_id)
    rows = session.exec(
        select(WeeklyCheckin)
        .where(WeeklyCheckin.athlete_id == athlete.id)
        .order_by(WeeklyCheckin.week_start.desc())
    ).all()
    return [_checkin_out(c, athlete.name) for c in rows]


@router.delete("/coach/checkins/{checkin_id}")
def coach_delete_checkin(
    checkin_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    c = session.get(WeeklyCheckin, checkin_id)
    if not c:
        raise HTTPException(status_code=404, detail="Check-in não encontrado.")
    _owned_athlete(session, coach, c.athlete_id)
    session.delete(c)
    session.commit()
    return {"ok": True}


@router.delete("/coach/videos/{video_id}")
def coach_delete_video(
    video_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    """Apaga o vídeo do atleta e as correções dele (o arquivo no R2 fica)."""
    v = session.get(VideoSubmission, video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    _owned_athlete(session, coach, v.athlete_id)
    for corr in session.exec(select(VideoCorrection).where(VideoCorrection.submission_id == v.id)).all():
        session.delete(corr)
    # Vídeos que comparavam com este perdem a referência.
    for other in session.exec(select(VideoSubmission).where(VideoSubmission.compare_to_id == v.id)).all():
        other.compare_to_id = None
        session.add(other)
    session.delete(v)
    session.commit()
    return {"ok": True}


# ============================================================
# Coach — plano do atleta
# ============================================================
@router.get("/coach/athletes/{athlete_id}/plan", response_model=Optional[PlanOut])
def coach_get_plan(
    athlete_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    _owned_athlete(session, coach, athlete_id)
    p = session.exec(select(AthletePlan).where(AthletePlan.athlete_id == athlete_id)).first()
    return _plan_out(p) if p else None


@router.put("/coach/athletes/{athlete_id}/plan", response_model=PlanOut)
def coach_set_plan(
    athlete_id: int,
    payload: PlanIn,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    _owned_athlete(session, coach, athlete_id)
    p = session.exec(select(AthletePlan).where(AthletePlan.athlete_id == athlete_id)).first()
    if p is None:
        p = AthletePlan(athlete_id=athlete_id, plan_name=payload.plan_name)
    p.plan_name = payload.plan_name.strip()
    p.months_total = payload.months_total
    p.monthly_price = payload.monthly_price
    p.show_price_to_athlete = payload.show_price_to_athlete
    if payload.start_date:
        p.start_date = payload.start_date
    p.notes = payload.notes
    p.updated_at = _now()
    session.add(p)
    session.commit()
    session.refresh(p)
    return _plan_out(p)
