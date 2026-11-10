"""Importador (formato TREINO N): blocos TÉCNICOS e ACESSÓRIOS."""
import io

from openpyxl import Workbook

from services.excel_import import parse_accessory_series, parse_workbook


def _xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    rows = [
        ["TREINO 1 — SNATCH"],
        ["TÉCNICOS (barra vazia)", "Volume", "Observações", "Vídeo"],
        ["Tall power clean", "3x6", "Barra vazia.", "https://youtu.be/abc"],
        ['#2 2" pausas + pull', "3 rounds", "Ombro na orelha"],
        [],
        ["#1 Power Snatch", None, None, "SEMANA 1", None, None, "SEMANA 2", None, None, "Observações"],
        ["Exercício", "Base do %", "RM", "%", "kg", "Séries", "%", "kg", "Séries"],
        ["Power Snatch", "Power Snatch", None, 0.5, None, "1x5", 0.55, None, "1x5"],
        [None, None, None, 0.6, None, "3x3", 0.65, None, "3x3"],
        [],
        ["ACESSÓRIOS", "Séries", "Observações"],
        ["Face pull", "2x8-10", None],
        ["Supino unilateral", "2x10/10", "Pegada neutra"],
        [],
    ]
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_tecnicos_e_acessorios_viram_blocos_em_todas_as_semanas():
    aba = parse_workbook(_xlsx())[0]
    assert aba["format"] == "dias" and aba["weeks"] == 2
    for w in aba["plan"]["weeks"]:
        day = next(d for d in w["days"] if d["day"] == "monday")
        assert day["technical"] == [
            {"name": "Tall power clean", "prescription": "3x6", "instructions": "Barra vazia.",
             "video_url": "https://youtu.be/abc"},
            {"name": '2" pausas + pull', "prescription": "3 rounds", "instructions": "Ombro na orelha",
             "video_url": None},
        ]
        assert [a["name"] for a in day["accessories"]] == ["Face pull", "Supino unilateral"]
        assert day["accessories"][0]["series"] == [{"reps": 10}, {"reps": 10}]
        assert "Face pull: 8 a 10 reps" in day["coach_notes"]
        assert "Supino unilateral: Pegada neutra" in day["coach_notes"]
        assert [e["name"] for e in day["lpo_exercises"]] == ["Power Snatch"]
    w1 = aba["plan"]["weeks"][0]["days"][0]["lpo_exercises"][0]["series"]
    assert [(s["reps"], s["percent"]) for s in w1] == [(5, 50), (3, 60), (3, 60), (3, 60)]


def test_parse_accessory_series():
    assert parse_accessory_series("2x10") == (2, 10, None)
    assert parse_accessory_series("2x8-10") == (2, 10, "8 a 10 reps")
    assert parse_accessory_series("2x10/10") == (2, 10, "10 de cada lado")
    assert parse_accessory_series("40 segundos") == (1, 1, "40 segundos")
