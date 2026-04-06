"""add log field to scanresult

Revision ID: b1e3f7a09c22
Revises: a3c8f1d92e45
Create Date: 2026-04-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1e3f7a09c22"
down_revision: Union[str, Sequence[str], None] = "a3c8f1d92e45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scanresult", sa.Column("log", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("scanresult", "log")
