"""Testes das rotas de atleta: planilhas, progresso, complete-day."""
from datetime import date


# ---------- /athlete/training-sheets ----------
def test_athlete_lists_only_own_sheets(
    athlete_client, coach_client, coach_user, athlete_user, session
):
    """Coach cria uma sheet pra athlete_user; outra pra ninguém."""
    res = coach_client.post(
        "/coach/training-sheets",
        json={
            "athlete_id": athlete_user.id,
            "title": "Treino do Atleta",
            "weeks": 4,
            "same_weeks": True,
            "start_date": str(date.today()),
        },
    )
    assert res.status_code == 200

    list_res = athlete_client.get("/athlete/training-sheets")
    assert list_res.status_code == 200
    sheets = list_res.json()
    assert len(sheets) == 1
    assert sheets[0]["title"] == "Treino do Atleta"
    assert sheets[0]["athlete_id"] == athlete_user.id


def test_coach_cannot_call_athlete_endpoints(coach_client):
    """require_role('athlete') bloqueia coach."""
    res = coach_client.get("/athlete/training-sheets")
    assert res.status_code == 403


# ---------- /athlete/progress ----------
def test_athlete_progress_initial_state(athlete_client):
    res = athlete_client.get("/athlete/progress")
    assert res.status_code == 200
    data = res.json()
    assert data["total_completed_days"] == 0
    assert data["completed_today"] is False
    assert data["streak_days"] == 0


# ---------- /athlete/complete-day ----------
def test_athlete_completes_day_and_progress_updates(
    athlete_client, coach_client, athlete_user
):
    # Coach cria planilha
    create_res = coach_client.post(
        "/coach/training-sheets",
        json={
            "athlete_id": athlete_user.id,
            "title": "Treino X",
            "weeks": 4,
            "same_weeks": True,
            "start_date": str(date.today()),
        },
    )
    sheet_id = create_res.json()["id"]

    # Atleta completa o dia
    res = athlete_client.post(
        "/athlete/complete-day",
        json={
            "training_sheet_id": sheet_id,
            "week_number": 1,
            "day": "monday",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["completed_today"] is True
    assert data["total_completed_days"] == 1
    assert data["streak_days"] == 1


def test_athlete_complete_day_idempotent(
    athlete_client, coach_client, athlete_user
):
    """Completar o mesmo dia 2x não duplica a contagem."""
    create_res = coach_client.post(
        "/coach/training-sheets",
        json={
            "athlete_id": athlete_user.id,
            "title": "T",
            "weeks": 4,
            "same_weeks": True,
            "start_date": str(date.today()),
        },
    )
    sheet_id = create_res.json()["id"]

    payload = {
        "training_sheet_id": sheet_id,
        "week_number": 1,
        "day": "monday",
    }
    athlete_client.post("/athlete/complete-day", json=payload)
    res2 = athlete_client.post("/athlete/complete-day", json=payload)

    assert res2.status_code == 200
    data = res2.json()
    assert data["total_completed_days"] == 1


def test_athlete_cannot_complete_other_athletes_sheet(
    athlete_client, coach_client, session, coach_user
):
    """Sheet de OUTRO atleta retorna 404."""
    # Cria um segundo atleta direto no DB
    from models import User
    from security import get_password_hash

    other = User(
        name="Outro",
        email="outro@test.com",
        password_hash=get_password_hash("test123"),
        role="athlete",
    )
    session.add(other)
    session.commit()
    session.refresh(other)

    create_res = coach_client.post(
        "/coach/training-sheets",
        json={
            "athlete_id": other.id,
            "title": "Treino do Outro",
            "weeks": 4,
            "same_weeks": True,
            "start_date": str(date.today()),
        },
    )
    other_sheet_id = create_res.json()["id"]

    # athlete_client é "atleta@test.com" (não é "outro")
    res = athlete_client.post(
        "/athlete/complete-day",
        json={
            "training_sheet_id": other_sheet_id,
            "week_number": 1,
            "day": "monday",
        },
    )
    assert res.status_code == 404


# ---------- /athlete/exercise-rms ----------
def test_athlete_lists_rms_empty_initially(athlete_client):
    res = athlete_client.get("/athlete/exercise-rms")
    assert res.status_code == 200
    assert res.json() == []
