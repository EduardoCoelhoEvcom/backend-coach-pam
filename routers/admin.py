"""Visão geral do admin (somente role='admin').

  - GET /admin/overview → totais de usuários, resumo de pagamento, coaches com
    contagem de atletas, e atletas com dados de uso (tempo de conta, última
    atividade, total de treinos concluídos) + status de pagamento.

Sem dados financeiros por enquanto (não há valor de mensalidade no modelo).
"""
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from db import get_session
from models import TrainingDayCompletion, User
from security import require_role

router = APIRouter(tags=["admin"], prefix="/admin")


def _days_since(dt: Optional[datetime]) -> Optional[int]:
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    # dt pode vir sem tzinfo (sqlite) — normaliza pra UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (now - dt).days)


@router.get("/overview")
def admin_overview(
    _admin: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
):
    users = session.exec(select(User)).all()

    coaches = [u for u in users if u.role == "coach"]
    athletes = [u for u in users if u.role == "athlete"]
    admins = [u for u in users if u.role == "admin"]

    today = date.today()

    # ---- Resumo de pagamento (atletas) ----
    pay_counts: dict = {}
    overdue = 0
    for a in athletes:
        st = a.status_pagamento or "indefinido"
        pay_counts[st] = pay_counts.get(st, 0) + 1
        if a.vencimento and a.vencimento < today:
            overdue += 1

    # ---- Uso por atleta: total de treinos concluídos + última atividade ----
    rows = session.exec(
        select(
            TrainingDayCompletion.athlete_id,
            func.count(TrainingDayCompletion.id),
            func.max(TrainingDayCompletion.date_completed),
        ).group_by(TrainingDayCompletion.athlete_id)
    ).all()
    usage = {r[0]: {"total": int(r[1] or 0), "last": r[2]} for r in rows}

    coach_name_by_id = {c.id: c.name for c in coaches}

    # ---- Contagem de atletas por coach ----
    athletes_per_coach: dict = {}
    for a in athletes:
        if a.coach_id is not None:
            athletes_per_coach[a.coach_id] = athletes_per_coach.get(a.coach_id, 0) + 1

    coaches_out = [
        {
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "athlete_count": athletes_per_coach.get(c.id, 0),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in coaches
    ]

    athletes_out = []
    for a in athletes:
        u = usage.get(a.id, {})
        last = u.get("last")
        athletes_out.append({
            "id": a.id,
            "name": a.name,
            "email": a.email,
            "coach_id": a.coach_id,
            "coach_name": coach_name_by_id.get(a.coach_id),
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "days_since_signup": _days_since(a.created_at),
            "total_completed_days": u.get("total", 0),
            "last_activity": last.isoformat() if last else None,
            "status_pagamento": a.status_pagamento,
            "vencimento": a.vencimento.isoformat() if a.vencimento else None,
            "overdue": bool(a.vencimento and a.vencimento < today),
        })

    # ordena atletas: mais recentemente ativos primeiro, depois por nome
    athletes_out.sort(
        key=lambda x: (x["last_activity"] or "", x["name"] or ""),
        reverse=True,
    )

    return {
        "totals": {
            "users": len(users),
            "coaches": len(coaches),
            "athletes": len(athletes),
            "admins": len(admins),
        },
        "payment": {
            "by_status": pay_counts,
            "overdue": overdue,
        },
        "coaches": coaches_out,
        "athletes": athletes_out,
    }
