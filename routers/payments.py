"""Pagamento da mensalidade.

Atleta (aba "Eu"):
  - GET  /athlete/payment                  → situação: em dia, vencendo, atrasado, trancado...
  - POST /athlete/payments/receipt-upload-url → URL pra subir o comprovante pro R2
  - POST /athlete/payments                 → "Já paguei" (com o comprovante)

Coach:
  - GET/PUT /coach/payment-settings        → chave Pix e links de cartão (Asaas) por plano
  - GET  /coach/payments                   → comprovantes pra conferir, vencendo e atrasados
  - POST /coach/payments/{id}/confirm      → "Recebi ✓" (o vencimento vai pro mês seguinte)
  - POST /coach/payments/{id}/reject       → pede outro comprovante
  - GET  /coach/athletes/{id}/payments     → histórico do atleta
  - POST /coach/athletes/{id}/payments     → "Recebi" sem comprovante (ex.: pagou no Asaas)

Regras:
  - O vencimento é um dia fixo do mês (`due_day`), combinado com cada atleta.
  - 3 dias antes: aviso. Mais de 2 dias de atraso: o treino tranca.
  - Mandou o comprovante: o treino libera na hora, enquanto a coach confere.
  - "integral": pagou o plano todo; sem aviso e sem cobrança até `vencimento`.
"""
import calendar
import re
import secrets
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, SQLModel, select

from db import get_session
from models import AthletePlan, CoachPaymentSettings, Payment, User
from security import require_role
from services.clock import today_br

router = APIRouter(tags=["payments"])

WARN_DAYS = 3  # aviso a partir de 3 dias antes
LOCK_AFTER_DAYS = 2  # tranca depois de 2 dias de atraso (no 3º dia)
RECEIPT_MAX_MB = 10
RECEIPT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
    "application/pdf": "pdf",
}
PIX_KEY_TYPES = ("cpf", "cnpj", "celular", "email", "aleatoria")


# ============================================================
# Regras
# ============================================================
def next_due(current: date, day: Optional[int]) -> date:
    """O mesmo dia combinado, no mês seguinte (dia 31 vira o último dia do mês)."""
    y, m = (current.year + 1, 1) if current.month == 12 else (current.year, current.month + 1)
    d = day or current.day
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def plan_key(plan: Optional[AthletePlan]) -> Optional[str]:
    """Plano do atleta → chave do link de cartão ("experience-3", "competicao"...)."""
    from routers.coach import PLAN_OPTIONS

    if not plan:
        return None
    for key, opt in PLAN_OPTIONS.items():
        # O nome salvo pode vir com a frequência: "Experience · 3x na semana".
        if opt["plan_name"] != plan.plan_name.split(" · ")[0].strip():
            continue
        if opt.get("flat_price") is not None:
            return key
        for freq, price in (opt.get("prices") or {}).items():
            if plan.monthly_price is not None and abs(price - plan.monthly_price) < 0.01:
                return f"{key}-{freq}"
    return None


def card_link_options() -> List[dict]:
    """Os planos que podem ter link de cartão, na ordem da tela da coach."""
    from routers.coach import PLAN_OPTIONS

    out = []
    for key, opt in PLAN_OPTIONS.items():
        if opt.get("flat_price") is not None:
            out.append({"key": key, "label": opt["plan_name"], "price": opt["flat_price"]})
        for freq, price in (opt.get("prices") or {}).items():
            out.append({"key": f"{key}-{freq}", "label": f"{opt['plan_name']} · {freq}x por semana", "price": price})
    return out


