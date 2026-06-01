"""Uso único: cria (ou atualiza) a conta da COACH no banco.

Como rodar (no Terminal, dentro de ~/backend-coach-pam):

    DATABASE_URL="<URL_EXTERNA_DO_POSTGRES_DO_RENDER>" python create_coach.py

A URL externa do Postgres você copia no Render:
  Render -> seu banco Postgres -> aba "Info" -> "External Database URL".

Pode trocar NOME/EMAIL/SENHA abaixo antes de rodar, se quiser.
"""
import os
import sys
from datetime import date, timedelta

from passlib.context import CryptContext
from sqlmodel import Session, SQLModel, create_engine, select

from models.user import User

# ----- dados da conta da coach (troque se quiser) -----
NOME = "Coach PAM"
EMAIL = "coach@pam.com"
SENHA = "123456"
# ------------------------------------------------------

db_url = os.environ.get("DATABASE_URL") or (sys.argv[1] if len(sys.argv) > 1 else "")
if not db_url:
    print("ERRO: defina DATABASE_URL. Ex.:")
    print('  DATABASE_URL="postgresql://..." python create_coach.py')
    sys.exit(1)

# Render às vezes entrega "postgres://"; SQLAlchemy quer "postgresql://".
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
engine = create_engine(db_url)
SQLModel.metadata.create_all(engine)  # garante que as tabelas existem

email = EMAIL.strip().lower()
with Session(engine) as s:
    existente = s.exec(select(User).where(User.email == email)).first()
    if existente:
        existente.role = "coach"
        existente.password_hash = pwd.hash(SENHA)
        s.add(existente)
        s.commit()
        print(f"OK: conta '{email}' atualizada para COACH (senha redefinida).")
    else:
        u = User(
            name=NOME,
            email=email,
            password_hash=pwd.hash(SENHA),
            role="coach",
            status_pagamento="ok",
            vencimento=date.today() + timedelta(days=3650),
        )
        s.add(u)
        s.commit()
        print(f"OK: COACH '{email}' criada com sucesso.")

print("Pronto. Agora faça login no app com esse email e senha.")
