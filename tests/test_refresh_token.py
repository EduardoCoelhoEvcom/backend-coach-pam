"""Testes do fluxo de refresh token.

Cobre:
  - login/register agora emitem (access, refresh, expires_in)
  - /auth/refresh valida e rotaciona (token rotation: o velho fica inválido)
  - /auth/refresh rejeita token inválido / revogado
  - /auth/logout revoga o refresh
  - /auth/logout-all revoga todos os tokens do usuário (multi-device)
"""


# ---------- Login retorna o par completo ----------
def test_login_returns_access_and_refresh_token(client, coach_user):
    res = client.post(
        "/auth/login",
        data={"username": "coach@test.com", "password": "test123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["expires_in"] > 0
    assert data["token_type"] == "bearer"


def test_register_returns_access_and_refresh_token(client):
    res = client.post(
        "/auth/register",
        json={
            "name": "Novo",
            "email": "novo@test.com",
            "password": "abc123",
            "role": "athlete",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["access_token"]
    assert data["refresh_token"]


# ---------- /auth/refresh ----------
def test_refresh_returns_new_token_pair(client, coach_user):
    login = client.post(
        "/auth/login",
        data={"username": "coach@test.com", "password": "test123"},
    )
    refresh_token = login.json()["refresh_token"]
    old_access = login.json()["access_token"]

    res = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert res.status_code == 200
    data = res.json()

    assert data["access_token"]
    assert data["refresh_token"]
    # Novo refresh deve ser diferente do antigo (rotação)
    assert data["refresh_token"] != refresh_token


def test_refresh_invalidates_old_refresh_token(client, coach_user):
    """Token rotation: depois de usar um refresh, ele não vale mais."""
    login = client.post(
        "/auth/login",
        data={"username": "coach@test.com", "password": "test123"},
    )
    old_refresh = login.json()["refresh_token"]

    # Primeira chamada: ok
    res1 = client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert res1.status_code == 200

    # Tentar reusar o mesmo refresh: deve falhar
    res2 = client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert res2.status_code == 401


def test_refresh_rejects_invalid_token(client):
    res = client.post(
        "/auth/refresh", json={"refresh_token": "garbage-not-a-real-token"}
    )
    assert res.status_code == 401


def test_refresh_returns_working_access_token(client, coach_user):
    """O novo access token retornado pelo /auth/refresh deve funcionar."""
    login = client.post(
        "/auth/login",
        data={"username": "coach@test.com", "password": "test123"},
    )
    refresh_res = client.post(
        "/auth/refresh",
        json={"refresh_token": login.json()["refresh_token"]},
    )
    new_access = refresh_res.json()["access_token"]

    # Usa o novo access pra chamar /me
    me_res = client.get("/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "coach@test.com"


# ---------- /auth/logout ----------
def test_logout_revokes_refresh_token(client, coach_user):
    login = client.post(
        "/auth/login",
        data={"username": "coach@test.com", "password": "test123"},
    )
    refresh_token = login.json()["refresh_token"]

    logout_res = client.post(
        "/auth/logout", json={"refresh_token": refresh_token}
    )
    assert logout_res.status_code == 200

    # Tentar usar o refresh depois do logout: deve falhar
    res = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert res.status_code == 401


def test_logout_does_not_require_auth(client):
    """Logout funciona mesmo sem header de auth (pra recuperar de access expirado)."""
    res = client.post(
        "/auth/logout", json={"refresh_token": "qualquer-coisa-mesmo-invalida"}
    )
    # Não dá erro mesmo com token inválido — idempotente
    assert res.status_code == 200


# ---------- /auth/logout-all ----------
def test_logout_all_revokes_all_user_tokens(client, coach_user):
    """Login 3 vezes (3 devices), logout-all revoga os 3."""
    refreshes = []
    for _ in range(3):
        res = client.post(
            "/auth/login",
            data={"username": "coach@test.com", "password": "test123"},
        )
        refreshes.append(res.json()["refresh_token"])

    # Logout-all com o último access (qualquer um vale)
    last_login = client.post(
        "/auth/login",
        data={"username": "coach@test.com", "password": "test123"},
    )
    access = last_login.json()["access_token"]

    res = client.post(
        "/auth/logout-all",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert res.status_code == 200
    assert res.json()["revoked"] >= 3

    # Cada um dos 3 refreshes anteriores deve estar inválido
    for r in refreshes:
        check = client.post("/auth/refresh", json={"refresh_token": r})
        assert check.status_code == 401
