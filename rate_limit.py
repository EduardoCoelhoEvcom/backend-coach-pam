"""Rate limiting com slowapi.

Aplicado nos endpoints de auth pra defender contra brute force.

Setup mínimo: instala `pip install slowapi` e o middleware é registrado
no main.py via `app.state.limiter = limiter` + handler de exceção.

Uso em router:
    from rate_limit import limiter

    @router.post("/auth/login")
    @limiter.limit("10/minute")
    async def login(request: Request, ...):
        ...

A primeira request a parar dispara `RateLimitExceeded` (429 Too Many Requests).
Identifica o cliente por IP via `get_remote_address`.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=[])
