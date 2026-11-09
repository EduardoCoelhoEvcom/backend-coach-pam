"""Bloco "Técnicos" do dia (aquecimento neural, barra vazia): salvo no plano,
limpo pelo servidor e entregue ao atleta."""
from datetime import date

from services.training_plan import normalize_technical


def test_technical_saved_and_visible_to_athlete(athlete_client, coach_client, athlete_user):
    sheet_id = coach_client.post("/coach/training-sheets", json={
        "athlete_id": athlete_user.id, "title": "Treino", "weeks": 1,
        "same_weeks": True, "start_date": str(date.today()),
    }).json()["id"]

    plan = coach_client.get(f"/coach/training-sheets/{sheet_id}").json()["plan"]
    monday = plan["weeks"][0]["days"][0]
    monday["technical"] = [
        {"name": "2\" pausas (snatch)", "prescription": "3 rounds",
         "instructions": "Low hang, hang e high hang", "video_url": "https://youtu.be/x"},
        {"name": "  ", "prescription": "descartado"},
    ]
    monday["accessories"] = [{"name": "Face pull", "series": [{"reps": 10}]}]
    r = coach_client.put(f"/coach/training-sheets/{sheet_id}/plan", json={"plan": plan})
    assert r.status_code == 200, r.text

    got = athlete_client.get(f"/athlete/training-sheets/{sheet_id}").json()["plan"]
    tec = got["weeks"][0]["days"][0]["technical"]
    assert tec == [{"name": "2\" pausas (snatch)", "prescription": "3 rounds",
                    "instructions": "Low hang, hang e high hang", "video_url": "https://youtu.be/x"}]
    # Dias sem técnicos continuam com a lista vazia
    assert got["weeks"][0]["days"][1]["technical"] == []


def test_normalize_technical_cleans_input():
    assert normalize_technical(None) == []
    assert normalize_technical("lixo") == []
    out = normalize_technical([{"name": " Tall clean ", "video_url": "javascript:alert(1)", "prescription": ""}, 5])
    assert out == [{"name": "Tall clean", "prescription": None, "instructions": None, "video_url": None}]
