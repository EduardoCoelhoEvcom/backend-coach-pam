"""Check-ins, correções de vídeo e plano do atleta."""
from datetime import date, timedelta

from tests.conftest import _make_user, _token_for


def test_checkin_flow(athlete_client, coach_client, athlete_user):
    cur = athlete_client.get("/athlete/checkins/current")
    assert cur.status_code == 200
    assert cur.json()["checkin"] is None
    assert cur.json()["expected_kind"] == "inicio_mes"  # primeiro check-in

    r = athlete_client.post("/athlete/checkins", json={
        "answers": {"sono": "ok", "energia": 4, "rm_novo": "nao"},
        "has_pain": True,
        "pain_note": "  ombro direito no jerk ",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_pain"] is True and body["needs_attention"] is True
    assert body["pain_note"] == "ombro direito no jerk"

    # Reenviar na mesma semana atualiza (não duplica)
    r2 = athlete_client.post("/athlete/checkins", json={"answers": {"sono": "ruim"}})
    assert r2.json()["id"] == body["id"]
    assert r2.json()["has_pain"] is False and r2.json()["pain_note"] is None

    week = coach_client.get("/coach/checkins").json()
    assert [c["athlete_name"] for c in week["answered"]] == [athlete_user.name]
    assert week["missing"] == []

    seen = coach_client.post(f"/coach/checkins/{body['id']}/seen", json={"reply": "Boa!"})
    assert seen.status_code == 200
    assert seen.json()["coach_seen_at"] and seen.json()["coach_reply"] == "Boa!"


def test_coach_sees_missing_and_not_other_coaches(coach_client, session, coach_user):
    other_coach = _make_user(session, name="Outra", email="o@t.com", role="coach")
    _make_user(session, name="Bia", email="b@t.com", role="athlete", coach_id=coach_user.id)
    _make_user(session, name="Zé", email="z@t.com", role="athlete", coach_id=other_coach.id)
    week = coach_client.get("/coach/checkins").json()
    assert {m["name"] for m in week["missing"]} == {"Bia"}


def test_video_correction_flow(athlete_client, coach_client):
    v = athlete_client.post("/athlete/videos", json={
        "exercise_name": "Squat Snatch",
        "video_url": "https://example.com/v1.mp4",
        "week_number": 1, "day": "Treino 1",
    })
    assert v.status_code == 200, v.text
    vid = v.json()["id"]
    assert v.json()["status"] == "pendente"

    fila = coach_client.get("/coach/videos").json()
    assert [x["id"] for x in fila] == [vid]
    assert fila[0]["athlete_name"] == "Atleta Test"

    bad = coach_client.post(f"/coach/videos/{vid}/corrections", json={"corrections": []})
    assert bad.status_code == 422

    c = coach_client.post(f"/coach/videos/{vid}/corrections", json={"corrections": [
        {"title": "Barra mais perto do quadril"},
        {"title": "Cotovelo travado antes de sentar", "timestamp_sec": 4,
         "audio_url": "https://example.com/a.m4a", "audio_duration_sec": 18, "is_focus": True},
    ]})
    assert c.status_code == 200, c.text
    assert c.json()["status"] == "corrigido"
    assert c.json()["corrections"][0]["is_focus"] is True  # foco primeiro

    assert coach_client.get("/coach/videos").json() == []
    pend = athlete_client.get("/athlete/corrections/pending").json()
    assert len(pend) == 1 and len(pend[0]["corrections"]) == 2

    ack = athlete_client.post(f"/athlete/videos/{vid}/ack")
    assert ack.status_code == 200 and ack.json()["acknowledged_at"]
    assert athlete_client.get("/athlete/corrections/pending").json() == []

    # Antes e depois: novo vídeo apontando pro anterior
    v2 = athlete_client.post("/athlete/videos", json={
        "exercise_name": "Squat Snatch", "video_url": "https://example.com/v2.mp4",
        "compare_to_id": vid,
    })
    assert v2.status_code == 200 and v2.json()["compare_to_id"] == vid


def test_coach_cannot_correct_other_coach_video(athlete_client, client, session):
    vid = athlete_client.post("/athlete/videos", json={
        "exercise_name": "Clean", "video_url": "https://example.com/x.mp4",
    }).json()["id"]
    intruder = _make_user(session, name="Intrusa", email="i@t.com", role="coach")
    client.headers["Authorization"] = f"Bearer {_token_for(intruder)}"
    r = client.post(f"/coach/videos/{vid}/corrections", json={"corrections": [{"title": "x"}]})
    assert r.status_code == 403
    assert client.get("/coach/videos").json() == []


def test_plan(athlete_client, coach_client, athlete_user):
    assert athlete_client.get("/athlete/plan").json() is None
    start = date.today() - timedelta(days=40)
    r = coach_client.put(f"/coach/athletes/{athlete_user.id}/plan", json={
        "plan_name": "Experience", "months_total": 6, "monthly_price": 190,
        "start_date": start.isoformat(),
    })
    assert r.status_code == 200, r.text
    p = athlete_client.get("/athlete/plan").json()
    assert p["plan_name"] == "Experience" and p["months_total"] == 6
    assert p["current_month"] == 2 and p["monthly_price"] == 190

    coach_client.put(f"/coach/athletes/{athlete_user.id}/plan", json={
        "plan_name": "Mês avulso", "monthly_price": 230, "show_price_to_athlete": False,
    })
    p = athlete_client.get("/athlete/plan").json()
    assert p["plan_name"] == "Mês avulso" and p["monthly_price"] is None


def test_delete_account_removes_feedback_data(athlete_client, coach_client, session):
    from sqlmodel import select
    from models import VideoCorrection, VideoSubmission, WeeklyCheckin
    athlete_client.post("/athlete/checkins", json={"answers": {"sono": "ok"}})
    vid = athlete_client.post("/athlete/videos", json={
        "exercise_name": "Clean", "video_url": "https://example.com/x.mp4",
    }).json()["id"]
    coach_client.post(f"/coach/videos/{vid}/corrections", json={"corrections": [{"title": "ok"}]})
    athlete_client.post("/athlete/videos", json={
        "exercise_name": "Clean", "video_url": "https://example.com/y.mp4", "compare_to_id": vid,
    })
    exp = athlete_client.get("/me/export").json()
    assert len(exp["checkins"]) == 1 and len(exp["videos"]) == 2 and len(exp["video_corrections"]) == 1

    r = athlete_client.request("DELETE", "/me", json={"password": "test123"})
    assert r.status_code == 200, r.text
    session.expire_all()
    assert session.exec(select(WeeklyCheckin)).all() == []
    assert session.exec(select(VideoSubmission)).all() == []
    assert session.exec(select(VideoCorrection)).all() == []
