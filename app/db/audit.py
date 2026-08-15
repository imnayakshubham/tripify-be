"""Audit trail: who asked what, and which agents handled it.

Every write here is best-effort. A failure to log must never break a user's
request, so the public functions swallow and report their own errors.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.db.pool import get_pool

logger = logging.getLogger(__name__)

# Agent output is truncated before storage; the checkpoint tables hold the
# full text under the same id.
OUTPUT_SUMMARY_LIMIT = 2000


# ---------------------------------------------------------------- users

def upsert_user(email: str, role: str | None = None) -> dict[str, Any]:
    """Find or create the user for this email, returning the row.

    Part of the auth *stub* — see app/api/deps.py. Identity is asserted by a
    header, not proven.
    """
    with get_pool().connection() as connection:
        existing = connection.execute(
            "SELECT * FROM users WHERE lower(email) = lower(%s)",
            (email,),
        ).fetchone()

        if existing is None:
            return connection.execute(
                """
                INSERT INTO users (email, display_name, role)
                VALUES (%s, %s, COALESCE(%s, 'user'))
                RETURNING *
                """,
                (email, email.split("@")[0], role),
            ).fetchone()

        # A role passed on the request seeds the stub, but never demotes an
        # existing admin silently.
        if role and role != existing["role"]:
            return connection.execute(
                "UPDATE users SET role = %s WHERE id = %s RETURNING *",
                (role, existing["id"]),
            ).fetchone()

        connection.execute(
            "UPDATE users SET last_login_at = now() WHERE id = %s",
            (existing["id"],),
        )
        return existing


# -------------------------------------------------------- plan requests

def start_request(
    plan_id: uuid.UUID,
    user_id: uuid.UUID,
    user_query: str,
    model_name: str,
    source: str = "web",
) -> None:
    try:
        with get_pool().connection() as connection:
            connection.execute(
                """
                INSERT INTO plan_requests (id, user_id, user_query, status, model_name, source)
                VALUES (%s, %s, %s, 'running', %s, %s)
                """,
                (plan_id, user_id, user_query, model_name, source),
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
    try:
        with get_pool().connection() as connection:
            connection.execute(
                """
                UPDATE plan_requests AS request
                SET status           = %s,
                    trip_constraints = %s,
                    error_message    = %s,
                    duration_ms      = %s,
                    completed_at     = now(),
                    llm_calls     = COALESCE(rollup.llm_calls, 0),
                    input_tokens  = COALESCE(rollup.input_tokens, 0),
                    output_tokens = COALESCE(rollup.output_tokens, 0)
                FROM (
                    SELECT SUM(llm_calls)     AS llm_calls,
                           SUM(input_tokens)  AS input_tokens,
                           SUM(output_tokens) AS output_tokens
                    FROM agent_invocations
                    WHERE request_id = %s
                ) AS rollup
                WHERE request.id = %s
                """,
                (
                    status,
                    json.dumps(trip_constraints) if trip_constraints is not None else None,
                    error_message,
                    duration_ms,
                    plan_id,
                    plan_id,
                ),
            )
    except Exception:
        logger.exception("Failed to record completion of plan %s", plan_id)


# ---------------------------------------------------- agent invocations

def record_agent_invocation(
    plan_id: uuid.UUID,
    agent_name: str,
    sequence_index: int,
    status: str,
    started_at,
    finished_at,
    duration_ms: int,
    llm_calls: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    output_summary: str | None = None,
    error_message: str | None = None,
) -> None:
    try:
        with get_pool().connection() as connection:
            connection.execute(
                """
                INSERT INTO agent_invocations (
                    request_id, agent_name, sequence_index, status, error_message,
                    llm_calls, input_tokens, output_tokens, duration_ms,
                    output_summary, started_at, finished_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    plan_id,
                    agent_name,
                    sequence_index,
                    status,
                    error_message,
                    llm_calls,
                    input_tokens,
                    output_tokens,
                    duration_ms,
                    (output_summary or "")[:OUTPUT_SUMMARY_LIMIT] or None,
                    started_at,
                    finished_at,
                ),
            )
    except Exception:
        logger.exception("Failed to record %s for plan %s", agent_name, plan_id)


# ------------------------------------------------------------- querying

def list_requests(
    limit: int = 50,
    user_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Recent requests with the agents that handled each.

    user_id scoping is applied in the WHERE clause, not filtered afterwards, so
    a non-admin's query never loads another user's rows.
    """
    with get_pool().connection() as connection:
        return connection.execute(
            """
            SELECT request.id,
                   request.user_query,
                   request.status,
                   request.model_name,
                   request.llm_calls,
                   request.input_tokens,
                   request.output_tokens,
                   request.duration_ms,
                   request.created_at,
                   account.email AS user_email,
                   COALESCE(
                       ARRAY_AGG(invocation.agent_name ORDER BY invocation.sequence_index)
                           FILTER (WHERE invocation.agent_name IS NOT NULL),
                       '{}'
                   ) AS agents
            FROM plan_requests AS request
            JOIN users AS account ON account.id = request.user_id
            LEFT JOIN agent_invocations AS invocation ON invocation.request_id = request.id
            WHERE (%s::uuid IS NULL OR request.user_id = %s::uuid)
            GROUP BY request.id, account.email
            ORDER BY request.created_at DESC
            LIMIT %s
            """,
            (user_id, user_id, limit),
        ).fetchall()


def get_request(
    plan_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    with get_pool().connection() as connection:
        request = connection.execute(
            """
            SELECT request.*, account.email AS user_email
            FROM plan_requests AS request
            JOIN users AS account ON account.id = request.user_id
            WHERE request.id = %s
              AND (%s::uuid IS NULL OR request.user_id = %s::uuid)
            """,
            (plan_id, user_id, user_id),
        ).fetchone()

        if request is None:
            return None

        request["invocations"] = connection.execute(
            """
            SELECT agent_name, sequence_index, status, error_message,
                   llm_calls, input_tokens, output_tokens, duration_ms,
                   output_summary, started_at, finished_at
            FROM agent_invocations
            WHERE request_id = %s
            ORDER BY sequence_index
            """,
            (plan_id,),
        ).fetchall()

        return request


def list_invocations(limit: int = 100) -> list[dict[str, Any]]:
    """Flat log view across all requests, newest first."""
    with get_pool().connection() as connection:
        return connection.execute(
            """
            SELECT invocation.agent_name,
                   invocation.status,
                   invocation.duration_ms,
                   invocation.input_tokens,
                   invocation.output_tokens,
                   invocation.error_message,
                   invocation.started_at,
                   invocation.request_id,
                   request.user_query
            FROM agent_invocations AS invocation
            JOIN plan_requests AS request ON request.id = invocation.request_id
            ORDER BY invocation.started_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
