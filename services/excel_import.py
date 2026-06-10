"""Parser do Excel de planilhas da Coach Pâm.

Lê o formato que ela já usa (cada aba = um time/fase) e devolve, por aba:
  - title, athletes (nomes do topo), weeks (qtd de semanas detectadas)
  - plan: { weeks: [ { week_number, days: [ { day, rest, lpo_exercises } ] } ] }
  - exercises: lista de nomes distintos encontrados
  - complexes: lista de complexos (nome com "+") com as partes

NÃO toca no banco. A resolução de exercise_id por nome e a validação contra a
biblioteca acontecem no router (que tem a sessão do DB).

Regras do layout (combinadas com a coach):
  - Cada semana é um bloco horizontal de 6 colunas:
        Exercício | RM | % | kg | s/r | Reps
    Os blocos começam onde a linha de cabeçalho tem "Exercício".
  - Dias ficam na 1ª coluna ("SEGUNDA-FEIRA", ... "QUINTA — DESCANSO").
  - Cabeçalhos decorativos (▸, ✦, ℹ️, emojis), PSE/PSR, AUXILIARES e TESTE
    são ignorados. A fonte de verdade é a LINHA DE DADOS (nome limpo + %).
  - "s/r" tipo "2x3" = 2 séries de 3 reps. Várias linhas = ondas (% diferentes).
  - "%" vem como decimal (0.70) e vira 70.
  - kg/RM/Reps(laranja)/PSE são ignorados no import (o app recalcula o kg
    pelo RM de cada atleta; Reps/PSE são dados de execução).
"""
from __future__ import annotations

import io
import re
from typing import List, Optional

import openpyxl


# ---- Mapeamento de dias -------------------------------------------------

_DAY_MAP = [
    (("segunda",), "monday"),
    (("terca", "terça"), "tuesday"),
    (("quarta",), "wednesday"),
    (("quinta",), "thursday"),
    (("sexta",), "friday"),
    (("sabado", "sábado"), "saturday"),
    (("domingo",), "sunday"),
]

# Prefixos/decorações que indicam linha que NÃO é dado de exercício.
_DECO_PREFIXES = ("▸", "✦", "ℹ", "🔵", "🟢", "💡", "👥", "🟡", "🟠", "⚠")


def _clean_text(v) -> str:
    return str(v).strip() if v is not None else ""


def _strip_accents_lower(s: str) -> str:
    s = (s or "").lower()
    repl = {"á": "a", "â": "a", "ã": "a", "à": "a", "é": "e", "ê": "e",
            "í": "i", "ó": "o", "ô": "o", "õ": "o", "ú": "u", "ç": "c"}
    for k, v in repl.items():
        s = s.replace(k, v)
    return s


def _detect_day(text: str) -> Optional[str]:
    """Se o texto da 1ª coluna marca um dia, retorna o slug do dia."""
    t = _strip_accents_lower(text)
    for needles, slug in _DAY_MAP:
        if any(n in t for n in needles):
            return slug
    return None


def _is_rest(text: str) -> bool:
    return "descanso" in _strip_accents_lower(text)


def _is_deco_or_meta(text: str) -> bool:
    """True para linhas decorativas/meta que devem ser ignoradas."""
    t = text.strip()
    if not t:
        return True
    if t.lower() == "x":
        return True
    for p in _DECO_PREFIXES:
        if t.startswith(p):
            return True
    tl = _strip_accents_lower(t)
    meta_markers = ("pse sessao", "psr", "auxiliares", "teste", "sem treino")
    if any(m in tl for m in meta_markers):
        return True
    return False


