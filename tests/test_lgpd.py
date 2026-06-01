"""Testes dos endpoints LGPD: GET /me/export e DELETE /me.

Garantem que o usuário consegue exportar e apagar seus próprios dados,
sem afetar dados de outros usuários.
"""
from datetime import date


# ---------- GET /me/export ----------
def test_export_returns_user_data(athlete_client, athlete_user):
    res = athlete_client.get("/me/export")
    assert res.status_code == 200
    data = res.json()

    assert data["user"]["email"] == "atleta@test.com"
    assert data["user"]["role"] == "athlete"
    # Estruturas listadas mesmo se vazias
    assert "training_sheets" in data
    assert "training_day_completions" in data
    assert "training_set_executions" in data
    assert "rm_history" in data


def test_export_includes_training_sheet_when_user_is_athlete(
    athlete_client, coach_client, athlete_user
):
    """Sheet criado pelo coach pra esse atleta deve aparecer no export."""
    coach_client.post(
        "/coach/training-sheets",
        json={
            "athlete_id": athlete_user.id,
            "title": "Treino do Atleta",
            "weeks": 4,
            "same_weeks": True,
            "start_date": str(date.today()),
        },
    )

    res = athlete_client.get("/me/export")
    data = res.json()
    titles = [s["title"] for s in data["training_sheets"]]
    assert "Treino do Atleta" in titles


def test_export_requires_auth(client):
    res = client.get("/me/export")
    assert res.status_code == 401


# ---------- DELETE /me ----------
def test_delete_account_removes_user(athlete_client, athlete_user, session):
    res = athlete_client.request("DELETE", "/me", json={"password": "test123"})
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # Tenta acessar /me com o mesmo token — backend não deve achar o user
    me_res = athlete_client.get("/me")
    assert me_res.status_code == 401


def test_delete_account_rejects_wrong_password(athlete_client, athlete_user):
    res = athlete_client.request("DELETE", "/me", json={"password": "wrong"})
    assert res.status_code == 400
    # Account ainda existe
    me_res = athlete_client.get("/me")
    assert me_res.status_code == 200


def test_delete_account_removes_associated_data(
    athlete_client, coach_client, athlete_user
):
    """Apagar conta também apaga planilhas, completions, executions."""
    # Coach cria sheet pro atleta
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

    # Atleta completa um dia
    athlete_client.post(
        "/athlete/complete-day",
        json={"training_sheet_id": sheet_id, "week_number": 1, "day": "monday"},
    )

    # Apaga conta
    res = athlete_client.request("DELETE", "/me", json={"password": "test123"})
    assert res.status_code == 200

    # Coach lista sheets — não deve ter mais
    list_res = coach_client.get("/coach/training-sheets")
    titles = [s["title"] for s in list_res.json()]
    assert "T" not in titles


def test_delete_account_does_not_affect_other_users(
    athlete_client, athlete_user, coach_user, session
):
    """Apagar atleta NÃO apaga o coach (que é outro usuário)."""
    res = athlete_client.request("DELETE", "/me", json={"password": "test123"})
    assert res.status_code == 200

    # Coach ainda existe no banco
    from models import User
    coach = session.get(User, coach_user.id)
    assert coach is not None
    assert coach.email == "coach@test.com"
