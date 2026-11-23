"""Editar cadastro, nova senha, remover aluno, plano antigo e competições."""
from models import AthletePlan, RefreshToken, TrainingGoal, User
from security import issue_refresh_token, verify_password
from sqlmodel import select


def _novo(coach_client, email="ficha@example.com", **extra):
    r = coach_client.post("/coach/athletes", json={"name": "Aluna Ficha", "email": email, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_editar_cadastro(coach_client):
    a = _novo(coach_client)
    _novo(coach_client, "outra@example.com")
    r = coach_client.patch(f"/coach/athletes/{a}", json={
        "name": " Aluna Nova ", "email": "NOVA@example.com", "whatsapp": "51 99999-0000", "vencimento": "2026-12-10",
    })
    assert r.status_code == 200, r.text
    p = coach_client.get(f"/coach/athletes/{a}/profile").json()
    assert (p["name"], p["email"], p["whatsapp"], p["vencimento"]) == (
        "Aluna Nova", "nova@example.com", "51 99999-0000", "2026-12-10")
    # só o campo enviado muda
    coach_client.patch(f"/coach/athletes/{a}", json={"whatsapp": ""})
    p = coach_client.get(f"/coach/athletes/{a}/profile").json()
    assert p["whatsapp"] is None and p["name"] == "Aluna Nova"
    assert coach_client.patch(f"/coach/athletes/{a}", json={"email": "outra@example.com"}).status_code == 400
    assert coach_client.patch(f"/coach/athletes/{a}", json={"name": "  "}).status_code == 422


def test_coach_nao_mexe_em_aluno_de_outra(coach_client, session):
    other_coach = User(name="Outra", email="c2@example.com", password_hash="x", role="coach")
    session.add(other_coach)
    session.commit()
    aluno = User(name="De Outra", email="a2@example.com", password_hash="x", role="athlete", coach_id=other_coach.id)
    session.add(aluno)
    session.commit()
    assert coach_client.patch(f"/coach/athletes/{aluno.id}", json={"name": "X"}).status_code == 404
    assert coach_client.post(f"/coach/athletes/{aluno.id}/reset-password").status_code == 404
    r = coach_client.request("DELETE", f"/coach/athletes/{aluno.id}", json={"confirm_name": "De Outra"})
    assert r.status_code == 404
    assert session.get(User, aluno.id) is not None


def test_nova_senha_provisoria(coach_client, session):
    a = _novo(coach_client)
    issue_refresh_token(session.get(User, a), session)
    temp = coach_client.post(f"/coach/athletes/{a}/reset-password").json()["temp_password"]
    session.expire_all()
    user = session.get(User, a)
    assert verify_password(temp, user.password_hash) and user.must_change_password
    rows = session.exec(select(RefreshToken).where(RefreshToken.user_id == a)).all()
    assert rows and all(t.revoked_at for t in rows)


def test_remover_aluno_exige_nome(coach_client, session):
    a = _novo(coach_client, plan="experience", frequency=3)
    issue_refresh_token(session.get(User, a), session)
    coach_client.put(f"/coach/athletes/{a}/goal", json={"objective": "Competir"})
    r = coach_client.request("DELETE", f"/coach/athletes/{a}", json={"confirm_name": "Outro nome"})
    assert r.status_code == 400 and session.get(User, a) is not None
    r = coach_client.request("DELETE", f"/coach/athletes/{a}", json={"confirm_name": " aluna ficha "})
    assert r.status_code == 200, r.text
    session.expire_all()
    assert session.get(User, a) is None
    for model, col in ((AthletePlan, AthletePlan.athlete_id), (TrainingGoal, TrainingGoal.athlete_id), (RefreshToken, RefreshToken.user_id)):
        assert session.exec(select(model).where(col == a)).first() is None


def test_plano_antigo(coach_client, athlete_client, athlete_user):
    a = _novo(coach_client, plan="antigo", custom_price=175.5, custom_months=6)
    p = coach_client.get(f"/coach/athletes/{a}/plan").json()
    assert (p["plan_name"], p["monthly_price"], p["months_total"]) == ("Plano antigo", 175.5, 6)
    bad = coach_client.post("/coach/athletes", json={"name": "Sem", "email": "sem@example.com", "plan": "antigo"})
    assert bad.status_code == 422
    # O aluno não vê a palavra "antigo"; a coach continua vendo.
    coach_client.put(f"/coach/athletes/{athlete_user.id}/plan", json={"plan_name": "Plano antigo", "monthly_price": 150})
    assert athlete_client.get("/athlete/plan").json()["plan_name"] == "Programa LPO"
    assert coach_client.get(f"/coach/athletes/{athlete_user.id}/plan").json()["plan_name"] == "Plano antigo"


def test_competicoes_no_objetivo(coach_client, athlete_client, athlete_user):
    url = f"/coach/athletes/{athlete_user.id}/goal"
    r = coach_client.put(url, json={"objective": "Competir", "focuses": [{"title": "Foco antigo"}], "competitions": [
        {"name": "Estadual", "date": "2027-06-10"},
        {"name": "Open", "date": "2027-03-05"},
        {"name": "  ", "date": "2027-01-01"},
    ]})
    assert r.status_code == 200, r.text
    assert [c["name"] for c in r.json()["competitions"]] == ["Open", "Estadual"]
    assert athlete_client.get("/athlete/goal").json()["competitions"][0]["date"] == "2027-03-05"
    # app antigo (sem o campo) não apaga as competições
    r = coach_client.put(url, json={"objective": "Competir 2", "focuses": [{"title": "Foco antigo"}]})
    assert len(r.json()["competitions"]) == 2
    r = coach_client.put(url, json={"objective": "Só técnica", "focuses": [{"title": "Foco antigo"}], "competitions": []})
    assert r.json()["competitions"] == [] and r.json()["focuses"][0]["title"] == "Foco antigo"
