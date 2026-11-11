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

from config import NTFY_COACH_TOPIC, NTFY_SERVER, NTFY_TOPIC

logger = logging.getLogger(__name__)


def is_ntfy_configured() -> bool:
    return bool(NTFY_TOPIC)


def send_ntfy(*, title: str, body: str, priority: str = "default", tags: str = "", topic: str = "") -> bool:
    """Envia notificação push via ntfy. Retorna True se conseguiu.

    priority: min | low | default | high | urgent
    tags: lista separada por vírgula (emojis), ex.: "warning,key"
    """
    topic = topic or NTFY_TOPIC
    if not topic:
        logger.warning(
            "[ntfy] NTFY_TOPIC ausente. Notificação NÃO enviada. Título: %s",
            title,
        )
        return False

    url = f"{NTFY_SERVER.rstrip('/')}/{topic}"
    # ntfy aceita UTF-8 no Title, mas urllib exige string ASCII-safe nos
    # headers; então codifica em RFC 2047 (ou cai pra latin-1 safe).
    try:
        safe_title = title.encode("latin-1").decode("latin-1")
    except UnicodeEncodeError:
        safe_title = title.encode("ascii", "replace").decode("ascii")

    headers = {
        "Title": safe_title,
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
        with urllib.request.urlopen(req, timeout=5) as resp:
            if 200 <= resp.status < 300:
                logger.info("[ntfy] enviado (titulo: %s)", title)
                return True
            logger.error("[ntfy] status inesperado: %s", resp.status)
            return False
    except Exception as exc:  # noqa: BLE001 — jamais quebrar o chamador
        logger.error("[ntfy] falha ao enviar: %r", exc)
        return False


def notify_coach(title: str, body: str, tags: str = "") -> bool:
    """Aviso pro celular da coach (app ntfy). Nunca derruba quem chamou."""
    try:
        return send_ntfy(title=title, body=body, tags=tags, topic=NTFY_COACH_TOPIC)
    except Exception:  # noqa: BLE001
        logger.exception("[ntfy] falha ao avisar a coach")
        return False
