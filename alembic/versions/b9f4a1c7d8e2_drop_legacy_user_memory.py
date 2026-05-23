"""Drop legacy user_memory table

The user_memory table was superseded by user_memory_fact in revision
a3b8f2c4d5e1 (2026-04-15). All runtime read/write paths target
user_memory_fact; past the 30-day soak window declared in that migration.

Revision ID: b9f4a1c7d8e2
Revises: a3b8f2c4d5e1
Create Date: 2026-05-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b9f4a1c7d8e2"
down_revision: Union[str, Sequence[str], None] = "a3b8f2c4d5e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_memory")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_memory (
            id                TEXT PRIMARY KEY,
            user_id           UUID NOT NULL UNIQUE REFERENCES "user"(id) ON DELETE CASCADE,
            work_context      TEXT,
            personal_context  TEXT,
            top_of_mind       TEXT,
            preferences       TEXT,
            created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
