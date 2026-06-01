"""Helpers para o JSON de planilhas (`plan` da TrainingSheet).

  - normalize_plan_for_sheet: resolve nomes pra exercise_id, normaliza séries.
  - resolve_exercise_id_by_name: lookup por nome normalizado.
  - compute_end_date: data final = start + weeks*7 - 1.
  - build_default_plan: scaffold inicial de plano (todos os dias, sem exercícios).
"""
import json
import re
from datetime import date, timedelta
from typing import Optional

from sqlmodel import Session, select

from models import Exercise


def compute_end_date(start_date: date, weeks: int) -> date:
    weeks = int(weeks or 4)
    if weeks <= 1:
        weeks = 1
    return start_date + timedelta(days=weeks * 7 - 1)


def build_default_plan(weeks: int, same_weeks: bool) -> dict:
    days_order = [
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday",
    ]

    def make_week(week_number: int):
        return {
            "week_number": week_number,
            "days": [
                {"day": day, "rest": False, "coach_notes": "", "exercises": []}
                for day in days_order
            ],
        }

    base_week = make_week(1)

    if same_weeks:
        weeks_list = []
        for i in range(weeks):
            week_copy = json.loads(json.dumps(base_week))
            week_copy["week_number"] = i + 1
            weeks_list.append(week_copy)
    else:
        weeks_list = [make_week(i + 1) for i in range(weeks)]

    return {"weeks": weeks_list}


def _norm_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("&", "and")
    s = re.sub(r"\s+", " ", s)
    return s


def resolve_exercise_id_by_name(
    session: Session,
    *,
    coach_id: int,
    name: str,
    ex_type: str,  # "lpo" | "accessory"
) -> Optional[int]:
    nn = _norm_name(name)
    if not nn:
        return None

    # globais + do coach
    candidates = session.exec(
        select(Exercise).where(
            Exercise.is_active == True,
            Exercise.type == ex_type,
            (Exercise.coach_id == None) | (Exercise.coach_id == coach_id),
        )
    ).all()

    hits = [e for e in candidates if _norm_name(e.name) == nn]
    if len(hits) == 1:
        return hits[0].id
    return None


def normalize_plan_for_sheet(
    session: Session,
    *,
    coach_id: int,
    raw_plan: dict,
) -> dict:
    """Normaliza o plano antes de salvar/retornar.

    - Migra do formato antigo ("exercises") pro novo ("lpo_exercises").
    - Resolve exercise_id por nome quando faltar.
    - Garante shape consistente de séries e flags de acessório.
    """
    plan = raw_plan or {}
    weeks = plan.get("weeks") or []

    for w in weeks:
        days = w.get("days") or []
        for d in days:
            d["coach_notes"] = d.get("coach_notes") or ""

            if "lpo_exercises" not in d:
                d["lpo_exercises"] = d.get("exercises") or []
            if "accessories" not in d:
                d["accessories"] = []

            # ---- LPO ----
            normalized_lpo = []
            for ex in (d.get("lpo_exercises") or []):
                name = (ex.get("name") or "").strip()
                if not name:
                    continue

                ex["series"] = ex.get("series") or []

                is_complex = bool(ex.get("is_complex"))
                if not is_complex:
                    if ex.get("exercise_id") in (None, "", 0):
                        found = resolve_exercise_id_by_name(
                            session,
                            coach_id=coach_id,
                            name=name,
                            ex_type="lpo",
                        )
                        if found:
                            ex["exercise_id"] = found

                normalized_lpo.append(ex)

            d["lpo_exercises"] = normalized_lpo
            # compat com telas antigas
            d["exercises"] = d["lpo_exercises"]

            # ---- Accessories ----
            normalized_acc = []
            for ax in (d.get("accessories") or []):
                name = (ax.get("name") or "").strip()
                if not name:
                    continue

                ax["series"] = ax.get("series") or []
                ax["allow_weight_input"] = bool(ax.get("allow_weight_input", True))

                # acessórios não têm percent
                for s in ax["series"]:
                    s.pop("percent", None)

                if ax.get("exercise_id") in (None, "", 0):
                    found = resolve_exercise_id_by_name(
                        session,
                        coach_id=coach_id,
                        name=name,
                        ex_type="accessory",
                    )
                    if found:
                        ax["exercise_id"] = found

                normalized_acc.append(ax)

            d["accessories"] = normalized_acc

    return {"weeks": weeks}
