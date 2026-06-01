"""Testes de /auth/* e /me."""


# ---------- /auth/register ----------
def test_register_creates_athlete_and_returns_token(client):
    res = client.post(
        "/auth/register",
        json={
            "name": "Novo Atleta",
            "email": "novo@test.com",
            "password": "abc123",
            "role": "athlete",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["name"] == "Novo Atleta"
    assert data["role"] == "athlete"


def test_register_blocks_coach_role(client):
    """Registro auto-serviço NÃO pode criar coach."""
    res = client.post(
        "/auth/register",
        json={
            "name": "Tentativa Coach",
            "email": "fake_coach@test.com",
            "password": "abc123",
            "role": "coach",
        },
    )
    assert res.status_code == 403


def test_register_rejects_short_password(client):
    res = client.post(
        "/auth/register",
        json={
            "name": "X",
            "email": "x@test.com",
            "password": "12345",  # < 6 chars
            "role": "athlete",
        },
    )
    assert res.status_code == 400


def test_register_rejects_invalid_email_format(client):
    """EmailStr deve barrar formato inválido com 422 (validation)."""
    res = client.post(
        "/auth/register",
        json={
            "name": "X",
            "email": "not-an-email",
            "password": "abc123",
            "role": "athlete",
        },
    )
    assert res.status_code == 422  # validation error do Pydantic


def test_register_rejects_duplicate_email(client):
    payload = {
        "name": "A",
        "email": "dup@test.com",
        "password": "abc123",
        "role": "athlete",
    }
    res1 = client.post("/auth/register", json=payload)
    assert res1.status_code == 200

    res2 = client.post("/auth/register", json=payload)
    assert res2.status_code == 409


# ---------- /auth/login ----------
def test_login_with_valid_credentials(client, coach_user):
    """coach_user fixture cria coach@test.com com senha 'test123'."""
    res = client.post(
        "/auth/login",
        data={"username": "coach@test.com", "password": "test123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["access_token"]
    assert data["role"] == "coach"


def test_login_fails_with_wrong_password(client, coach_user):
    res = client.post(
        "/auth/login",
        data={"username": "coach@test.com", "password": "wrong"},
    )
    assert res.status_code == 400


def test_login_fails_with_unknown_email(client):
    res = client.post(
        "/auth/login",
        data={"username": "ghost@test.com", "password": "whatever"},
    )
    assert res.status_code == 400


# ---------- /me ----------
def test_me_returns_current_user(coach_client, coach_user):
    res = coach_client.get("/me")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == coach_user.id
    assert data["email"] == "coach@test.com"
    assert data["role"] == "coach"


def test_me_rejects_unauthenticated(client):
    res = client.get("/me")
    assert res.status_code == 401


def test_me_rejects_invalid_token(client):
    client.headers.update({"Authorization": "Bearer not-a-valid-jwt"})
    res = client.get("/me")
    assert res.status_code == 401
