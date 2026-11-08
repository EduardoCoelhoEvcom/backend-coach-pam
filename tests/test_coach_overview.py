"""Visão geral da coach (Início / Atletas) e notas privadas."""
from datetime import date, timedelta

from models import AthleteExerciseRMHistory, Exercise, ExerciseCategory
from tests.conftest import _make_user, _token_for


def _exercises(session):
    cat = ExerciseCategory(type="lpo", name="Snatch")
    session.add(cat)
    session.commit()
    snatch = Exercise(category_id=cat.id, name="Snatch", type="lpo")
    session.add(snatch)
    session.commit()
    hang = Exercise(category_id=cat.id, name="Hang Snatch", type="lpo", rm_source_exercise_id=snatch.id)
    session.add(hang)
    session.commit()
    return snatch, hang


def _sheet(coach_client, athlete_id, ex_id, start, weeks=4):
    sid = coach_client.post("/coach/training-sheets", json={
        "athlete_id": athlete_id, "title": "Bloco", "weeks": weeks, "same_weeks": True, "start_date": str(start),
    }).json()["id"]
    plan = {"weeks": [{"week_number": n, "days": [{
        "day": "monday", "rest": False, "coach_notes": "",
        "lpo_exercises": [{"name": "Hang Snatch", "exercise_id": ex_id, "series": [{"reps": 2, "percent": 70}]}],
        "accessories": [],
    }]} for n in range(1, weeks + 1)]}
    assert coach_client.put(f"/coach/training-sheets/{sid}/plan", json={"plan": plan}).status_code == 200
    return sid


def _row(coach_client, athlete_id):
    data = coach_client.get("/coach/overview").json()
    return data, next(a for a in data["athletes"] if a["id"] == athlete_id)


def test_tags_follow_priority(coach_client, athlete_client, session, athlete_user):
    snatch, hang = _exercises(session)

    # Sem planilha
    data, a = _row(coach_client, athlete_user.id)
    assert a["tag"] == "Sem planilha"
    assert data["coach"]["name"] == "Coach Test"

    # Planilha usa uma variação sem RM no principal → Falta RM
    start = date.today() - timedelta(days=8)
    _sheet(coach_client, athlete_user.id, hang.id, start)
    _, a = _row(coach_client, athlete_user.id)
    assert a["tag"] == "Falta RM" and a["missing_rm"] is True
    assert a["sheet"]["current_week"] == 2 and a["sheet"]["weeks"] == 4

    # RM no principal resolve → Em dia
    session.add(AthleteExerciseRMHistory(athlete_id=athlete_user.id, exercise_id=snatch.id, rm_value=70))
    session.commit()
    _, a = _row(coach_client, athlete_user.id)
    assert a["tag"] == "Em dia" and a["missing_rm"] is False

    # Check-in com dor e não visto → Alerta; depois de visto volta
    c = athlete_client.post("/athlete/checkins", json={"answers": {"desempenho": 3, "sono": 8}, "has_pain": True}).json()
    data, a = _row(coach_client, athlete_user.id)
    assert a["tag"] == "Alerta"
    assert data["checkins"] == {"answered": 1, "total": 1, "alerts": 1, "pain": 1, "low": 1}
    coach_client.post(f"/coach/checkins/{c['id']}/seen", json={})
    data, a = _row(coach_client, athlete_user.id)
    assert a["tag"] == "Em dia" and data["checkins"]["alerts"] == 0


def test_sheet_ending_and_not_entered(coach_client, session, coach_user):
    snatch, _ = _exercises(session)
    ending = _make_user(session, name="Bia", email="b@t.com", role="athlete", coach_id=coach_user.id)
    _sheet(coach_client, ending.id, snatch.id, date.today() - timedelta(days=24), weeks=4)
    session.add(AthleteExerciseRMHistory(athlete_id=ending.id, exercise_id=snatch.id, rm_value=60))
    session.commit()
    data, a = _row(coach_client, ending.id)
    assert a["tag"] == "Planilha vence" and data["sheets_ending"] == 1

    novo = coach_client.post("/coach/athletes", json={"name": "Novo", "email": "n@t.com"}).json()
    _, a = _row(coach_client, novo["id"])
    assert a["tag"] == "Não entrou ainda"


def test_activity_today_and_videos(coach_client, athlete_client, athlete_user, session):
    snatch, _ = _exercises(session)
    sid = _sheet(coach_client, athlete_user.id, snatch.id, date.today())
    athlete_client.post("/athlete/complete-day", json={
        "training_sheet_id": sid, "week_number": 1, "day": "monday",
        "sets": [{"exercise_name": "Hang Snatch", "series_index": 0, "status": "fez"}],
    })
    athlete_client.post("/athlete/videos", json={"exercise_name": "Snatch", "video_url": "https://example.com/v.mp4"})
    data, a = _row(coach_client, athlete_user.id)
    assert a["trained_today"] is True and a["days_without_training"] == 0
    assert a["video_today"] is True and a["videos_pending"] == 1
    assert data["videos_pending"] == 1


def test_overview_only_own_athletes(client, session, athlete_user):
    other = _make_user(session, name="Outra", email="o@t.com", role="coach")
    client.headers["Authorization"] = f"Bearer {_token_for(other)}"
    assert client.get("/coach/overview").json()["athletes"] == []


def test_notes(coach_client, client, session, athlete_user, athlete_client):
    assert coach_client.get(f"/coach/athletes/{athlete_user.id}/notes").json()["text"] == ""
    r = coach_client.put(f"/coach/athletes/{athlete_user.id}/notes", json={"text": "Puxa com braço cedo."})
    assert r.status_code == 200
    assert coach_client.get(f"/coach/athletes/{athlete_user.id}/notes").json()["text"] == "Puxa com braço cedo."

    # Atleta não acessa; outra coach também não
    assert athlete_client.get(f"/coach/athletes/{athlete_user.id}/notes").status_code == 403
    other = _make_user(session, name="Outra", email="o@t.com", role="coach")
    client.headers["Authorization"] = f"Bearer {_token_for(other)}"
    assert client.get(f"/coach/athletes/{athlete_user.id}/notes").status_code == 403


def test_notes_deleted_with_athlete_account(coach_client, athlete_client, session, athlete_user):
    from sqlmodel import select
    from models import CoachNote

    coach_client.put(f"/coach/athletes/{athlete_user.id}/notes", json={"text": "x"})
    r = athlete_client.request("DELETE", "/me", json={"password": "test123"})
    assert r.status_code == 200, r.text
    session.expire_all()
    assert session.exec(select(CoachNote)).all() == []
