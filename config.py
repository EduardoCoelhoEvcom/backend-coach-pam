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
# Procura DATABASE_URL primeiro; se não tiver, aceita POSTGRES_URL
# (nome padrão quando o Vercel conecta um Postgres gerenciado no projeto).
# Como último fallback, SQLite local (só pra dev — em serverless o /tmp
# é efêmero, dados são perdidos).
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("POSTGRES_URL")
    or "sqlite:///coach_pam.db"
)

# ---- CORS ----
_cors_raw = os.getenv("CORS_ORIGINS", "*").strip()
if _cors_raw == "*":
    CORS_ORIGINS: list[str] = ["*"]
else:
    CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

# ---- E-mail (SMTP) ----
# Usado para notificar o admin quando alguém esquece a senha.
# Em produção, defina essas variáveis no Render. Com Gmail, crie uma
# "Senha de app" (App Password) e use ela em SMTP_PASSWORD.
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
# Para quem vão os alertas (ex.: aviso de senha esquecida).
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "eduardocoelho12y@gmail.com")
# Remetente; por padrão usa o próprio SMTP_USER.
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "") or SMTP_USER

# ---- Notificação push (ntfy.sh) ----
# Alternativa/complemento ao e-mail para alertas administrativos.
# Como funciona: o admin instala o app `ntfy` (iOS/Android), se inscreve
# no tópico definido em NTFY_TOPIC, e o backend faz um POST pra
# https://ntfy.sh/<topico> — a notificação chega como push no celular.
# O tópico é "segredo por obscuridade": qualquer um com o nome pode
# enviar, então usa um nome único e difícil de adivinhar.
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

# ---- Object storage (Cloudflare R2) ----
# Usado para upload de vídeos de exercício pelos atletas, sem passar
# pelo backend (o Vercel tem limite de 4.5 MB por request). O backend
# só gera URLs pre-assinadas; o cliente faz PUT direto no R2.
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.getenv("R2_BUCKET", "")
R2_ENDPOINT = os.getenv(
    "R2_ENDPOINT",
    f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else "",
)
# URL pública do bucket (pub-xxx.r2.dev ou domínio custom).
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")
# Limite por vídeo (MB). Validado antes do upload.
VIDEO_MAX_MB = int(os.getenv("VIDEO_MAX_MB", "100"))
