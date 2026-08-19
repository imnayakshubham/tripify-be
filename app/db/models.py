"""Audit schema. LangGraph owns the checkpoint tables and they are not modelled here —
the join is by shared id (plan_requests.id IS the thread id), deliberately without a FK.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Role(Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')", name="users_status_check"
        ),
        # Login uniqueness without CITEXT. id stays a surrogate because email changes.
        Index("users_email_lower_idx", text("lower(email)"), unique=True),
        Index("users_role_status_idx", "role", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str | None] = mapped_column(Text, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(
        Text, ForeignKey("roles.name"), nullable=False, server_default=text("'user'")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locale: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str | None] = mapped_column(Text)
    # "metadata" is reserved on DeclarativeBase, so the column keeps its name and the
    # attribute does not.
    user_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Soft delete: audit rows must outlive the user they reference.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlanRequest(Base):
    __tablename__ = "plan_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="plan_requests_status_check"
        ),
        Index("plan_requests_user_created_idx", "user_id", text("created_at DESC")),
    )

    # Also the LangGraph thread id, so no default — the API supplies it.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    trip_constraints: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_name: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'web'"))
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentInvocation(Base):
    __tablename__ = "agent_invocations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed')", name="agent_invocations_status_check"
        ),
        Index("agent_invocations_request_seq_idx", "request_id", "sequence_index"),
        Index("agent_invocations_agent_started_idx", "agent_name", text("started_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plan_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    # Truncated: the full state lives in the checkpoint under the same id.
    output_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
