"""Envio de e-mail via SMTP (stdlib, sem dependência externa).

Usado para alertas administrativos — hoje, o aviso de "esqueci a senha".

Se as variáveis de SMTP não estiverem configuradas, send_email apenas
registra um aviso no log e retorna False (não derruba a aplicação).
"""
import logging
import smtplib
from email.message import EmailMessage

from config import (
    ALERT_EMAIL_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
)

logger = logging.getLogger(__name__)


def is_email_configured() -> bool:
    return bool(SMTP_USER and SMTP_PASSWORD and ALERT_EMAIL_FROM)


def send_email(*, to: str, subject: str, body: str) -> bool:
    """Envia um e-mail de texto simples. Retorna True se conseguiu."""
    if not is_email_configured():
        logger.warning(
            "[email] SMTP não configurado (SMTP_USER/SMTP_PASSWORD ausentes). "
            "E-mail NÃO enviado. Assunto: %s",
            subject,
        )
        return False

    msg = EmailMessage()
    msg["From"] = ALERT_EMAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("[email] enviado para %s (assunto: %s)", to, subject)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("[email] falha ao enviar para %s: %s", to, exc)
        return False