def parse_sr(sr) -> Optional[tuple]:
    """'2x3' -> (2, 3). Aceita também 'NxM' com espaços. None se não casar."""
    if sr is None:
        return None
    s = str(sr).strip().lower().replace(" ", "")
    m = re.match(r"^(\d+)x(\d+)$", s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def pct_to_int(v) -> Optional[float]:
    """0.7 -> 70 ; 0.875 -> 87.5 ; 70 -> 70 (se já vier inteiro)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f <= 1.5:  # decimal (0.70). Acima disso assume que já é percentual.
        f = f * 100
    r = round(f, 1)
    return int(r) if r == int(r) else r


def is_complex_name(name: str) -> bool:
    return "+" in (name or "")


def split_complex(name: str) -> List[str]:
    parts = [p.strip() for p in re.split(r"\+", name or "")]
    return [p for p in parts if p]


# ---- Detecção dos blocos de semana --------------------------------------

def _find_week_blocks(ws) -> List[int]:
    """Acha as colunas iniciais de cada bloco de semana.

    Procura na linha de cabeçalho (primeiras ~10 linhas) as células
    que contenham 'Exercício'. Cada uma marca o começo de um bloco.
    """
    for row in range(1, 11):
        cols = []
        for col in range(1, ws.max_column + 1):
            val = _clean_text(ws.cell(row=row, column=col).value)
            if _strip_accents_lower(val).startswith("exercicio"):
                cols.append(col)
        if len(cols) >= 1:
            return cols
    return [1]


def _find_header_row(ws) -> int:
    for row in range(1, 11):
        for col in range(1, ws.max_column + 1):
            val = _clean_text(ws.cell(row=row, column=col).value)
            if _strip_accents_lower(val).startswith("exercicio"):
                return row
    return 5


def _parse_athletes(ws) -> List[str]:
    """Nomes do time ficam numa linha com '👥 A · B · C'.

    Só consideramos a célula que tem o marcador 👥 (a do título também usa
    '·', então não dá pra cair nela).
    """
    for row in range(1, 8):
        for col in range(1, ws.max_column + 1):
            val = _clean_text(ws.cell(row=row, column=col).value)
            if "👥" in val:
                cleaned = val.replace("👥", "").strip()
                parts = re.split(r"·|,|;|/|\|", cleaned)
                names = [p.strip() for p in parts if p.strip()]
                if names:
                    return names
    return []


def _parse_title(ws) -> str:
    for row in range(1, 4):
        for col in range(1, ws.max_column + 1):
            val = _clean_text(ws.cell(row=row, column=col).value)
            if val and len(val) > 8 and "exercicio" not in _strip_accents_lower(val):
                # pega só a 1ª linha do texto do título
                return val.split("\n")[0].strip()
    return ws.title


def parse_sheet(ws) -> dict:
    """Parseia uma aba inteira e devolve a estrutura pronta para a prévia."""
    header_row = _find_header_row(ws)
    block_cols = _find_week_blocks(ws)
    first_data_row = header_row + 1
    last_row = ws.max_row

    # 1) Estrutura de dias a partir da 1ª coluna (col 1).
    #    Lista de (day_slug, rest, start_row, end_row).
    day_spans = []
    cur = None  # (slug, rest, start_row)
    for r in range(first_data_row, last_row + 1):
        a = _clean_text(ws.cell(row=r, column=1).value)
        slug = _detect_day(a)
        if slug:
            if cur:
                day_spans.append((cur[0], cur[1], cur[2], r - 1))
            cur = (slug, _is_rest(a), r + 1)
    if cur:
        day_spans.append((cur[0], cur[1], cur[2], last_row))

    weeks = []
    all_names: List[str] = []

    for wi, start_col in enumerate(block_cols):
        name_col = start_col
        pct_col = start_col + 2
        sr_col = start_col + 4

        days_out = []
        for slug, rest, r0, r1 in day_spans:
            lpo_exercises = []
            current_ex = None

            if not rest:
                for r in range(r0, r1 + 1):
                    raw_name = _clean_text(ws.cell(row=r, column=name_col).value)
                    pct = ws.cell(row=r, column=pct_col).value
                    sr = ws.cell(row=r, column=sr_col).value
                    pct_val = pct_to_int(pct)
                    sr_parsed = parse_sr(sr)

                    is_data_name = (
                        raw_name
                        and not _is_deco_or_meta(raw_name)
                        and _detect_day(raw_name) is None
                    )

                    if is_data_name:
                        # novo exercício (linha-base)
                        current_ex = {
                            "name": raw_name,
                            "is_complex": is_complex_name(raw_name),
                            "series": [],
                        }
                        lpo_exercises.append(current_ex)
                        all_names.append(raw_name)
                        _append_series(current_ex, pct_val, sr_parsed)
                    elif (pct_val is not None or sr_parsed is not None) and current_ex:
                        # onda adicional do exercício atual
                        _append_series(current_ex, pct_val, sr_parsed)

            # remove exercícios que ficaram sem nenhuma série nesta semana
            lpo_exercises = [e for e in lpo_exercises if e["series"]]
            days_out.append({
                "day": slug,
                "rest": rest,
                "coach_notes": "",
                "lpo_exercises": lpo_exercises,
                "accessories": [],
            })

        weeks.append({"week_number": wi + 1, "days": days_out})

    # nomes distintos preservando ordem
    seen = set()
    distinct = []
    for n in all_names:
        if n not in seen:
            seen.add(n)
            distinct.append(n)

    complexes = []
    for n in distinct:
        if is_complex_name(n):
            complexes.append({"name": n, "parts": split_complex(n)})

    return {
        "name": ws.title,
        "title": _parse_title(ws),
        "athletes": _parse_athletes(ws),
        "weeks": len(block_cols),
        "plan": {"weeks": weeks},
        "exercises": distinct,
        "complexes": complexes,
    }


def _append_series(ex: dict, pct_val, sr_parsed) -> None:
    """Expande s/r em séries. '2x3' -> 2 séries de {reps:3, percent}."""
    if sr_parsed:
        sets, reps = sr_parsed
    else:
        # sem s/r: 1 série; reps desconhecida -> 1 (a coach ajusta)
        sets, reps = 1, 1
    for _ in range(sets):
        ex["series"].append({
            "reps": reps,
            "percent": pct_val if pct_val is not None else 0,
        })


def parse_workbook(file_bytes: bytes) -> List[dict]:
    """Parseia todas as abas e devolve uma lista de estruturas por aba."""
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    return [parse_sheet(ws) for ws in wb.worksheets]
