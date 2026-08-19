"""Audit trail: who asked what, and which agents handled it.

The logging writes swallow their own errors — a failure to log must never break a
user's request. `upsert_user` and the reads do not: failing quietly there would serve
a request as an unknown user, or show an empty log as though nothing had happened.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Text, cast, func, literal, select, update
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by, insert

from app.db.engine import session_scope
from app.db.models import AgentInvocation, PlanRequest, User

logger = logging.getLogger(__name__)

# Agent output is truncated before storage; the checkpoint tables hold the full text
# under the same id.
OUTPUT_SUMMARY_LIMIT = 2000


# ---------------------------------------------------------------- users

def upsert_user(email: str, role: str | None = None) -> dict[str, Any]:
    """Find or create the user for this email, returning the row.

    Part of the auth stub — `X-User-Role` is written straight onto the row, so a
    caller can promote itself. One statement, not SELECT-then-INSERT: that raced two
    concurrent first requests for the same email into users_email_lower_idx.
    """
    values = {"email": email, "display_name": email.split("@")[0], "role": role or "user"}

    updates: dict[str, Any] = {"last_login_at": func.now()}
    if role:
        updates["role"] = role

    statement = (
        insert(User)
        .values(**values)
        .on_conflict_do_update(index_elements=[func.lower(User.email)], set_=updates)
        .returning(*User.__table__.c)
    )

    with session_scope() as session:
        return dict(session.execute(statement).mappings().one())


# -------------------------------------------------------- plan requests

def start_request(
    plan_id: uuid.UUID,
    user_id: uuid.UUID,
    user_query: str,
    model_name: str,
    source: str = "web",
) -> None:
    try:
        with session_scope() as session:
            session.execute(
                insert(PlanRequest).values(
                    id=plan_id,
                    user_id=user_id,
                    user_query=user_query,
                    status="running",
                    model_name=model_name,
                    source=source,
                )
            )
    except Exception:
        logger.exception("Failed to record start of plan %s", plan_id)


def finish_request(
    plan_id: uuid.UUID,
    status: str,
    trip_constraints: dict | None = None,
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Close the request and roll up cost from its agent invocations."""

    def rollup(column):
        return (
            select(func.coalesce(func.sum(column), 0))
            .where(AgentInvocation.request_id == plan_id)
            .scalar_subquery()
        )

    try:
        with session_scope() as session:
            session.execute(
                update(PlanRequest)
                .where(PlanRequest.id == plan_id)
                .values(
                    status=status,
                    trip_constraints=trip_constraints,
                    error_message=error_message,
                    duration_ms=duration_ms,
                    completed_at=func.now(),
                    llm_calls=rollup(AgentInvocation.llm_calls),
                    input_tokens=rollup(AgentInvocation.input_tokens),
                    output_tokens=rollup(AgentInvocation.output_tokens),
                )
            )
    except Exception:
        logger.exception("Failed to record completion of plan %s", plan_id)


# ---------------------------------------------------- agent invocations

def record_agent_invocation(
    plan_id: uuid.UUID,
    agent_name: str,
    sequence_index: int,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    duration_ms: int,
    llm_calls: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    output_summary: str | None = None,
    error_message: str | None = None,
) -> None:
    try:
        with session_scope() as session:
            session.execute(
                insert(AgentInvocation).values(
                    request_id=plan_id,
                    agent_name=agent_name,
                    sequence_index=sequence_index,
                    status=status,
                    error_message=error_message,
                    llm_calls=llm_calls,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    duration_ms=duration_ms,
                    output_summary=(output_summary or "")[:OUTPUT_SUMMARY_LIMIT] or None,
                    started_at=started_at,
                    finished_at=finished_at,
                )
            )
    except Exception:
        logger.exception("Failed to record %s for plan %s", agent_name, plan_id)


# ------------------------------------------------------------- querying

def list_requests(
    limit: int = 50,
    user_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Recent requests with the agents that handled each.

    Scoping is a WHERE clause, not a post-filter, so a non-admin never loads another
    user's rows.
    """
    agents = func.coalesce(
        func.array_agg(
            aggregate_order_by(AgentInvocation.agent_name, AgentInvocation.sequence_index)
        ).filter(AgentInvocation.agent_name.is_not(None)),
        cast(literal("{}"), ARRAY(Text)),
    ).label("agents")

    statement = (
        select(
            PlanRequest.id,
            PlanRequest.user_query,
            PlanRequest.status,
            PlanRequest.model_name,
            PlanRequest.llm_calls,
            PlanRequest.input_tokens,
            PlanRequest.output_tokens,
            PlanRequest.duration_ms,
            PlanRequest.created_at,
            User.email.label("user_email"),
            agents,
        )
        .select_from(PlanRequest)
        .join(User, User.id == PlanRequest.user_id)
        .outerjoin(AgentInvocation, AgentInvocation.request_id == PlanRequest.id)
        .group_by(PlanRequest.id, User.email)
        .order_by(PlanRequest.created_at.desc())
        .limit(limit)
    )

    if user_id is not None:
        statement = statement.where(PlanRequest.user_id == user_id)

    with session_scope() as session:
        return [dict(row) for row in session.execute(statement).mappings()]


def get_request(
    plan_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    request_statement = (
        select(*PlanRequest.__table__.c, User.email.label("user_email"))
        .join_from(PlanRequest, User, User.id == PlanRequest.user_id)
        .where(PlanRequest.id == plan_id)
    )

    if user_id is not None:
        request_statement = request_statement.where(PlanRequest.user_id == user_id)

    invocations_statement = (
        select(
            AgentInvocation.agent_name,
            AgentInvocation.sequence_index,
            AgentInvocation.status,
            AgentInvocation.error_message,
            AgentInvocation.llm_calls,
            AgentInvocation.input_tokens,
            AgentInvocation.output_tokens,
            AgentInvocation.duration_ms,
            AgentInvocation.output_summary,
            AgentInvocation.started_at,
            AgentInvocation.finished_at,
        )
        .where(AgentInvocation.request_id == plan_id)
        .order_by(AgentInvocation.sequence_index)
    )

    with session_scope() as session:
        row = session.execute(request_statement).mappings().one_or_none()
        if row is None:
            return None

        request = dict(row)
        request["invocations"] = [
            dict(invocation) for invocation in session.execute(invocations_statement).mappings()
        ]
        return request


def list_invocations(limit: int = 100) -> list[dict[str, Any]]:
    """Flat log view across all requests, newest first."""
    statement = (
        select(
            AgentInvocation.agent_name,
            AgentInvocation.status,
            AgentInvocation.duration_ms,
            AgentInvocation.input_tokens,
            AgentInvocation.output_tokens,
            AgentInvocation.error_message,
            AgentInvocation.started_at,
            AgentInvocation.request_id,
            PlanRequest.user_query,
        )
        .join_from(AgentInvocation, PlanRequest, PlanRequest.id == AgentInvocation.request_id)
        .order_by(AgentInvocation.started_at.desc())
        .limit(limit)
    )

    with session_scope() as session:
        return [dict(row) for row in session.execute(statement).mappings()]