def normalize_pix_key(kind: str, key: str) -> str:
    key = (key or "").strip()
    if kind in ("cpf", "cnpj"):
        digits = re.sub(r"\D", "", key)
        if len(digits) != (11 if kind == "cpf" else 14):
            raise HTTPException(status_code=422, detail=f"Confira o {kind.upper()} da chave Pix.")
        return digits
    if kind == "celular":
        digits = re.sub(r"\D", "", key)
        if len(digits) in (10, 11):
            digits = "55" + digits
        if len(digits) not in (12, 13) or not digits.startswith("55"):
            raise HTTPException(status_code=422, detail="Confira o celular da chave Pix (com DDD).")
        return "+" + digits
    if kind == "email":
        if "@" not in key:
            raise HTTPException(status_code=422, detail="Confira o e-mail da chave Pix.")
        return key.lower()
    return key.lower()


def _settings(session: Session, coach_id: Optional[int]) -> Optional[CoachPaymentSettings]:
    if coach_id is None:
        return None
    return session.exec(select(CoachPaymentSettings).where(CoachPaymentSettings.coach_id == coach_id)).first()


def _plan(session: Session, athlete_id: int) -> Optional[AthletePlan]:
    return session.exec(select(AthletePlan).where(AthletePlan.athlete_id == athlete_id)).first()


def _payments(session: Session, athlete_id: int) -> List[Payment]:
    return list(
        session.exec(
            select(Payment).where(Payment.athlete_id == athlete_id).order_by(Payment.created_at.desc(), Payment.id.desc())
        ).all()
    )


class PaymentOut(SQLModel):
    id: int
    athlete_id: int
    athlete_name: Optional[str] = None
    due_date: Optional[date] = None
    amount: Optional[float] = None
    method: str
    receipt_url: Optional[str] = None
    status: str
    coach_note: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None


def _out(p: Payment, name: Optional[str] = None) -> PaymentOut:
    return PaymentOut(**p.model_dump(), athlete_name=name)


class PaymentStatus(SQLModel):
    # integral | sem_data | em_dia | vencendo | atrasado | em_analise
    state: str
    due_date: Optional[date] = None
    days: Optional[int] = None  # dias até o vencimento (negativo = atrasado)
    amount: Optional[float] = None
    plan_name: Optional[str] = None
    locked: bool = False
    lock_after_days: int = LOCK_AFTER_DAYS
    warn_days: int = WARN_DAYS
    pix_code: Optional[str] = None  # "copia e cola"
    pix_key: Optional[str] = None
    pix_name: Optional[str] = None
    card_link: Optional[str] = None
    pending: Optional[PaymentOut] = None
    rejected_note: Optional[str] = None


def payment_status(session: Session, athlete: User, today: Optional[date] = None) -> PaymentStatus:
    today = today or today_br()
    plan = _plan(session, athlete.id)
    amount = plan.monthly_price if plan else None
    due = athlete.vencimento
    hist = _payments(session, athlete.id)
    pending = next((p for p in hist if p.status == "enviado"), None)
    last = hist[0] if hist else None

    if (athlete.payment_mode or "mensal") == "integral":
        return PaymentStatus(state="integral", due_date=due, plan_name=plan.plan_name if plan else None)
    if due is None:
        return PaymentStatus(state="sem_data", amount=amount, plan_name=plan.plan_name if plan else None)

    days = (due - today).days
    if pending:
        state = "em_analise"
    elif days > WARN_DAYS:
        state = "em_dia"
    elif days >= 0:
        state = "vencendo"
    else:
        state = "atrasado"
    locked = pending is None and -days > LOCK_AFTER_DAYS

    st = _settings(session, athlete.coach_id)
    pix_code = None
    if st and st.pix_key:
        from services.pix import pix_copia_e_cola

        pix_code = pix_copia_e_cola(st.pix_key, st.pix_name or "", st.pix_city or "", amount)
    card_link = athlete.payment_link or ((st.card_links or {}).get(plan_key(plan) or "") if st else None) or None

    return PaymentStatus(
        state=state,
        due_date=due,
        days=days,
        amount=amount,
        plan_name=plan.plan_name if plan else None,
        locked=locked,
        pix_code=pix_code,
        pix_key=st.pix_key if st else None,
        pix_name=st.pix_name if st else None,
        card_link=card_link,
        pending=_out(pending) if pending else None,
        rejected_note=(last.coach_note or "") if last and last.status == "recusado" else None,
    )


