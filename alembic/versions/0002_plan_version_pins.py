"""Bookmarked plan versions, and an index for the new activity ordering.

Restored from the deployed schema after the original file was deleted while the
production database was still stamped with this revision — which made every boot fail
with "Can't locate revision identified by '0002_plan_version_pins'". 0003 drops both
objects; this exists so the revision graph stays walkable from either end.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_plan_version_pins"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_version_pins",
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plan_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id", "checkpoint_id"),
    )
    op.create_index(
        "plan_requests_user_activity_idx",
        "plan_requests",
        ["user_id", sa.text("COALESCE(completed_at, created_at) DESC")],
    )


def downgrade() -> None:
    op.drop_index("plan_requests_user_activity_idx", table_name="plan_requests")
    op.drop_table("plan_version_pins")
