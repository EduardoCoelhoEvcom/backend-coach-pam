"""Coach PAM API — entry point.

Estrutura do projeto (rodadas anteriores extraíram tudo daqui):

  config.py              → variáveis de ambiente (.env)
  db.py                  → engine + get_session + create_db_and_tables
  security.py            → JWT, hash, get_current_user, require_role
  models/                → User, TrainingSheet, Exercise, ExerciseCategory,
                           TrainingDayCompletion, TrainingSetExecution,
                           AthleteExerciseRMHistory
  schemas/               → schemas Pydantic compartilhados (RM e training)
  services/
    training_plan.py     → normalize_plan, compute_end_date, build_default_plan
    seeding.py           → seed inicial do banco
  routers/
    auth.py              → /auth/register, /auth/login, /me
    exercises.py         → /coach/exercise-library, /athlete/exercise-library,
                           /coach/exercise-categories, /coach/exercises (CRUD)
    coach.py             → /coach/athletes, /coach/dashboard,
                           /coach/training-sheets (CRUD + duplicate),
                           /coach/athletes/{id}/exercise-rms (CRUD)
    athlete.py           → /athlete/training-sheets, /athlete/exercise-rms,
                           /athlete/save-day-execution, /athlete/complete-day,
                           /athlete/progress

Este arquivo só monta o FastAPI, registra os middlewares e routers,
e dispara o seed inicial no startup.
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlmodel import Session

from config import CORS_ORIGINS
from db import create_db_and_tables, get_session
from logging_config import setup_logging
from rate_limit import limiter
from routers import (
    athlete as athlete_router,
    auth as auth_router,
    coach as coach_router,
    exercises as exercises_router,
)
from services.seeding import run_initial_seed


# Configura logging JSON antes de qualquer logger ser usado
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan substitui o @app.on_event("startup") (deprecated).

    Tudo antes do `yield` roda no startup. Tudo depois roda no shutdown
    (vazio por enquanto).
    """
    create_db_and_tables()
    run_initial_seed()
    yield
    # shutdown hooks (ex: fechar conexões externas, flush de logs) entram aqui


app = FastAPI(title="Coach PAM API", lifespan=lifespan)

# Rate limiter global — limita por IP nos endpoints decorados com @limiter.limit
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(exercises_router.router)
app.include_router(coach_router.router)
app.include_router(athlete_router.router)


@app.get("/health", tags=["health"])
def health_check(session: Session = Depends(get_session)) -> dict:
    """Health check para uptime monitoring (UptimeRobot etc).

    Retorna 200 se: o app está respondendo E o banco aceita queries.
    """
    db_ok = False
    try:
        session.exec(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "ok": db_ok,
        "service": "coach-pam-api",
        "db": "ok" if db_ok else "error",
    }


