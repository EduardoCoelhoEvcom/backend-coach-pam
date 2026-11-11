"""Ficha do atleta: histórico de check-ins e exclusões pela coach."""


def test_historico_e_excluir_checkin(athlete_client, coach_client, athlete_user):
    c = athlete_client.post("/athlete/checkins", json={"answers": {"sono": 8, "rm": "sim"}}).json()
    hist = coach_client.get(f"/coach/athletes/{athlete_user.id}/checkins")
    assert hist.status_code == 200
    assert [x["id"] for x in hist.json()] == [c["id"]]
    assert hist.json()[0]["answers"] == {"sono": 8, "rm": "sim"}

    assert coach_client.delete(f"/coach/checkins/{c['id']}").status_code == 200
    assert coach_client.get(f"/coach/athletes/{athlete_user.id}/checkins").json() == []
    assert coach_client.delete(f"/coach/checkins/{c['id']}").status_code == 404


def test_excluir_video_com_correcoes(athlete_client, coach_client, athlete_user):
    v = athlete_client.post("/athlete/videos", json={"exercise_name": "Snatch", "video_url": "https://x/v.mp4"}).json()
    v2 = athlete_client.post("/athlete/videos", json={
        "exercise_name": "Snatch", "video_url": "https://x/v2.mp4", "compare_to_id": v["id"]}).json()
    coach_client.post(f"/coach/videos/{v['id']}/corrections", json={"corrections": [{"title": "Cotovelo"}]})

    assert coach_client.delete(f"/coach/videos/{v['id']}").status_code == 200
    restantes = coach_client.get(f"/coach/videos?status=&athlete_id={athlete_user.id}").json()
    assert [x["id"] for x in restantes] == [v2["id"]]
    assert restantes[0]["compare_to_id"] is None


def test_atleta_nao_exclui(athlete_client, athlete_user):
    assert athlete_client.get(f"/coach/athletes/{athlete_user.id}/checkins").status_code == 403
