"""Áudio de correção gravado pela coach no app (upload direto pro R2)."""
import services.storage as storage
from services.storage import make_audio_key


def _fake_r2(monkeypatch):
    monkeypatch.setattr(storage, "is_r2_configured", lambda: True)
    monkeypatch.setattr(storage, "presigned_put_url", lambda key, content_type, expires_in: f"https://r2.test/put/{key}?ct={content_type}")
    monkeypatch.setattr(storage, "public_url_for", lambda key: f"https://cdn.test/{key}")


def test_coach_gets_upload_url(coach_client, coach_user, monkeypatch):
    _fake_r2(monkeypatch)
    r = coach_client.post("/coach/audio/upload-url", json={"content_type": "audio/webm;codecs=opus", "size_bytes": 300_000})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"].startswith(f"audios/{coach_user.id}/") and body["key"].endswith(".webm")
    assert body["public_url"] == f"https://cdn.test/{body['key']}"
    assert "ct=audio/webm" in body["put_url"]  # assina sem o ";codecs=..."


def test_only_audio_and_size_limit(coach_client, monkeypatch):
    _fake_r2(monkeypatch)
    assert coach_client.post("/coach/audio/upload-url", json={"content_type": "video/mp4"}).status_code == 422
    r = coach_client.post("/coach/audio/upload-url", json={"content_type": "audio/mp4", "size_bytes": 500 * 1024 * 1024})
    assert r.status_code == 413


def test_athlete_cannot_and_r2_off(athlete_client, coach_client):
    assert athlete_client.post("/coach/audio/upload-url", json={"content_type": "audio/webm"}).status_code == 403
    # Sem as variáveis R2_* (como nos testes), avisa em vez de quebrar
    assert coach_client.post("/coach/audio/upload-url", json={"content_type": "audio/webm"}).status_code == 503


def test_audio_key_extension():
    assert make_audio_key(7, "audio/mp4").endswith(".m4a")
    assert make_audio_key(7, "audio/ogg").endswith(".ogg")
    assert make_audio_key(7, "audio/esquisito").endswith(".webm")
    assert make_audio_key(7, "audio/webm").startswith("audios/7/")
