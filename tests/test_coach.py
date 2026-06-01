"""Testes das rotas de coach: atletas, dashboard, planilhas."""
from datetime import date


# ---------- /coach/athletes ----------
def test_coach_lists_athletes(coach_client, athlete_user):
    res = coach_client.get("/coach/athletes")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    emails = [a["email"] for a in data]
    assert "atleta@test.com" in emails


def test_athlete_cannot_list_athletes(athlete_client, athlete_user):
    """Atleta não pode listar atletas (require_role('coach'))."""
    res = athlete_client.get("/coach/athletes")
    assert res.status_code == 403


def test_coach_creates_athlete(coach_client):
    res = coach_client.post(
        "/coach/athletes",
        json={
            "name": "Novo Aluno",
            "email": "aluno@test.com",
            "password": "abc123",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Novo Aluno"
    assert data["role"] == "athlete"

    # Aparece na listagem
    list_res = coach_client.get("/coach/athletes")
    emails = [a["email"] for a in list_res.json()]
    assert "aluno@test.com" in emails


def test_coach_create_athlete_rejects_duplicate(coach_client, athlete_user):
    res = coach_client.post(
        "/coach/athletes",
        json={
            "name": "X",
            "email": "atleta@test.com",  # já existe via fixture
            "password": "abc123",
        },
    )
    assert res.status_code == 400


# ---------- /coach/dashboard ----------
def test_coach_dashboard_returns_zeros_when_empty(coach_client):
    res = coach_client.get("/coach/dashboard")
    assert res.status_code == 200
    data = res.json()
    assert data["athletes_total"] == 0
    assert data["sheets_total"] == 0
    assert data["executions_total"] == 0


# ---------- /coach/training-sheets ----------
def test_coach_creates_training_sheet(coach_client, athlete_user):
    res = coach_client.post(
        "/coach/training-sheets",
        json={
            "athlete_id": athlete_user.id,
            "title": "Bloco de força",
            "weeks": 4,
            "same_weeks": True,
            "start_date": str(date.today()),
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "Bloco de força"
    assert data["athlete_id"] == athlete_user.id
    assert data["weeks"] == 4


def test_coach_create_sheet_rejects_invalid_athlete(coach_client):
    res = coach_client.post(
        "/coach/training-sheets",
        json={
            "athlete_id": 99999,
            "title": "X",
            "weeks": 4,
            "same_weeks": True,
            "start_date": str(date.today()),
        },
    )
    assert res.status_code == 400


def test_coach_lists_only_own_sheets(coach_client, athlete_user):
    # Cria 2 planilhas
    for title in ["Sheet 1", "Sheet 2"]:
        coach_client.post(
            "/coach/training-sheets",
            json={
                "athlete_id": athlete_user.id,
                "title": title,
                "weeks": 4,
                "same_weeks": True,
                "start_date": str(date.today()),
            },
        )

    res = coach_client.get("/coach/training-sheets")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    titles = sorted(s["title"] for s in data)
    assert titles == ["Sheet 1", "Sheet 2"]


def test_coach_dashboard_counts_after_creating_sheet(coach_client, athlete_user):
    coach_client.post(
        "/coach/training-sheets",
        json={
            "athlete_id": athlete_user.id,
            "title": "S",
            "weeks": 4,
            "same_weeks": True,
            "start_date": str(date.today()),
        },
    )

    res = coach_client.get("/coach/dashboard")
    data = res.json()
    assert data["sheets_total"] == 1
    assert data["athletes_total"] == 1
