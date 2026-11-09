"""'+ Novo atleta' da coach e primeiro acesso do atleta."""
import re

from fastapi.testclient import TestClient

from main import app


def _novo(coach_client, **extra):
    body = {"name": " Marina Souza ", "email": "Marina.Souza@Gmail.com", **extra}
    return coach_client.post("/coach/athletes", json=body)


def _login(email, password):
    with TestClient(app) as c:
        return c.post("/auth/login", data={"username": email, "password": password})


def test_coach_creates_athlete_with_generated_password(coach_client):
    r = _novo(coach_client, whatsapp=" (51) 99876-5432 ", plan="experience", start_date="2026-11-09")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["name"] == "Marina Souza"
    assert a["email"] == "marina.souza@gmail.com"
    assert a["whatsapp"] == "(51) 99876-5432"
    assert a["plan_name"] == "Experience" and a["start_date"] == "2026-11-09"
    assert a["must_change_password"] is True
    assert re.fullmatch(r"PAM-[A-Z2-9]{6}", a["temp_password"])

    # A lista mostra o WhatsApp e que ainda não entrou
    lst = coach_client.get("/coach/athletes").json()
    m = next(x for x in lst if x["email"] == "marina.souza@gmail.com")
    assert m["whatsapp"] == "(51) 99876-5432" and m["must_change_password"] is True

    # O plano contratado foi criado junto
    plan = coach_client.get(f"/coach/athletes/{a['id']}/plan").json()
    assert plan["plan_name"] == "Experience" and plan["months_total"] == 6
    assert plan["monthly_price"] == 190 and plan["start_date"] == "2026-11-09"


def test_avulso_plan_and_no_plan(coach_client):
    a = _novo(coach_client, plan="avulso").json()
    plan = coach_client.get(f"/coach/athletes/{a['id']}/plan").json()
    assert plan["plan_name"] == "Mês avulso" and plan["months_total"] is None
    assert plan["monthly_price"] == 230

    b = coach_client.post("/coach/athletes", json={"name": "Sem Plano", "email": "sp@t.com"}).json()
    assert b["plan_name"] is None
    assert coach_client.get(f"/coach/athletes/{b['id']}/plan").json() is None


def test_create_athlete_validation(coach_client):
    assert _novo(coach_client, plan="vip").status_code == 422
    assert coach_client.post("/coach/athletes", json={"name": "  ", "email": "x@t.com"}).status_code == 422
    # E-mail repetido não cria outro
    assert _novo(coach_client).status_code == 200
    assert _novo(coach_client).status_code == 400


def test_first_access_forces_new_password(coach_client):
    temp = _novo(coach_client).json()["temp_password"]

    r = _login("marina.souza@gmail.com", temp)
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is True
    token = r.json()["access_token"]

    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        # Curta demais
        assert c.post("/auth/change-password", json={"new_password": "abc1234"}).status_code == 400
        # Igual à provisória
        assert c.post("/auth/change-password", json={"new_password": temp}).status_code == 400
        ok = c.post("/auth/change-password", json={"new_password": "levanta2026"})
        assert ok.status_code == 200, ok.text

    # A provisória para de funcionar; a nova entra sem pedir troca
    assert _login("marina.souza@gmail.com", temp).status_code == 400
    r2 = _login("marina.souza@gmail.com", "levanta2026")
    assert r2.status_code == 200 and r2.json()["must_change_password"] is False

    lst = coach_client.get("/coach/athletes").json()
    assert next(x for x in lst if x["email"] == "marina.souza@gmail.com")["must_change_password"] is False


def test_coach_given_password_is_also_provisional(coach_client):
    r = _novo(coach_client, password="abc123")
    assert r.status_code == 200
    assert r.json()["temp_password"] is None  # a coach já sabe a senha que digitou
    login = _login("marina.souza@gmail.com", "abc123")
    assert login.json()["must_change_password"] is True
