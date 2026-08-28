"""create ride_requests table

Revision ID: 0001
Revises:
Create Date: 2026-08-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ride_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rider_id", sa.String(), nullable=False),
        sa.Column("origin_lat", sa.Float(), nullable=False),
        sa.Column("origin_lng", sa.Float(), nullable=False),
        sa.Column("destination_lat", sa.Float(), nullable=False),
        sa.Column("destination_lng", sa.Float(), nullable=False),
        sa.Column("schedule_type", sa.String(), nullable=False),
        sa.Column("schedule", postgresql.JSONB(), nullable=False),
        sa.Column("seats_needed", sa.Integer(), nullable=False),
        sa.Column("contact", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("posted_at", sa.DateTime(), nullable=False),
        sa.Column("matched_with", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_ride_requests_status", "ride_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ride_requests_status", table_name="ride_requests")
    op.drop_table("ride_requests")
