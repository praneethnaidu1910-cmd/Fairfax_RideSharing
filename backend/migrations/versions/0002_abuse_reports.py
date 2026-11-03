"""create abuse_reports table

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "abuse_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reported_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reporter_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_abuse_reports_reported_request_id", "abuse_reports", ["reported_request_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_abuse_reports_reported_request_id", table_name="abuse_reports")
    op.drop_table("abuse_reports")
