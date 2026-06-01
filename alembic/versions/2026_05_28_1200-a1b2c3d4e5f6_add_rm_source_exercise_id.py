"""add rm_source_exercise_id to exercise

Revision ID: a1b2c3d4e5f6
Revises: 7676a01cdee9
Create Date: 2026-05-28 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "7676a01cdee9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "exercise",
        sa.Column("rm_source_exercise_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_exercise_rm_source_exercise_id",
        "exercise",
        ["rm_source_exercise_id"],
    )
    op.create_foreign_key(
        "fk_exercise_rm_source_exercise_id",
        "exercise",
        "exercise",
        ["rm_source_exercise_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_exercise_rm_source_exercise_id", "exercise", type_="foreignkey"
    )
    op.drop_index("ix_exercise_rm_source_exercise_id", table_name="exercise")
    op.drop_column("exercise", "rm_source_exercise_id")
