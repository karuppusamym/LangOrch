"""Add system_settings table for hot-patched config persistence.

Revision ID: v013_system_settings
Revises: v012_procedure_builder_drafts
Create Date: 2026-04-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v013_system_settings"
down_revision: Union[str, None] = "v012_procedure_builder_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("system_settings"):
        return

    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(128), primary_key=True, nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("system_settings"):
        op.drop_table("system_settings")
