"""Correção no vídeo com desenho da coach sobre o quadro pausado."""


def test_desenho_salvo_e_limpo(athlete_client, coach_client):
    v = athlete_client.post("/athlete/videos", json={"exercise_name": "Snatch", "video_url": "https://x/v.mp4"}).json()
    r = coach_client.post(f"/coach/videos/{v['id']}/corrections", json={"corrections": [
        {"title": "Correção 1", "timestamp_sec": 2.5, "is_focus": True, "drawing": [
            {"t": "line", "c": "#FF4D4D", "p": [[0.1, 0.2], [0.5, 1.7]]},
            {"t": "circle", "p": [[0.3, 0.3], [0.4, 0.4]]},
            {"t": "bomba", "p": [[0, 0], [1, 1]]},
            {"t": "free", "p": [[0.2, 0.2]]},
        ]},
        {"title": "Correção extra: pés mais abertos"},
    ]})
    assert r.status_code == 200, r.text
    corr = athlete_client.get("/athlete/corrections/pending").json()[0]["corrections"]
    first = next(c for c in corr if c["is_focus"])
    assert first["timestamp_sec"] == 2.5
    assert first["drawing"] == [
        {"t": "line", "c": "#FF4D4D", "p": [[0.1, 0.2], [0.5, 1.0]]},
        {"t": "circle", "c": "#FF4D4D", "p": [[0.3, 0.3], [0.4, 0.4]]},
    ]
    extra = next(c for c in corr if not c["is_focus"])
    assert extra["drawing"] is None and extra["timestamp_sec"] is None
