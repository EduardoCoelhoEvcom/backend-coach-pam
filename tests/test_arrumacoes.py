"""Preços por frequência, aviso pra coach, PDF e limpeza da biblioteca."""
from datetime import datetime, timezone

import routers.feedback as fb
import services.storage as storage
from models import Exercise, ExerciseCategory
from services.seeding import dedupe_global_exercises


def test_plano_com_frequencia(coach_client):
    r = coach_client.post("/coach/athletes", json={
        "name": "Ana Teste", "email": "ana.freq@example.com", "plan": "experience", "frequency": 5,
    })
    assert r.status_code == 200, r.text
    p = coach_client.get(f"/coach/athletes/{r.json()['id']}/plan").json()
    assert p["plan_name"] == "Experience · 5x na semana"
    assert p["monthly_price"] == 370.0 and p["months_total"] == 6

    r = coach_client.post("/coach/athletes", json={
        "name": "Bia Teste", "email": "bia.freq@example.com", "plan": "avulso", "frequency": 3,
    })
    p = coach_client.get(f"/coach/athletes/{r.json()['id']}/plan").json()
    assert (p["plan_name"], p["monthly_price"]) == ("Mês avulso · 3x na semana", 310.0)

    bad = coach_client.post("/coach/athletes", json={
        "name": "Caio", "email": "caio.freq@example.com", "plan": "avulso", "frequency": 4})
    assert bad.status_code == 422


def test_avisa_coach_no_video_e_checkin(athlete_client, monkeypatch):
    sent = []
    monkeypatch.setattr(fb, "notify_coach", lambda title, body, tags="": sent.append((title, body)))
    athlete_client.post("/athlete/videos", json={"exercise_name": "Snatch", "video_url": "https://x/v.mp4"})
    athlete_client.post("/athlete/checkins", json={"answers": {"sono": 3}, "has_pain": True, "pain_note": "ombro"})
    assert sent[0][0] == "Vídeo novo pra corrigir" and "Snatch" in sent[0][1]
    assert sent[1][0] == "Check-in novo" and "dor" in sent[1][1]


def test_pdf_upload_url(coach_client, monkeypatch):
    monkeypatch.setattr(storage, "is_r2_configured", lambda: True)
    monkeypatch.setattr(storage, "presigned_put_url", lambda key, ct, expires_in: f"https://r2/put/{key}")
    monkeypatch.setattr(storage, "public_url_for", lambda key: f"https://cdn/{key}")
    r = coach_client.post("/coach/files/pdf-upload-url", json={"content_type": "application/pdf", "size_bytes": 1000})
    assert r.status_code == 200 and r.json()["public_url"].endswith(".pdf")
    assert coach_client.post("/coach/files/pdf-upload-url", json={"content_type": "image/png"}).status_code == 422


def test_limpa_exercicio_repetido(session):
    now = datetime.now(timezone.utc)
    main_cat = ExerciseCategory(coach_id=None, type="lpo", name="Força X", sort_order=1)
    var_cat = ExerciseCategory(coach_id=None, type="lpo", name="Variações", sort_order=2)
    session.add(main_cat)
    session.add(var_cat)
    session.commit()
    a = Exercise(coach_id=None, category_id=main_cat.id, name="Zercher Squat", type="lpo", created_at=now, updated_at=now)
    b = Exercise(coach_id=None, category_id=var_cat.id, name="zercher  squat", type="lpo", created_at=now, updated_at=now)
    session.add(a)
    session.add(b)
    session.commit()
    child = Exercise(coach_id=None, category_id=var_cat.id, name="Pause Zercher", type="lpo",
                     rm_source_exercise_id=b.id, created_at=now, updated_at=now)
    session.add(child)
    session.commit()

    assert dedupe_global_exercises(session) >= 1
    session.refresh(a)
    session.refresh(b)
    session.refresh(child)
    assert a.is_active and not b.is_active
    assert child.rm_source_exercise_id == a.id
    assert dedupe_global_exercises(session) == 0  # idempotente
