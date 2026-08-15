"""Observability from SQL aggregates over the audit tables.

No new storage: the agent_invocations(agent_name, started_at DESC) index already
supports these queries.
"""

from typing import Any

from app.db.pool import get_pool


def collect_metrics(window_days: int = 7) -> dict[str, Any]:
    with get_pool().connection() as connection:
        requests = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM plan_requests
            WHERE created_at > now() - make_interval(days => %s)
            GROUP BY status
            """,
            (window_days,),
        ).fetchall()

        totals = connection.execute(
            """
            SELECT COUNT(*)                    AS total_requests,
                   COALESCE(SUM(llm_calls), 0)     AS llm_calls,
                   COALESCE(SUM(input_tokens), 0)  AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COUNT(DISTINCT user_id)     AS active_users
            FROM plan_requests
            WHERE created_at > now() - make_interval(days => %s)
            """,
            (window_days,),
        ).fetchone()

        agents = connection.execute(
            """
            SELECT agent_name,
                   COUNT(*)                                            AS invocations,
                   COUNT(*) FILTER (WHERE status = 'succeeded')        AS succeeded,
                   COUNT(*) FILTER (WHERE status = 'failed')           AS failed,
                   ROUND(AVG(duration_ms))::int                        AS avg_duration_ms,
                   PERCENTILE_DISC(0.95) WITHIN GROUP (ORDER BY duration_ms)::int
                                                                       AS p95_duration_ms,
                   COALESCE(SUM(input_tokens), 0)                      AS input_tokens,
                   COALESCE(SUM(output_tokens), 0)                     AS output_tokens
            FROM agent_invocations
            WHERE started_at > now() - make_interval(days => %s)
            GROUP BY agent_name
            ORDER BY invocations DESC
            """,
            (window_days,),
        ).fetchall()

    return {
        "window_days": window_days,
        "total_requests": totals["total_requests"],
        "active_users": totals["active_users"],
        "requests_by_status": {row["status"]: row["count"] for row in requests},
        "llm_calls": totals["llm_calls"],
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "agents": agents,
    }
