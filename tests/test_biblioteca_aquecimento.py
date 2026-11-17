"""Biblioteca de aquecimento técnico (mesma estante da mobilidade)."""
from services.seeding import ensure_mobility_library


def test_aquecimento_separado_da_mobilidade(coach_client, session):
    ensure_mobility_library(session)
    assert coach_client.get("/coach/mobility-library?kind=aquecimento").json() == []
    r = coach_client.post("/coach/mobility-library", json={
        "name": "Tall Snatch", "joint": "Snatch", "kind": "aquecimento", "default_dose": "2x3"})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "aquecimento" and r.json()["joint"] == "Snatch"
    # mesmo nome que já existe na mobilidade ("Sots press") pode existir no aquecimento
    assert coach_client.post("/coach/mobility-library", json={
        "name": "Sots press", "joint": "Snatch", "kind": "aquecimento"}).status_code == 200
    assert coach_client.post("/coach/mobility-library", json={
        "name": "tall  snatch", "joint": "Clean", "kind": "aquecimento"}).status_code == 409
    assert coach_client.post("/coach/mobility-library", json={
        "name": "X", "joint": "Tornozelo", "kind": "aquecimento"}).status_code == 422
    aq = coach_client.get("/coach/mobility-library?kind=aquecimento").json()
    assert [i["name"] for i in aq] == ["Tall Snatch", "Sots press"]
    # a mobilidade continua só com a mobilidade
    mob = coach_client.get("/coach/mobility-library").json()
    assert len(mob) == 26 and all(i["kind"] == "mobilidade" for i in mob)
    assert len(coach_client.get("/coach/mobility-library?kind=todos").json()) == 28
