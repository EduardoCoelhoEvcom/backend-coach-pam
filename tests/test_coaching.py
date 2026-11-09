"""Mobilidade por atleta e diagnóstico inicial."""
from datetime import date, timedelta

from tests.conftest import _make_user, _token_for


def _add(coach_client, athlete_id, **body):
    return coach_client.post(f"/coach/athletes/{athlete_id}/mobility", json=body)


# ---------- Mobilidade ----------
def test_mobility_empty_list(athlete_client):
    # Sem nada cadastrado o app mostra "Nenhuma mobilidade cadastrada".
    r = athlete_client.get("/athlete/mobility")
    assert r.status_code == 200
    assert r.json() == []


def test_coach_adds_and_athlete_sees_in_order(coach_client, athlete_client, athlete_user):
    a = _add(coach_client, athlete_user.id, name=" Mobilidade de tornozelo na parede ",
             dose="2x10/10", video_url="https://youtube.com/watch?v=abc")
    assert a.status_code == 200, a.text
    assert a.json()["name"] == "Mobilidade de tornozelo na parede"
    _add(coach_client, athlete_user.id, name="Abertura torácica no rolo", dose='2x30"')

    lst = athlete_client.get("/athlete/mobility").json()
    assert [i["name"] for i in lst] == ["Mobilidade de tornozelo na parede", "Abertura torácica no rolo"]
    assert lst[0]["dose"] == "2x10/10"
    assert lst[0]["video_url"] == "https://youtube.com/watch?v=abc"
    assert lst[1]["video_url"] is None
    assert all(i["done"] is False for i in lst)


def test_mobility_validation(coach_client, athlete_user):
    assert _add(coach_client, athlete_user.id, name="   ").status_code == 422
    assert _add(coach_client, athlete_user.id, name="Pigeon", video_url="youtube.com/x").status_code == 422


def test_mark_done_per_day(coach_client, athlete_client, athlete_user):
    item = _add(coach_client, athlete_user.id, name="Pigeon (quadril)").json()
    today = date.today()
    yesterday = today - timedelta(days=1)

    r = athlete_client.post(f"/athlete/mobility/{item['id']}/done", json={"day": today.isoformat()})
    assert r.status_code == 200 and r.json()["done"] is True
    # Marcar de novo não duplica nem dá erro
    assert athlete_client.post(f"/athlete/mobility/{item['id']}/done", json={"day": today.isoformat()}).status_code == 200

    assert athlete_client.get(f"/athlete/mobility?day={today}").json()[0]["done"] is True
    # Outro dia começa desmarcado
    assert athlete_client.get(f"/athlete/mobility?day={yesterday}").json()[0]["done"] is False

    # Sem body vale a data de hoje
    assert athlete_client.post(f"/athlete/mobility/{item['id']}/done").status_code == 200

    off = athlete_client.delete(f"/athlete/mobility/{item['id']}/done?day={today}")
    assert off.status_code == 200 and off.json()["done"] is False
    assert athlete_client.get(f"/athlete/mobility?day={today}").json()[0]["done"] is False


def test_coach_edits_and_deletes(coach_client, athlete_client, athlete_user):
    item = _add(coach_client, athlete_user.id, name="Pigeon", dose="2x40\"").json()
    athlete_client.post(f"/athlete/mobility/{item['id']}/done")

    e = coach_client.patch(f"/coach/mobility/{item['id']}", json={"dose": "3x40\"", "video_url": "https://youtu.be/x"})
    assert e.status_code == 200, e.text
    assert e.json()["dose"] == "3x40\"" and e.json()["name"] == "Pigeon"
    assert coach_client.patch(f"/coach/mobility/{item['id']}", json={"name": ""}).status_code == 422

    assert coach_client.get(f"/coach/athletes/{athlete_user.id}/mobility").json()[0]["video_url"] == "https://youtu.be/x"

    d = coach_client.delete(f"/coach/mobility/{item['id']}")
    assert d.status_code == 200
    assert athlete_client.get("/athlete/mobility").json() == []


