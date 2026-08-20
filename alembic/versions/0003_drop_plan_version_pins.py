"""Drop the plan version pins and the activity index.

The feature they backed was removed; nothing in app/ reads either object, and the plan
listing orders by created_at DESC, which plan_requests_user_created_idx already serves.
Left in place they are invisible to include_object, so every autogenerate run proposes
these same drops.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_drop_plan_version_pins"
down_revision = "0002_plan_version_pins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("plan_requests_user_activity_idx", table_name="plan_requests")
    op.drop_table("plan_version_pins")


def downgrade() -> None:
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
