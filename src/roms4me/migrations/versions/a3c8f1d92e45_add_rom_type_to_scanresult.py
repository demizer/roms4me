"""add rom_type field to scanresult

Revision ID: a3c8f1d92e45
Revises: f4ec9632e55b
Create Date: 2026-04-06 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c8f1d92e45"
down_revision: Union[str, Sequence[str], None] = "f4ec9632e55b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("scanresult", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("rom_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="")
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("scanresult", schema=None) as batch_op:
        batch_op.drop_column("rom_type")