def _confirm(session: Session, athlete: User, p: Payment) -> None:
    """Marca como recebido e, se quitou o vencimento atual, passa pro mês seguinte."""
    p.status = "confirmado"
    p.coach_note = None
    p.reviewed_at = datetime.now(timezone.utc)
    session.add(p)
    if (athlete.payment_mode or "mensal") == "mensal" and athlete.vencimento and p.due_date == athlete.vencimento:
        athlete.vencimento = next_due(athlete.vencimento, athlete.due_day)
        session.add(athlete)


# ============================================================
# Atleta
# ============================================================
@router.get("/athlete/payment", response_model=PaymentStatus)
def athlete_payment(
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    return payment_status(session, athlete)


class ReceiptUploadIn(SQLModel):
    content_type: str
    size_bytes: Optional[int] = None


class ReceiptUploadOut(SQLModel):
    put_url: str
    public_url: str
    content_type: str


@router.post("/athlete/payments/receipt-upload-url", response_model=ReceiptUploadOut)
def athlete_receipt_upload_url(
    payload: ReceiptUploadIn,
    athlete: User = Depends(require_role("athlete")),
):
    import services.storage as storage

    ctype = (payload.content_type or "").split(";")[0].strip().lower()
    if ctype == "image/jpg":
        ctype = "image/jpeg"
    ext = RECEIPT_TYPES.get(ctype)
    if not ext:
        raise HTTPException(status_code=422, detail="Envie uma foto ou um PDF do comprovante.")
    if payload.size_bytes and payload.size_bytes > RECEIPT_MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"O arquivo passa de {RECEIPT_MAX_MB} MB.")
    if not storage.is_r2_configured():
        raise HTTPException(status_code=503, detail="Envio de arquivo temporariamente indisponível. Avise a coach.")
    key = f"receipts/{athlete.id}/{secrets.token_hex(16)}.{ext}"
    return ReceiptUploadOut(
        put_url=storage.presigned_put_url(key, ctype, expires_in=600),
        public_url=storage.public_url_for(key),
        content_type=ctype,
    )


class PaymentIn(SQLModel):
    receipt_url: str
    method: str = "pix"


@router.post("/athlete/payments", response_model=PaymentStatus)
def athlete_paid(
    payload: PaymentIn,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    athlete: User = Depends(require_role("athlete")),
):
    """"Já paguei": precisa do comprovante. O treino libera na hora."""
    url = (payload.receipt_url or "").strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=422, detail="Anexe o comprovante do pagamento.")
    if (athlete.payment_mode or "mensal") == "integral":
        raise HTTPException(status_code=400, detail="Seu plano já está pago.")
    method = payload.method if payload.method in ("pix", "cartao", "outro") else "outro"
    plan = _plan(session, athlete.id)
    pending = next((p for p in _payments(session, athlete.id) if p.status == "enviado"), None)
    p = pending or Payment(athlete_id=athlete.id, coach_id=athlete.coach_id)
    p.due_date = athlete.vencimento
    p.amount = plan.monthly_price if plan else None
    p.method = method
    p.receipt_url = url
    p.created_at = datetime.now(timezone.utc)
    session.add(p)
    session.commit()

    from services.notify import notify_coach

    first = (athlete.name or "").split(" ")[0]
    background.add_task(
        notify_coach,
        f"Comprovante de {first}",
        f"{athlete.name} mandou o comprovante do pagamento. Confira em Pagamentos.",
        "moneybag",
    )
    return payment_status(session, athlete)


# ============================================================
# Coach
# ============================================================
class SettingsIn(SQLModel):
    pix_key_type: Optional[str] = None
    pix_key: Optional[str] = None
    pix_name: Optional[str] = None
    pix_city: Optional[str] = None
    card_links: Optional[Dict[str, str]] = None


