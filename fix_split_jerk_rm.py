"""Uso único: faz o "Split Jerk" usar o RM próprio (parar de puxar do Clean and Jerk).

Como rodar (no Terminal, dentro de ~/backend-coach-pam):

    DATABASE_URL="<URL_EXTERNA_DO_POSTGRES_DO_RENDER>" python fix_split_jerk_rm.py

A URL externa do Postgres você copia no Render:
  Render -> seu banco Postgres -> aba "Info" -> "External Database URL".
"""
import os
import sys

from sqlmodel import Session, SQLModel, create_engine, select

from models.exercise import Exercise

# Nome exato do movimento que deve ter RM próprio.
ALVO = "Split Jerk"

db_url = os.environ.get("DATABASE_URL") or (sys.argv[1] if len(sys.argv) > 1 else "")
if not db_url:
    print("ERRO: defina DATABASE_URL. Ex.:")
    print('  DATABASE_URL="postgresql://..." python fix_split_jerk_rm.py')
    sys.exit(1)

# Render às vezes entrega "postgres://"; SQLAlchemy quer "postgresql://".
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(db_url)
SQLModel.metadata.create_all(engine)  # garante que as tabelas existem

with Session(engine) as s:
    rows = s.exec(select(Exercise).where(Exercise.name == ALVO)).all()
    if not rows:
        print(f"Nenhum exercício chamado '{ALVO}' encontrado. Nada a fazer.")
        sys.exit(0)

    for ex in rows:
        ex.rm_source_default = None
        # Coluna nova (pode não existir ainda se o backend não foi atualizado).
        if hasattr(ex, "rm_source_exercise_id"):
            try:
                ex.rm_source_exercise_id = None
            except Exception:
                pass
        s.add(ex)
        print(f"OK: '{ex.name}' (id={ex.id}) agora usa RM próprio.")

    s.commit()

print("Pronto. O Split Jerk passa a usar o RM próprio dele.")
