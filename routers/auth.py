"""Rotas de autenticação: register, login, /me, /me/export, DELETE /me."""
import logging
import os
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import EmailStr
from sqlmodel import Session, SQLModel, select

from config import ACCESS_TOKEN_EXPIRE_MINUTES
from db import get_session
from models import (
    AthleteExerciseRMHistory,
    TrainingDayCompletion,
    TrainingSetExecution,
    TrainingSheet,
)
from models.user import User, get_user_by_email
from rate_limit import limiter
from security import (
    create_access_token,
    get_current_user,
    get_password_hash,
    issue_refresh_token,
    revoke_all_user_tokens,
    revoke_refresh_token,
    verify_password,
    verify_refresh_token,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


# ---------- Schemas ----------
class UserCreate(SQLModel):
    name: str
    email: EmailStr  # validação automática de formato de email
    password: str
    role: str
    coach_code: Optional[str] = None  # exigido só quando role == "coach"


class TokenResponse(SQLModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # segundos até o access expirar
    name: str
    role: str


class RefreshRequest(SQLModel):
    refresh_token: str


class RefreshResponse(SQLModel):
    """Resposta do /auth/refresh: novo access + novo refresh (rotação)."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LogoutRequest(SQLModel):
    refresh_token: str


# ---------- Routes ----------
@router.post("/auth/register", response_model=TokenResponse)
@limiter.limit("5/hour")  # 5 cadastros por IP por hora — bloqueia spam
def register(
    request: Request,
    user_in: UserCreate,
    session: Session = Depends(get_session),
):
    name = (user_in.name or "").strip()
    email = (user_in.email or "").strip().lower()
    password = user_in.password or ""
    role_raw = (user_in.role or "athlete").strip().lower()

    if not name:
        raise HTTPException(status_code=400, detail="Nome é obrigatório.")
    if not email:
        raise HTTPException(status_code=400, detail="Email é obrigatório.")
    if len(password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Senha precisa ter pelo menos 6 caracteres.",
        )

    if get_user_by_email(email, session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email já cadastrado",
        )

    # Role final: athlete por padrão. Coach só com o código correto.
    final_role = "athlete"
    if role_raw == "coach":
        expected_code = (os.environ.get("COACH_REGISTER_CODE") or "ADMIN").strip()
        provided_code = (user_in.coach_code or "").strip()
        if provided_code != expected_code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Código de coach inválido.",
            )
        final_role = "coach"

    user = User(
        name=name,
        email=email,
        password_hash=get_password_hash(password),
        role=final_role,
        status_pagamento="ok",
        vencimento=date.today() + timedelta(days=30),
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    access_token = create_access_token(
        data={"sub": user.id, "role": user.role},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_plain, _ = issue_refresh_token(user, session)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_plain,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        name=user.name,
        role=user.role,
    )


@router.post("/auth/login", response_model=TokenResponse)
@limiter.limit("10/minute")  # 10 tentativas de login por IP por minuto
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    email = (form_data.username or "").strip().lower()
    user = get_user_by_email(email, session)

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Email ou senha inválidos")

    access_token = create_access_token(
        data={"sub": user.id, "role": user.role},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_plain, _ = issue_refresh_token(user, session)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_plain,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        name=user.name,
        role=user.role,
    )


@router.post("/auth/refresh", response_model=RefreshResponse)
@limiter.limit("60/minute")  # generoso — app pode renovar várias vezes em sessão
def refresh(
    request: Request,
    body: RefreshRequest,
    session: Session = Depends(get_session),
):
    """Rotação de refresh token: valida o atual, revoga, e emite novo par.

    Cliente deve substituir os dois tokens (access + refresh) pelos retornados.
    """
    user = verify_refresh_token(body.refresh_token, session)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Refresh token inválido ou expirado.",
        )

    # Revoga o atual (token rotation — defesa contra reuso/replay).
    revoke_refresh_token(body.refresh_token, session)

    # Emite par novo.
    access_token = create_access_token(
        data={"sub": user.id, "role": user.role},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    new_refresh, _ = issue_refresh_token(user, session)

    return RefreshResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/auth/logout")
def logout(
    body: LogoutRequest,
    session: Session = Depends(get_session),
):
    """Revoga o refresh token enviado (logout do device atual).

    Não exige access token — assim o cliente consegue deslogar mesmo se o
    access já tiver expirado. Não falha se o token já não existe.
    """
    revoke_refresh_token(body.refresh_token, session)
    return {"ok": True}


@router.post("/auth/logout-all")
def logout_all(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Revoga TODOS os refresh tokens do usuário logado.
    Útil quando o usuário suspeita que sua conta foi comprometida."""
    n = revoke_all_user_tokens(current_user.id, session)
    return {"ok": True, "revoked": n}


@router.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "status_pagamento": current_user.status_pagamento,
    }


# ============================================================
# LGPD: direito de exportar e deletar dados pessoais
# ============================================================
class ConfirmPasswordRequest(SQLModel):
    """Body de DELETE /me — exige re-confirmação de senha."""
    password: str


@router.get("/me/export")
def export_my_data(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Direito de portabilidade (LGPD art. 18 V).

    Retorna em JSON tudo que o sistema guarda sobre o usuário logado.
    Útil pra ele baixar/migrar antes de pedir exclusão.
    """
    user_id = current_user.id

    sheets = session.exec(
        select(TrainingSheet).where(
            (TrainingSheet.athlete_id == user_id)
            | (TrainingSheet.coach_id == user_id)
        )
    ).all()

    completions = session.exec(
        select(TrainingDayCompletion).where(
            TrainingDayCompletion.athlete_id == user_id
        )
    ).all()

    executions = session.exec(
        select(TrainingSetExecution).where(
            TrainingSetExecution.athlete_id == user_id
        )
    ).all()

    rms = session.exec(
        select(AthleteExerciseRMHistory).where(
            AthleteExerciseRMHistory.athlete_id == user_id
        )
    ).all()

    return {
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "role": current_user.role,
            "status_pagamento": current_user.status_pagamento,
            "vencimento": (
                current_user.vencimento.isoformat()
                if current_user.vencimento
                else None
            ),
            "created_at": current_user.created_at.isoformat(),
        },
        "training_sheets": [s.model_dump(mode="json") for s in sheets],
        "training_day_completions": [
            c.model_dump(mode="json") for c in completions
        ],
        "training_set_executions": [
            e.model_dump(mode="json") for e in executions
        ],
        "rm_history": [r.model_dump(mode="json") for r in rms],
    }


@router.delete("/me")
def delete_my_account(
    body: ConfirmPasswordRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Direito de eliminação (LGPD art. 18 VI).

    Apaga o usuário e TODOS os dados associados.
    Operação irreversível — exige re-confirmação de senha.
    """
    if not verify_password(body.password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Senha incorreta.")

    user_id = current_user.id

    # Apaga em ordem (filhos antes de pais pra não violar FK).
    session.exec(
        select(TrainingSetExecution).where(
            TrainingSetExecution.athlete_id == user_id
        )
    )
    for row in session.exec(
        select(TrainingSetExecution).where(
            TrainingSetExecution.athlete_id == user_id
        )
    ).all():
        session.delete(row)

    for row in session.exec(
        select(TrainingDayCompletion).where(
            TrainingDayCompletion.athlete_id == user_id
        )
    ).all():
        session.delete(row)

    for row in session.exec(
        select(AthleteExerciseRMHistory).where(
            AthleteExerciseRMHistory.athlete_id == user_id
        )
    ).all():
        session.delete(row)

    for row in session.exec(
        select(TrainingSheet).where(
            (TrainingSheet.athlete_id == user_id)
            | (TrainingSheet.coach_id == user_id)
        )
    ).all():
        session.delete(row)

    session.delete(current_user)
    session.commit()

    logger.info("user_deleted_self", extra={"user_id": user_id})

    return {"ok": True, "message": "Conta e dados removidos."}
