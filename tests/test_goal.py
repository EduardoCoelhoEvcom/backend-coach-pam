"""Objetivo/focos do atleta (aba "Plano") e contato da coach (aba "Eu")."""
from tests.conftest import _make_user, _token_for

GOAL = {
    "objective": " Competir pela primeira vez no LPO ",
    "target": "Meta: Open de Porto Alegre · 03/2027",
    "phases": ["Base técnica", "Força", " ", "Específico pra prova"],
    "focuses": [
        {"title": "Recepção mais baixa no arranco", "detail": "Pra ganhar confiança embaixo da barra."},
        {"title": "  "},
        {"title": "Estabilidade no jerk"},
    ],
    "coach_note": "Confia no processo. Técnica primeiro, peso depois.",
}


def test_goal_flow(coach_client, athlete_client, athlete_user):
    assert athlete_client.get("/athlete/goal").json() is None

    r = coach_client.put(f"/coach/athletes/{athlete_user.id}/goal", json=GOAL)
    assert r.status_code == 200, r.text

    g = athlete_client.get("/athlete/goal").json()
    assert g["objective"] == "Competir pela primeira vez no LPO"
    assert g["phases"] == ["Base técnica", "Força", "Específico pra prova"]  # vazios saem
    assert [f["title"] for f in g["focuses"]] == ["Recepção mais baixa no arranco", "Estabilidade no jerk"]
    assert g["focuses"][1]["detail"] is None
    assert g["coach_note"].startswith("Confia")

    # Salvar de novo substitui
    coach_client.put(f"/coach/athletes/{athlete_user.id}/goal", json={"objective": "Novo objetivo"})
    g = coach_client.get(f"/coach/athletes/{athlete_user.id}/goal").json()
    assert g["objective"] == "Novo objetivo" and g["phases"] == [] and g["focuses"] == []


def test_goal_privacy(client, session, athlete_user):
    intruder = _make_user(session, name="Intrusa", email="i@t.com", role="coach")
    client.headers["Authorization"] = f"Bearer {_token_for(intruder)}"
    assert client.get(f"/coach/athletes/{athlete_user.id}/goal").status_code == 403
    assert client.put(f"/coach/athletes/{athlete_user.id}/goal", json=GOAL).status_code == 403


def test_coach_contact(coach_client, athlete_client, client, session):
    c = athlete_client.get("/athlete/coach").json()
    assert c["name"] == "Coach Test" and c["whatsapp"] is None

    r = coach_client.put("/coach/me/whatsapp", json={"whatsapp": " (51) 99999-0000 "})
    assert r.status_code == 200
    assert athlete_client.get("/athlete/coach").json()["whatsapp"] == "(51) 99999-0000"

    # Atleta sem coach recebe vazio
    solo = _make_user(session, name="Solo", email="s@t.com", role="athlete")
    client.headers["Authorization"] = f"Bearer {_token_for(solo)}"
    assert client.get("/athlete/coach").json() == {"name": None, "whatsapp": None}


def test_goal_in_export_and_deleted_with_account(coach_client, athlete_client, session, athlete_user):
    from sqlmodel import select
    from models import TrainingGoal

    coach_client.put(f"/coach/athletes/{athlete_user.id}/goal", json=GOAL)
    assert athlete_client.get("/me/export").json()["goal"]["objective"].startswith("Competir")

    r = athlete_client.request("DELETE", "/me", json={"password": "test123"})
    assert r.status_code == 200, r.text
    session.expire_all()
    assert session.exec(select(TrainingGoal)).all() == []
