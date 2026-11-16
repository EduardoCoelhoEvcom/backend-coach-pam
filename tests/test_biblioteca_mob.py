"""Biblioteca de mobilidade por articulação (carga inicial + exercícios da coach)."""
from services.seeding import ensure_mobility_library


def test_carga_inicial_e_lista(coach_client, session):
    assert ensure_mobility_library(session) == 26
    assert ensure_mobility_library(session) == 0  # idempotente
    lib = coach_client.get("/coach/mobility-library").json()
    assert len(lib) == 26
    joints = [i["joint"] for i in lib]
    assert joints == sorted(joints, key=["Tornozelo", "Quadril", "Torácica", "Ombro", "Punho"].index)
    knee = next(i for i in lib if i["name"] == "Knee to wall")
    assert knee["joint"] == "Tornozelo" and knee["video_url"].startswith("https://") and knee["mine"] is False


def test_coach_cria_exercicio(coach_client, athlete_client, session):
    ensure_mobility_library(session)
    r = coach_client.post("/coach/mobility-library", json={
        "name": "Ankle CARs", "joint": "Tornozelo", "video_url": "https://youtu.be/x"})
    assert r.status_code == 200, r.text
    assert r.json()["mine"] is True
    assert coach_client.post("/coach/mobility-library", json={"name": "ankle  cars", "joint": "Tornozelo"}).status_code == 409
    assert coach_client.post("/coach/mobility-library", json={"name": "Knee to wall", "joint": "Tornozelo"}).status_code == 409
    assert coach_client.post("/coach/mobility-library", json={"name": "X", "joint": "Joelho"}).status_code == 422
    assert len(coach_client.get("/coach/mobility-library").json()) == 27
    assert athlete_client.get("/coach/mobility-library").status_code == 403
