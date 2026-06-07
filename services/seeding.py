"""Seed inicial do banco.

Roda no startup. Idempotente: se já tem categoria global ou se o usuário
já existe, não duplica nada.

  - seed_global_library  → cria categorias + exercícios globais (coach_id=None).
  - seed_default_users   → cria coach@pam.com / atleta@pam.com com senha 123456
                           se ainda não existirem (úteis pra dev/demo).
  - run_initial_seed     → orquestra os dois acima dentro de uma sessão.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from db import engine
from models import Exercise, ExerciseCategory, User, get_user_by_email
from security import get_password_hash


def _get_or_create_category(
    session: Session,
    *,
    coach_id: Optional[int],
    type: str,
    name: str,
    parent_id: Optional[int],
    sort_order: int,
) -> ExerciseCategory:
    stmt = select(ExerciseCategory).where(
        ExerciseCategory.coach_id == coach_id,
        ExerciseCategory.type == type,
        ExerciseCategory.name == name,
        ExerciseCategory.parent_id == parent_id,
    )
    existing = session.exec(stmt).first()
    if existing:
        return existing

    cat = ExerciseCategory(
        coach_id=coach_id,
        type=type,
        name=name,
        parent_id=parent_id,
        sort_order=sort_order,
        is_active=True,
    )
    session.add(cat)
    session.commit()
    session.refresh(cat)
    return cat


def _add_exercises(
    session: Session,
    coach_id: Optional[int],
    category_id: int,
    names: list[str],
    ex_type: str,  # "lpo" | "accessory"
    rm_source_default: Optional[str] = None,
    allow_weight_default: bool = True,
):
    now = datetime.now(timezone.utc)

    for name in names:
        nm = (name or "").strip()
        if not nm:
            continue

        stmt = select(Exercise).where(
            Exercise.coach_id == coach_id,
            Exercise.category_id == category_id,
            Exercise.name == nm,
        )
        if session.exec(stmt).first():
            continue

        ex = Exercise(
            coach_id=coach_id,
            category_id=category_id,
            name=nm,
            type=ex_type,
            rm_source_default=rm_source_default,
            allow_weight_default=allow_weight_default,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(ex)

    session.commit()


def seed_global_library(session: Session) -> None:
    """Popula a biblioteca global de exercícios (coach_id=None).

    Não roda se já existir alguma categoria global.
    """
    existing = session.exec(
        select(ExerciseCategory).where(ExerciseCategory.coach_id == None)
    ).first()
    if existing:
        return

    # ----- Categorias raiz -----
    force_cat = _get_or_create_category(
        session, coach_id=None, type="lpo", name="Força",
        parent_id=None, sort_order=10,
    )
    tech_cat = _get_or_create_category(
        session, coach_id=None, type="lpo", name="Técnicos",
        parent_id=None, sort_order=20,
    )
    lpo_acc_cat = _get_or_create_category(
        session, coach_id=None, type="lpo", name="Acessórios de LPO",
        parent_id=None, sort_order=30,
    )
    extra_cat = _get_or_create_category(
        session, coach_id=None, type="accessory", name="Acessórios Extras",
        parent_id=None, sort_order=40,
    )

    # ----- Subcategorias (Força) -----
    squats_cat = _get_or_create_category(session, coach_id=None, type="lpo", name="Agachamentos",       parent_id=force_cat.id, sort_order=1)
    pulls_cat  = _get_or_create_category(session, coach_id=None, type="lpo", name="Puxadas (Pulls)",    parent_id=force_cat.id, sort_order=2)
    hpulls_cat = _get_or_create_category(session, coach_id=None, type="lpo", name="Puxadas (High Pulls)", parent_id=force_cat.id, sort_order=3)
    pushes_cat = _get_or_create_category(session, coach_id=None, type="lpo", name="Empurradas",         parent_id=force_cat.id, sort_order=4)
    starts_cat = _get_or_create_category(session, coach_id=None, type="lpo", name="Saídas",             parent_id=force_cat.id, sort_order=5)

    # ----- Subcategorias (Técnicos) -----
    snatch_cat = _get_or_create_category(session, coach_id=None, type="lpo", name="Snatch",        parent_id=tech_cat.id, sort_order=1)
    clean_cat  = _get_or_create_category(session, coach_id=None, type="lpo", name="Clean",         parent_id=tech_cat.id, sort_order=2)
    cj_cat     = _get_or_create_category(session, coach_id=None, type="lpo", name="Clean & Jerk",  parent_id=tech_cat.id, sort_order=3)
    jerk_cat   = _get_or_create_category(session, coach_id=None, type="lpo", name="Jerk",          parent_id=tech_cat.id, sort_order=4)

    # ----- Subcategorias (Acessórios extras) -----
    extra_cat1 = _get_or_create_category(session, coach_id=None, type="accessory", name="Categoria 1", parent_id=extra_cat.id, sort_order=1)
    extra_cat2 = _get_or_create_category(session, coach_id=None, type="accessory", name="Categoria 2", parent_id=extra_cat.id, sort_order=2)

    # ----- Exercícios (Força) -----
    _add_exercises(session, coach_id=None, category_id=squats_cat.id, ex_type="lpo", names=[
        "Back Squat", "Front Squat", "Overhead Squat (OHS)",
        "1/2 Back Squat", "1/4 Back Squat",
    ])
    _add_exercises(session, coach_id=None, category_id=pulls_cat.id, ex_type="lpo", names=[
        "Clean Pull", "Hang Clean Pull", "Low Hang Clean Pull", "High Hang Clean Pull",
        "Snatch Pull", "Hang Snatch Pull", "Low Hang Snatch Pull", "High Hang Snatch Pull",
    ])
    _add_exercises(session, coach_id=None, category_id=hpulls_cat.id, ex_type="lpo", names=[
        "Clean High Pull", "Hang Clean High Pull", "Low Hang Clean High Pull", "High Hang Clean High Pull",
        "Snatch High Pull", "Hang Snatch High Pull", "Low Hang Snatch High Pull", "High Hang Snatch High Pull",
    ])
    _add_exercises(session, coach_id=None, category_id=pushes_cat.id, ex_type="lpo", names=[
        "Push Press", "Strict Press", "Press Behind the Neck", "Push Press Behind the Neck",
    ])
    _add_exercises(session, coach_id=None, category_id=starts_cat.id, ex_type="lpo", names=[
        "Deadlift", "Clean Deadlift", "Snatch Deadlift",
        "Tempo Clean Deadlift", "Tempo Snatch Deadlift",
        "Snatch Lift Off", "Clean Lift Off",
    ])

    # ----- Exercícios (Técnicos) -----
    _add_exercises(session, coach_id=None, category_id=snatch_cat.id, ex_type="lpo", rm_source_default="snatch",      names=["Snatch"])
    _add_exercises(session, coach_id=None, category_id=clean_cat.id,  ex_type="lpo", rm_source_default="clean_jerk",  names=["Clean"])
    _add_exercises(session, coach_id=None, category_id=cj_cat.id,     ex_type="lpo", rm_source_default="clean_jerk",  names=["Clean and Jerk"])
    # Split Jerk tem RM próprio (não puxa do Clean and Jerk).
    _add_exercises(session, coach_id=None, category_id=jerk_cat.id,   ex_type="lpo", rm_source_default=None,          names=[
        "Split Jerk",
    ])
    _add_exercises(session, coach_id=None, category_id=jerk_cat.id,   ex_type="lpo", rm_source_default="clean_jerk",  names=[
        "Push Jerk", "Push Jerk (Back Rack)", "Split Jerk (Back Rack)",
    ])

    # ----- Exercícios (Acessórios de LPO) -----
    _add_exercises(session, coach_id=None, category_id=lpo_acc_cat.id, ex_type="lpo", names=[
        "Tall Clean", "Tall Snatch", "Jerk Balance", "Sots Press (Press in Squat)",
        "Snatch Balance", "Power Snatch Balance", "Drop Snatch", "Snatch Push Press",
        "Press in Split Position", "Snatch Stiff", "Barbell Good Morning",
        "OHS with Bands", "Front Press in Squat", "Jerk Dip Hold",
    ])

    # ----- Exercícios (Acessórios extras) -----
    _add_exercises(
        session, coach_id=None, category_id=extra_cat1.id,
        ex_type="accessory", rm_source_default=None, allow_weight_default=True,
        names=["Elevação de quadril", "Deslocamento Lateral"],
    )
    _add_exercises(
        session, coach_id=None, category_id=extra_cat2.id,
        ex_type="accessory", rm_source_default=None, allow_weight_default=True,
        names=["Tríceps Francês"],
    )


def seed_default_users(session: Session) -> None:
    """Cria coach@pam.com e atleta@pam.com (senha 123456) se ainda não existirem.

    Útil pra dev/demo. Em produção, vc cria contas reais via /auth/register
    ou via /coach/athletes (POST).
    """
    if not get_user_by_email("coach@pam.com", session):
        session.add(User(
            name="Pam",
            email="coach@pam.com",
            password_hash=get_password_hash("123456"),
            role="coach",
            status_pagamento="ok",
            vencimento=date.today() + timedelta(days=30),
        ))

    if not get_user_by_email("atleta@pam.com", session):
        session.add(User(
            name="Aluno",
            email="atleta@pam.com",
            password_hash=get_password_hash("123456"),
            role="athlete",
            status_pagamento="ok",
            vencimento=date.today() + timedelta(days=30),
        ))

    session.commit()


def run_initial_seed() -> None:
    """Executa o seed completo numa sessão própria. Chamado no startup."""
    with Session(engine) as session:
        seed_global_library(session)
        seed_default_users(session)
