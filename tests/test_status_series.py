"""O status (fez / errou / não fez) e a observação de cada série voltam na lista
de execuções — pro atleta (ao reabrir o app) e pra coach."""
from datetime import date


def test_status_and_note_come_back(athlete_client, coach_client, athlete_user):
    sheet_id = coach_client.post("/coach/training-sheets", json={
        "athlete_id": athlete_user.id, "title": "Treino", "weeks": 4,
        "same_weeks": True, "start_date": str(date.today()),
    }).json()["id"]

    r = athlete_client.post("/athlete/complete-day", json={
        "training_sheet_id": sheet_id, "week_number": 1, "day": "monday",
        "sets": [
            {"exercise_name": "Snatch", "series_index": 0, "status": "fez"},
            {"exercise_name": "Snatch", "series_index": 1, "status": "errou", "note": "perdi na recepção"},
            {"exercise_name": "Snatch", "series_index": 2},
        ],
    })
    assert r.status_code == 200, r.text

    for client, url in [
        (athlete_client, f"/athlete/training-sheets/{sheet_id}/executions"),
        (coach_client, f"/coach/training-sheets/{sheet_id}/executions"),
    ]:
        rows = {e["series_index"]: e for e in client.get(url).json()}
        assert rows[0]["status"] == "fez"
        assert rows[1]["status"] == "errou" and rows[1]["note"] == "perdi na recepção"
        assert rows[2]["status"] is None
