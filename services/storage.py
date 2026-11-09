"""Upload de arquivos para o Cloudflare R2 via URLs pre-assinadas (S3).

Fluxo:
1. App chama POST /athlete/videos/upload-url informando o tamanho/tipo.
2. Backend gera uma "presigned URL" PUT válida por ~5 min e devolve
   {put_url, public_url, key}.
3. App faz PUT direto no R2 com o arquivo binário no body.
4. App chama POST /athlete/videos com a public_url como video_url.

O backend NUNCA recebe o vídeo (Vercel tem limite de 4.5 MB por request).
"""
import logging
import secrets
from typing import Optional

from config import (
    R2_ACCESS_KEY_ID,
    R2_BUCKET,
    R2_ENDPOINT,
    R2_PUBLIC_URL,
    R2_SECRET_ACCESS_KEY,
)

logger = logging.getLogger(__name__)


def is_r2_configured() -> bool:
    missing = [
        name
        for name, val in [
            ("R2_BUCKET", R2_BUCKET),
            ("R2_ENDPOINT", R2_ENDPOINT),
            ("R2_ACCESS_KEY_ID", R2_ACCESS_KEY_ID),
            ("R2_SECRET_ACCESS_KEY", R2_SECRET_ACCESS_KEY),
            ("R2_PUBLIC_URL", R2_PUBLIC_URL),
        ]
        if not val
    ]
    if missing:
        logger.error("[r2] variáveis ausentes/vazias: %s", ", ".join(missing))
        return False
    return True


def _client():
    """Lazy import pra não carregar boto3 em testes que não usam R2."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",  # R2 ignora região mas boto3 exige
        config=Config(signature_version="s3v4"),
    )


def make_video_key(athlete_id: int, filename: Optional[str] = None) -> str:
    """Gera chave única pro R2. Usa ID aleatório pra ser impossível de adivinhar."""
    ext = "mp4"
    if filename and "." in filename:
        maybe = filename.rsplit(".", 1)[-1].lower()
        if maybe in {"mp4", "mov", "m4v", "webm", "avi", "mkv"}:
            ext = maybe
    rand = secrets.token_urlsafe(16)
    return f"videos/{athlete_id}/{rand}.{ext}"


def presigned_put_url(
    key: str,
    content_type: str = "video/mp4",
    expires_in: int = 300,
) -> str:
    """Gera URL assinada de upload (PUT) válida por `expires_in` segundos."""
    if not is_r2_configured():
        raise RuntimeError("R2 não configurado. Verifique R2_* no .env/Vercel.")

    client = _client()
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": R2_BUCKET,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )
    return url


def public_url_for(key: str) -> str:
    """URL pública (via R2.dev subdomain) pra tocar/baixar o arquivo."""
    base = R2_PUBLIC_URL.rstrip("/")
    return f"{base}/{key}"
