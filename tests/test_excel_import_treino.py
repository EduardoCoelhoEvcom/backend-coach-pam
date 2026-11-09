"""Importação do Excel no formato "TREINO N" + "Base do %" (planilha da coach).

A planilha de teste reproduz o layout real: aquecimento, exercício em várias
linhas ("· 1/3", "· 2/3", "· 3/3"), séries como "2x 2+1", "4 rounds · SC 70%",
"EMOM 4' · 2 reps" e um bloco sem % ("2 rounds").
"""
import io

import openpyxl
import pytest

from models import Exercise, ExerciseCategory
from services.excel_import import parse_series_cell, parse_workbook

WEEK_HEADER = ["SEMANA 1", None, None, "SEMANA 2", None, None, "SEMANA 3", None, None, "SEMANA 4", None, None, "Observações"]
TABLE_HEADER = ["Exercício", "Base do %", "RM (kg)"] + ["%", "kg", "Séries"] * 4


def _block(ws, n, title, name, base, weeks, note=None):
    """weeks = [(pct, séries), ...] pras 4 semanas."""
    ws.append([f"#{n}  {title}", None, None] + WEEK_HEADER)
    ws.append(TABLE_HEADER)
    row = [name, base, 97]
    for pct, sr in weeks:
        row += [pct, None, sr]
    row.append(note)
    ws.append(row)
    ws.append([])


def _workbook(day_word="TREINO") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Treino"
    ws.append(["COACH PÂM · LEVANTAMENTO DE PESO"])
    ws.append(["PLANO 4 SEMANAS · NOVEMBRO · JULIA KLABUNDE"])
    ws.append([])
    ws.append([f"{day_word} 1 — JERK & CLEAN"])
    ws.append(["AQUECIMENTO · 2 rounds"] + [None] * 14 + ["Observações"])
    ws.append(["Isometric Back Extension (GHD)", '20"'] + [None] * 13 + ["Peito alto na isometria."])
    ws.append([])
    _block(ws, 1, "Jerk Drive", "Jerk Drive", "Split Jerk",
           [(0.8, "3x3"), (0.9, "3x3"), (1.0, "3x2"), (0.8, "3x3")], "Semana 3 é a semana pesada.")
    _block(ws, 2, "Front Squat + Split Jerk (2+1) · 1/3", "Front Squat + Split Jerk (2+1)", "Front Squat",
           [(0.6, "2x 2+1"), (0.65, "1x 2+1"), (0.75, "2x 2+1"), (0.6, "2x 2+1")], "1 rep = 2 Front Squat + 1 Split Jerk.")
    _block(ws, 2, "Front Squat + Split Jerk (2+1) · 2/3", "Front Squat + Split Jerk (2+1)", "Front Squat",
           [(0.65, "2x 2+1"), (0.7, "2x 2+1"), (0.8, "2x 2+1"), (0.65, "2x 2+1")], "Segue na sequência da linha anterior.")
    _block(ws, 3, "A cada 2'30\" por 4 rounds · Clean Hold + Squat Clean", "2 Clean Low Hang Hold (3\") + 3 Squat Clean", "Clean",
           [(0.8, "4 rounds · SC 70%"), (0.9, "4 rounds · SC 80%"), (1.0, "4 rounds · SC 80-85%"), (0.8, "4 rounds · SC 70%")])
    ws.append([f"{day_word} 2 — SNATCH"])
    _block(ws, 1, "Posição (barra vazia) · rodada 1", '3" abaixo do joelho + 3" High Hang', None,
           [(None, "2 rounds")] * 4, "Barra vazia.")
    _block(ws, 2, "Squat Snatch", "Squat Snatch", "Snatch", [(0.8, "EMOM 4' · 2 reps")] * 4)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _faixas(ex):
    out = []
    for s in ex["series"]:
        if out and (out[-1][1], out[-1][2]) == (s["reps"], s["percent"]):
            out[-1][0] += 1
        else:
            out.append([1, s["reps"], s["percent"]])
    return [tuple(f) for f in out]


def _day(plan, week, slug):
    return next(d for d in plan["weeks"][week - 1]["days"] if d["day"] == slug)


@pytest.mark.parametrize("raw, expected", [
    ("3x3", (3, 3, None)),
    ("2x 2+1", (2, 1, None)),
    ("1x 2+1+1", (1, 1, None)),
    ("4 rounds · SC 70%", (4, 1, "SC 70%")),
    ("EMOM 4' · 2 reps", (4, 2, "EMOM 4'")),
    ("2 rounds", (2, 1, None)),
    ("6 reps", (1, 6, None)),
    ("", None),
    ('20"', None),
])
def test_series_cell(raw, expected):
    assert parse_series_cell(raw) == expected


