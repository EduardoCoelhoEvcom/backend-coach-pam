"""Importação de planilhas em Excel (Coach Pâm).

Fluxo em 2 passos, sem salvar nada antes da confirmação:
  - POST /coach/import/preview  → sobe o .xlsx, devolve a prévia parseada de
    cada aba + a validação dos nomes contra a biblioteca (o que casou, o que
    não casou e, nos complexos, se cada parte existe).
  - POST /coach/import/apply    → recebe a aba escolhida (plano já parseado) +
    atleta + título + data de início e cria a planilha (1 atleta por vez).

O kg NÃO é importado: o app recalcula pelo RM de cada atleta. A resolução de
exercise_id por nome acontece quando a planilha é lida (normalize_plan_for_sheet).
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from db import get_session
from models import TrainingSheet, User
from security import require_role
from services.excel_import import is_complex_name, parse_workbook, split_complex
from services.training_plan import compute_end_date, resolve_exercise_id_by_name

router = APIRouter(tags=["coach-import"], prefix="/coach/import")

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


def _validate_names(session: Session, coach_id: int, names: List[str]) -> dict:
    """Para cada nome distinto diz se casa com a biblioteca.

    Complexos (nome com '+') são quebrados nas partes e cada parte é checada.
    """
    matched: List[str] = []
    unmatched: List[str] = []
    complexes: List[dict] = []

    for name in names:
        if is_complex_name(name):
            parts = []
            for p in split_complex(name):
                ex_id = resolve_exercise_id_by_name(
                    session, coach_id=coach_id, name=p, ex_type="lpo"
                )
                parts.append({"name": p, "exists": ex_id is not None})
            complexes.append({"name": name, "parts": parts})
        else:
            ex_id = resolve_exercise_id_by_name(
                session, coach_id=coach_id, name=name, ex_type="lpo"
            )
            (matched if ex_id is not None else unmatched).append(name)

    return {"matched": matched, "unmatched": unmatched, "complexes": complexes}


@router.post("/preview")
async def import_preview(
    file: UploadFile = File(...),
    current_coach: User = Depends(require_role("coach")),
    session: Session = Depends(get_session),
):
    fname = (file.filename or "").lower()
    if not fname.endswith((".xlsx", ".xlsm")):
        raise HTTPException(
            status_code=400,
            detail="Envie um arquivo Excel (.xlsx).",
        )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Arquivo grande demais (máx. 5 MB).")

    try:
        abas = parse_workbook(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"Não consegui ler o Excel: {exc}",
        )

    if not abas:
        raise HTTPException(status_code=400, detail="O arquivo não tem abas legíveis.")

    out = []
    for idx, ab in enumerate(abas):
        validation = _validate_names(session, current_coach.id, ab["exercises"])
        # resumo: total de exercícios e séries em todas as semanas
        total_ex = 0
        total_series = 0
        for w in ab["plan"]["weeks"]:
            for d in w["days"]:
                total_ex += len(d.get("lpo_exercises", []))
                for e in d.get("lpo_exercises", []):
                    total_series += len(e.get("series", []))
        out.append({
            "index": idx,
            "name": ab["name"],
            "title": ab["title"],
            "athletes": ab["athletes"],
            "weeks": ab["weeks"],
            "plan": ab["plan"],
            "exercises": ab["exercises"],
            "complexes": ab["complexes"],
            "validation": validation,
            "summary": {
                "total_exercises": total_ex,
                "total_series": total_series,
            },
        })

    return {"abas": out}


class ImportApplyRequest(BaseModel):
    athlete_id: int
    title: str
    start_date: date
    weeks: int
    plan: dict
    same_weeks: bool = False


@router.post("/apply")
def import_apply(
    body: ImportApplyRequest,
    current_coach: User = Depends(require_role("coach")),
    session: Session = Depends(get_session),
):
    athlete = session.get(User, body.athlete_id)
    if not athlete or athlete.role != "athlete":
        raise HTTPException(status_code=400, detail="Atleta inválido.")
    if athlete.coach_id != current_coach.id:
        raise HTTPException(
            status_code=403,
            detail="Este atleta não pertence a você.",
        )

    weeks = int(body.weeks or 1)
    if weeks < 1:
        weeks = 1

    plan = body.plan or {"weeks": []}
    if not isinstance(plan, dict) or "weeks" not in plan:
        raise HTTPException(status_code=400, detail="Plano inválido.")

    end = compute_end_date(body.start_date, weeks)

    sheet = TrainingSheet(
        athlete_id=body.athlete_id,
        coach_id=current_coach.id,
        title=body.title or "Planilha importada",
        weeks=weeks,
        same_weeks=bool(body.same_weeks),
        plan=plan,
        start_date=body.start_date,
        end_date=end,
    )
    session.add(sheet)
    session.commit()
    session.refresh(sheet)

    return {"id": sheet.id, "title": sheet.title, "weeks": sheet.weeks}
