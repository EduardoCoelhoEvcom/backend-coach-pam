"""Configurações carregadas do .env.

Importado por todos os outros módulos. O loader é minimalista (sem
dependência externa) e popula os.environ se ainda não estiver definido.
"""
import os
from pathlib import Path


def _load_dotenv(env_filename: str = ".env") -> None:
    """Lê .env ao lado deste arquivo e popula os.environ. Idempotente."""
    p = Path(__file__).parent / env_filename
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(
            f"Variável de ambiente obrigatória ausente: {name}. "
            f"Crie um arquivo .env baseado em .env.example."
        )
    return val


# ---- Auth / JWT ----
SECRET_KEY = _require_env("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
# Access token: padrão recomendado é curto (15min) com refresh token cobrindo
# o tempo longo. Mantém 1440 como default pra não quebrar quem ainda não
# atualizou o app — quando o app passar a usar /auth/refresh, troca pra 15.
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

# ---- Database ----
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///coach_pam.db")

# ---- CORS ----
_cors_raw = os.getenv("CORS_ORIGINS", "*").strip()
if _cors_raw == "*":
    CORS_ORIGINS: list[str] = ["*"]
else:
    CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]
