"""Hashing de senha, geração/validação de JWT e dependências de auth.

Inclui também emissão e verificação de refresh tokens (modelo
RefreshToken). O refresh token em si é um string aleatório de 32 bytes;
no banco guardamos apenas o SHA256.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlmodel import Session, select

from config import ALGORITHM, REFRESH_TOKEN_EXPIRE_DAYS, SECRET_KEY
from db import get_session
from models.refresh_token import RefreshToken
from models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


# ---- Senha ----
def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# ---- JWT ----
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    to_encode["sub"] = str(to_encode["sub"])
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ---- Dependências FastAPI ----
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não foi possível validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_raw = payload.get("sub")
        if user_id_raw is None:
            raise credentials_exception

        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    user = session.get(User, user_id)
    if not user:
        raise credentials_exception
    return user


def require_role(role: str):
    """Factory: retorna uma dependency que exige current_user.role == role."""
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acesso permitido apenas para {role}",
            )
        return current_user
    return role_checker


# ============================================================
# Refresh tokens
# ============================================================
def _hash_token(plain: str) -> str:
    """SHA256 hex digest. Determinístico — usado pra lookup."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def issue_refresh_token(
    user: User, session: Session
) -> Tuple[str, RefreshToken]:
    """Cria um refresh token novo no banco e retorna (token_plain, row).

    Apenas o caller (endpoint de login/refresh) recebe o token plain pra
    devolver na response. O banco só tem o hash.
    """
    plain = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=REFRESH_TOKEN_EXPIRE_DAYS
    )

    row = RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(plain),
        expires_at=expires_at,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return plain, row


def verify_refresh_token(plain: str, session: Session) -> Optional[User]:
    """Valida um refresh token recebido. Retorna o User se válido, None caso contrário.

    Falha quando: token não existe, foi revogado, ou expirou.
    """
    if not plain:
        return None

    row = session.exec(
        select(RefreshToken).where(RefreshToken.token_hash == _hash_token(plain))
    ).first()

    if not row:
        return None
    if row.revoked_at is not None:
        return None

    # SQLite armazena datetime sem tz info — comparação precisa ser naive vs naive
    # ou tz-aware vs tz-aware. Normalizamos pra UTC aware.
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None

    return session.get(User, row.user_id)


def revoke_refresh_token(plain: str, session: Session) -> bool:
    """Marca o token como revogado. Retorna True se algo foi revogado."""
    row = session.exec(
        select(RefreshToken).where(RefreshToken.token_hash == _hash_token(plain))
    ).first()
    if not row or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    return True


def revoke_all_user_tokens(user_id: int, session: Session) -> int:
    """Revoga todos os refresh tokens ativos de um usuário (logout em todos
    os devices). Retorna o número de tokens revogados."""
    rows = session.exec(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at == None,  # noqa: E711
        )
    ).all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.revoked_at = now
        session.add(row)
    session.commit()
    return len(rows)
