"""Notificação push via ntfy.sh.

Usado para alertar o admin — hoje, o aviso de "esqueci a senha".

ntfy.sh é um serviço gratuito e open-source: basta um POST HTTP com o
corpo da mensagem para `https://ntfy.sh/<topico>`. A notificação chega
no app ntfy instalado no celular do admin.

Se NTFY_TOPIC não estiver configurado, apenas registra um aviso no log
e retorna False (não derruba a aplicação).
"""
import logging
import urllib.error
import urllib.request

from config import NTFY_SERVER, NTFY_TOPIC

logger = logging.getLogger(__name__)


def is_ntfy_configured() -> bool:
    return bool(NTFY_TOPIC)


def send_ntfy(*, title: str, body: str, priority: str = "default", tags: str = "") -> bool:
    """Envia notificação push via ntfy. Retorna True se conseguiu.

    priority: min | low | default | high | urgent
    tags: lista separada por vírgula (emojis), ex.: "warning,key"
    """
    if not is_ntfy_configured():
        logger.warning(
            "[ntfy] NTFY_TOPIC ausente. Notificação NÃO enviada. Título: %s",
            title,
        )
        return False

    url = f"{NTFY_SERVER.rstrip('/')}/{NTFY_TOPIC}"
    headers = {
        "Title": title.encode("utf-8"),
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = tags

    try:
        req = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if 200 <= resp.status < 300:
                logger.info("[ntfy] enviado (título: %s)", title)
                return True
            logger.error("[ntfy] status inesperado: %s", resp.status)
            return False
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        logger.error("[ntfy] falha ao enviar: %s", exc)
        return False