def test_mobility_is_private_between_users(coach_client, athlete_client, client, session, coach_user, athlete_user):
    item = _add(coach_client, athlete_user.id, name="Tornozelo").json()

    # Outra coach não vê, não edita e não cadastra pro atleta
    intruder = _make_user(session, name="Intrusa", email="i@t.com", role="coach")
    client.headers["Authorization"] = f"Bearer {_token_for(intruder)}"
    assert client.get(f"/coach/athletes/{athlete_user.id}/mobility").status_code == 403
    assert client.patch(f"/coach/mobility/{item['id']}", json={"name": "x"}).status_code == 403
    assert client.delete(f"/coach/mobility/{item['id']}").status_code == 403
    assert client.post(f"/coach/athletes/{athlete_user.id}/mobility", json={"name": "x"}).status_code == 403

    # Outro atleta não marca a mobilidade de quem não é ele
    other = _make_user(session, name="Bia", email="b@t.com", role="athlete", coach_id=coach_user.id)
    client.headers["Authorization"] = f"Bearer {_token_for(other)}"
    assert client.post(f"/athlete/mobility/{item['id']}/done").status_code == 404
    assert client.get("/athlete/mobility").json() == []


# ---------- Diagnóstico inicial ----------
def test_diagnosis_flow(coach_client, athlete_client, athlete_user):
    assert athlete_client.get("/athlete/diagnosis").json() is None
    assert coach_client.get(f"/coach/athletes/{athlete_user.id}/diagnosis").json() is None

    r = coach_client.put(f"/coach/athletes/{athlete_user.id}/diagnosis", json={
        "strengths": "Boa força de pernas e puxada rápida.",
        "adjustments": "Barra se afastando do corpo no arranco.",
        "mobility": "Tornozelo e torácica limitam o overhead squat.",
        "pdf_url": "https://example.com/Diagnostico_Julia.pdf",
        "diagnosed_on": "2026-10-06",
    })
    assert r.status_code == 200, r.text

    d = athlete_client.get("/athlete/diagnosis").json()
    assert d["strengths"] == "Boa força de pernas e puxada rápida."
    assert d["pdf_url"] == "https://example.com/Diagnostico_Julia.pdf"
    assert d["diagnosed_on"] == "2026-10-06"

    # Salvar de novo atualiza (não cria outro); PDF é opcional
    r2 = coach_client.put(f"/coach/athletes/{athlete_user.id}/diagnosis", json={
        "strengths": "Nova versão", "pdf_url": "",
    })
    assert r2.status_code == 200
    d = athlete_client.get("/athlete/diagnosis").json()
    assert d["strengths"] == "Nova versão" and d["pdf_url"] is None
    assert d["diagnosed_on"] == "2026-10-06"  # sem data nova, mantém a anterior


def test_diagnosis_validation_and_privacy(coach_client, client, session, athlete_user):
    bad = coach_client.put(f"/coach/athletes/{athlete_user.id}/diagnosis", json={"pdf_url": "arquivo.pdf"})
    assert bad.status_code == 422

    intruder = _make_user(session, name="Intrusa", email="i@t.com", role="coach")
    client.headers["Authorization"] = f"Bearer {_token_for(intruder)}"
    assert client.get(f"/coach/athletes/{athlete_user.id}/diagnosis").status_code == 403
    assert client.put(f"/coach/athletes/{athlete_user.id}/diagnosis", json={"strengths": "x"}).status_code == 403


# ---------- LGPD ----------
def test_export_and_delete_include_mobility_and_diagnosis(coach_client, athlete_client, session, athlete_user):
    from sqlmodel import select
    from models import InitialDiagnosis, MobilityCompletion, MobilityItem

    item = _add(coach_client, athlete_user.id, name="Tornozelo").json()
    athlete_client.post(f"/athlete/mobility/{item['id']}/done")
    coach_client.put(f"/coach/athletes/{athlete_user.id}/diagnosis", json={"strengths": "Força"})

    exp = athlete_client.get("/me/export").json()
    assert len(exp["mobility"]) == 1 and len(exp["mobility_done"]) == 1
    assert exp["diagnosis"]["strengths"] == "Força"

    r = athlete_client.request("DELETE", "/me", json={"password": "test123"})
    assert r.status_code == 200, r.text
    session.expire_all()
    assert session.exec(select(MobilityItem)).all() == []
    assert session.exec(select(MobilityCompletion)).all() == []
    assert session.exec(select(InitialDiagnosis)).all() == []


def test_coach_leaving_keeps_athlete_data(coach_client, session, athlete_user):
    from sqlmodel import select
    from models import InitialDiagnosis, MobilityItem

    _add(coach_client, athlete_user.id, name="Tornozelo")
    coach_client.put(f"/coach/athletes/{athlete_user.id}/diagnosis", json={"strengths": "Força"})

    r = coach_client.request("DELETE", "/me", json={"password": "test123"})
    assert r.status_code == 200, r.text
    session.expire_all()
    items = session.exec(select(MobilityItem)).all()
    diag = session.exec(select(InitialDiagnosis)).all()
    assert len(items) == 1 and items[0].coach_id is None
    assert len(diag) == 1 and diag[0].coach_id is None
