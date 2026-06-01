"""Configuração de logging estruturado em JSON.

Sem dependência externa — usa só stdlib `logging`.

Uso:
    from logging_config import setup_logging
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("evento", extra={"user_id": 42, "endpoint": "/me"})

Output (uma linha JSON por log):
    {"ts": "2026-04-29T12:34:56.789Z", "level": "INFO",
     "logger": "routers.auth", "msg": "evento",
     "user_id": 42, "endpoint": "/me"}

Quando vier o ingestor de logs (Logtail/BetterStack/etc.), os campos já
estão nomeados e indexáveis.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


# Campos do LogRecord que NÃO devem ir pro JSON (são internos).
_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
}


class JSONFormatter(logging.Formatter):
    """Renderiza cada log como uma linha JSON.

    Tudo que vc passar via `logger.info("msg", extra={"k": v})` vira campo
    de primeiro nível no JSON.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Adiciona qualquer extra={...} passado no log call.
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    """Configura o root logger pra emitir JSON em stderr."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn reconfigura logs próprios — vamos garantir que herdam o nosso
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