class SettingsOut(SQLModel):
    pix_key: Optional[str] = None
    pix_name: Optional[str] = None
    pix_city: Optional[str] = None
    card_links: Dict[str, str] = {}
    plans: List[dict] = []  # planos que podem ter link de cartão
    pix_preview: Optional[str] = None


def _settings_out(st: Optional[CoachPaymentSettings]) -> SettingsOut:
    preview = None
    if st and st.pix_key:
        from services.pix import pix_copia_e_cola

        preview = pix_copia_e_cola(st.pix_key, st.pix_name or "", st.pix_city or "", None)
    return SettingsOut(
        pix_key=st.pix_key if st else None,
        pix_name=st.pix_name if st else None,
        pix_city=st.pix_city if st else None,
        card_links=dict(st.card_links or {}) if st else {},
        plans=card_link_options(),
        pix_preview=preview,
    )


@router.get("/coach/payment-settings", response_model=SettingsOut)
def get_payment_settings(
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    return _settings_out(_settings(session, coach.id))


@router.put("/coach/payment-settings", response_model=SettingsOut)
def put_payment_settings(
    payload: SettingsIn,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    st = _settings(session, coach.id) or CoachPaymentSettings(coach_id=coach.id, card_links={})
    sent = payload.model_fields_set
    if "pix_key" in sent:
        key = (payload.pix_key or "").strip()
        if key:
            kind = payload.pix_key_type or "aleatoria"
            if kind not in PIX_KEY_TYPES:
                raise HTTPException(status_code=422, detail="Tipo de chave Pix inválido.")
            st.pix_key = normalize_pix_key(kind, key)
        else:
            st.pix_key = None
    if "pix_name" in sent:
        st.pix_name = (payload.pix_name or "").strip() or None
    if "pix_city" in sent:
        st.pix_city = (payload.pix_city or "").strip() or None
    if st.pix_key and (not st.pix_name or not st.pix_city):
        raise HTTPException(status_code=422, detail="Informe o nome e a cidade de quem recebe o Pix.")
    if "card_links" in sent and payload.card_links is not None:
        valid = {o["key"] for o in card_link_options()}
        links = {}
        for k, v in payload.card_links.items():
            v = (v or "").strip()
            if k not in valid or not v:
                continue
            if not v.startswith("http"):
                raise HTTPException(status_code=422, detail="O link do cartão precisa começar com https://")
            links[k] = v
        st.card_links = links
    st.updated_at = datetime.now(timezone.utc)
    session.add(st)
    session.commit()
    session.refresh(st)
    return _settings_out(st)


class AthleteDue(SQLModel):
    athlete_id: int
    name: str
    whatsapp: Optional[str] = None
    due_date: date
    days: int
    amount: Optional[float] = None
    locked: bool = False


class PaymentsOverview(SQLModel):
    pending: List[PaymentOut]
    due_soon: List[AthleteDue]  # vencendo nos próximos 7 dias
    overdue: List[AthleteDue]


@router.get("/coach/payments", response_model=PaymentsOverview)
def coach_payments(
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    today = today_br()
    athletes = session.exec(select(User).where(User.role == "athlete", User.coach_id == coach.id)).all()
    by_id = {a.id: a for a in athletes}
    pending = [
        p
        for p in session.exec(
            select(Payment).where(Payment.coach_id == coach.id, Payment.status == "enviado").order_by(Payment.created_at)
        ).all()
        if p.athlete_id in by_id
    ]
    pending_ids = {p.athlete_id for p in pending}
    due_soon, overdue = [], []
    for a in athletes:
        if (a.payment_mode or "mensal") != "mensal" or not a.vencimento or a.id in pending_ids:
            continue
        days = (a.vencimento - today).days
        if days > 7:
            continue
        plan = _plan(session, a.id)
        row = AthleteDue(
            athlete_id=a.id,
            name=a.name,
            whatsapp=a.whatsapp,
            due_date=a.vencimento,
            days=days,
            amount=plan.monthly_price if plan else None,
            locked=-days > LOCK_AFTER_DAYS,
        )
        (overdue if days < 0 else due_soon).append(row)
    due_soon.sort(key=lambda r: r.days)
    overdue.sort(key=lambda r: r.days)
    return PaymentsOverview(
        pending=[_out(p, by_id[p.athlete_id].name) for p in pending],
        due_soon=due_soon,
        overdue=overdue,
    )


def _my_payment(session: Session, coach: User, payment_id: int):
    p = session.get(Payment, payment_id)
    athlete = session.get(User, p.athlete_id) if p else None
    if not p or not athlete or athlete.coach_id != coach.id:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado.")
    return p, athlete


@router.post("/coach/payments/{payment_id}/confirm", response_model=PaymentOut)
def confirm_payment(
    payment_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    p, athlete = _my_payment(session, coach, payment_id)
    if p.status != "confirmado":
        _confirm(session, athlete, p)
        session.commit()
        session.refresh(p)
    return _out(p, athlete.name)


class RejectIn(SQLModel):
    note: Optional[str] = None


@router.post("/coach/payments/{payment_id}/reject", response_model=PaymentOut)
def reject_payment(
    payment_id: int,
    payload: RejectIn,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    p, athlete = _my_payment(session, coach, payment_id)
    if p.status == "confirmado":
        raise HTTPException(status_code=400, detail="Esse pagamento já foi confirmado.")
    p.status = "recusado"
    p.coach_note = (payload.note or "").strip() or "Não consegui confirmar esse pagamento."
    p.reviewed_at = datetime.now(timezone.utc)
    session.add(p)
    session.commit()
    session.refresh(p)
    return _out(p, athlete.name)


class AthletePayments(SQLModel):
    status: PaymentStatus
    due_day: Optional[int] = None
    payment_mode: str = "mensal"
    payment_link: Optional[str] = None
    history: List[PaymentOut]


def _athlete_payments(session: Session, athlete: User) -> AthletePayments:
    return AthletePayments(
        status=payment_status(session, athlete),
        due_day=athlete.due_day,
        payment_mode=athlete.payment_mode or "mensal",
        payment_link=athlete.payment_link,
        history=[_out(p) for p in _payments(session, athlete.id)],
    )


@router.get("/coach/athletes/{athlete_id}/payments", response_model=AthletePayments)
def athlete_payments_for_coach(
    athlete_id: int,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    from routers.coach import _my_athlete

    return _athlete_payments(session, _my_athlete(session, coach, athlete_id))


class ManualIn(SQLModel):
    method: str = "outro"


@router.post("/coach/athletes/{athlete_id}/payments", response_model=AthletePayments)
def coach_mark_received(
    athlete_id: int,
    payload: ManualIn,
    session: Session = Depends(get_session),
    coach: User = Depends(require_role("coach")),
):
    """"Recebi" direto na ficha (pagou no cartão pelo Asaas, em dinheiro...)."""
    from routers.coach import _my_athlete

    athlete = _my_athlete(session, coach, athlete_id)
    if not athlete.vencimento or (athlete.payment_mode or "mensal") != "mensal":
        raise HTTPException(status_code=400, detail="Esse aluno não tem mensalidade pra receber.")
    hist = _payments(session, athlete.id)
    p = next((x for x in hist if x.status == "enviado"), None)
    if p is None:
        plan = _plan(session, athlete.id)
        p = Payment(
            athlete_id=athlete.id,
            coach_id=coach.id,
            due_date=athlete.vencimento,
            amount=plan.monthly_price if plan else None,
            method=payload.method if payload.method in ("pix", "cartao", "outro") else "outro",
        )
    else:
        p.due_date = athlete.vencimento
    _confirm(session, athlete, p)
    session.commit()
    session.refresh(athlete)
    return _athlete_payments(session, athlete)
