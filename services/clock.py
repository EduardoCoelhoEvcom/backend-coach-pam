"""Relógio do app: o "hoje" é o dia no Brasil (UTC-3), não o do servidor.

O servidor (Vercel) roda em UTC. Sem isso, um treino marcado depois das 21h
no Brasil caía no dia seguinte, e o "treino de hoje" se perdia.
O Brasil não tem horário de verão desde 2019, então o fuso fixo basta.
"""
from datetime import date, datetime, timedelta, timezone

BR_TZ = timezone(timedelta(hours=-3), name="America/Sao_Paulo")


def today_br() -> date:
    return datetime.now(BR_TZ).date()


def br_date_of(dt: datetime) -> date:
    """Dia no Brasil de um instante gravado em UTC (com ou sem fuso)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BR_TZ).date()
