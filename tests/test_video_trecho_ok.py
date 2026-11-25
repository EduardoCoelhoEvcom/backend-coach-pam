"""Trecho do vídeo escolhido pelo atleta e o "tudo certo" da coach."""


def _video(athlete_client, **extra):
    r = athlete_client.post("/athlete/videos", json={"exercise_name": "Snatch", "video_url": "https://x/v.mp4", **extra})
    return r


def test_trecho_do_video(athlete_client, coach_client):
    r = _video(athlete_client, trim_start=2.5, trim_end=9)
    assert r.status_code == 200, r.text
    assert (r.json()["trim_start"], r.json()["trim_end"]) == (2.5, 9)
    q = coach_client.get("/coach/videos").json()
    assert (q[0]["trim_start"], q[0]["trim_end"]) == (2.5, 9)
    # sem trecho continua funcionando
    assert _video(athlete_client).json()["trim_start"] is None
    assert _video(athlete_client, trim_start=3, trim_end=3.2).status_code == 422
    assert _video(athlete_client, trim_start=-1).status_code == 422


def test_tudo_certo(athlete_client, coach_client):
    vid = _video(athlete_client).json()["id"]
    r = coach_client.post(f"/coach/videos/{vid}/all-good", json={"message": " Ótima puxada! "})
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["all_good"], r.json()["coach_message"]) == ("corrigido", True, "Ótima puxada!")
    assert coach_client.get("/coach/videos").json() == []  # saiu da fila
    pend = athlete_client.get("/athlete/corrections/pending").json()
    assert pend[0]["all_good"] and pend[0]["corrections"] == []
    athlete_client.post(f"/athlete/videos/{vid}/ack")
    assert athlete_client.get("/athlete/corrections/pending").json() == []


def test_tudo_certo_sem_recado_e_bloqueios(athlete_client, coach_client):
    vid = _video(athlete_client).json()["id"]
    assert coach_client.post(f"/coach/videos/{vid}/all-good", json={}).json()["coach_message"] is None
    other = _video(athlete_client).json()["id"]
    coach_client.post(f"/coach/videos/{other}/corrections", json={"corrections": [{"title": "Cotovelo"}]})
    assert coach_client.post(f"/coach/videos/{other}/all-good", json={}).status_code == 400
    assert athlete_client.post(f"/coach/videos/{vid}/all-good", json={}).status_code == 403
    # correção depois de um "tudo certo" desliga o tudo certo
    third = _video(athlete_client).json()["id"]
    coach_client.post(f"/coach/videos/{third}/all-good", json={"message": "ok"})
    r = coach_client.post(f"/coach/videos/{third}/corrections", json={"corrections": [{"title": "Pés"}]})
    assert r.json()["all_good"] is False and r.json()["coach_message"] is None
