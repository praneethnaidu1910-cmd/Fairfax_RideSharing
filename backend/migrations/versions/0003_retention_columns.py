"""add retention columns to ride_requests

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ride_requests", sa.Column("status_changed_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "ride_requests", sa.Column("anonymized_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("ride_requests", "anonymized_at")
    op.drop_column("ride_requests", "status_changed_at")