def test_treino_format_is_read_like_the_sheet():
    abas = parse_workbook(_workbook())
    assert len(abas) == 1
    aba = abas[0]
    assert aba["format"] == "dias" and aba["weeks"] == 4
    assert aba["title"] == "PLANO 4 SEMANAS · NOVEMBRO · JULIA KLABUNDE"
    assert aba["day_map"] == {"DIA 1": "monday", "DIA 2": "thursday"}

    t1 = _day(aba["plan"], 1, "monday")
    names = [e["name"] for e in t1["lpo_exercises"]]
    # 1/3 e 2/3 viram UM exercício com faixas
    assert names == ["Jerk Drive", "Front Squat + Split Jerk (2+1)", '2 Clean Low Hang Hold (3") + 3 Squat Clean']
    jd, fs, hold = t1["lpo_exercises"]
    assert _faixas(jd) == [(3, 3, 80)] and jd["rm_base"] == "Split Jerk" and jd["is_complex"] is False
    assert _faixas(fs) == [(2, 1, 60), (2, 1, 65)] and fs["is_complex"] is True
    assert _faixas(hold) == [(4, 1, 80)]
    # Semana 2: "1x 2+1" na primeira faixa
    assert _faixas(_day(aba["plan"], 2, "monday")["lpo_exercises"][1]) == [(1, 1, 65), (2, 1, 70)]

    notes = t1["coach_notes"].split("\n")
    assert notes[0] == "AQUECIMENTO · 2 rounds"
    assert notes[1] == '• Isometric Back Extension (GHD) — 20". Peito alto na isometria.'
    assert "Jerk Drive: Semana 3 é a semana pesada." in notes
    assert "Front Squat + Split Jerk (2+1): 1 rep = 2 Front Squat + 1 Split Jerk." in notes
    assert not any("Segue na sequência" in n for n in notes)  # repetida, sai
    assert '2 Clean Low Hang Hold (3") + 3 Squat Clean: A cada 2\'30" por 4 rounds' in notes
    assert '2 Clean Low Hang Hold (3") + 3 Squat Clean: Nesta semana: SC 70%' in notes
    assert "Nesta semana: SC 80-85%" in _day(aba["plan"], 3, "monday")["coach_notes"]


def test_block_without_percent_and_emom():
    aba = parse_workbook(_workbook())[0]
    t2 = _day(aba["plan"], 1, "thursday")
    pos, ss = t2["lpo_exercises"]
    # Sem %: o título do bloco é o nome; a linha vira observação
    assert pos["name"] == "Posição (barra vazia) · rodada 1" and pos["rm_base"] is None
    assert _faixas(pos) == [(2, 1, 0)]
    assert 'Posição (barra vazia) · rodada 1: 3" abaixo do joelho + 3" High Hang' in t2["coach_notes"]
    # EMOM 4' · 2 reps → 4 séries de 2; "EMOM 4'" igual em todas as semanas vira observação fixa
    assert _faixas(ss) == [(4, 2, 80)]
    assert "Squat Snatch: EMOM 4'" in t2["coach_notes"]
    assert "Nesta semana: EMOM" not in t2["coach_notes"]


def test_old_dia_format_still_works():
    aba = parse_workbook(_workbook(day_word="DIA"))[0]
    assert aba["weeks"] == 4
    assert [e["name"] for e in _day(aba["plan"], 1, "monday")["lpo_exercises"]][0] == "Jerk Drive"


def test_preview_links_bases_to_library(coach_client, session):
    cat = ExerciseCategory(type="lpo", name="Teste")
    session.add(cat)
    session.commit()
    ids = {}
    for n in ["Split Jerk", "Front Squat", "Clean", "Snatch"]:
        e = Exercise(category_id=cat.id, name=n, type="lpo")
        session.add(e)
        session.commit()
        ids[n] = e.id

    r = coach_client.post(
        "/coach/import/preview",
        files={"file": ("julia.xlsx", _workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    aba = r.json()["abas"][0]
    assert aba["validation"]["unmatched"] == []
    t1 = _day(aba["plan"], 1, "monday")["lpo_exercises"]
    assert t1[0]["exercise_id"] == ids["Split Jerk"]          # simples → exercise_id
    assert t1[1]["rm_exercise_id"] == ids["Front Squat"]      # complexo → rm_exercise_id
    assert t1[2]["rm_exercise_id"] == ids["Clean"]
