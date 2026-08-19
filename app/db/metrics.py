"""Observability from SQL aggregates over the audit tables.

Raw SQL because FILTER and PERCENTILE_DISC ... WITHIN GROUP read worse through the
query builder. agent_invocations(agent_name, started_at DESC) covers these.
"""

from typing import Any

from sqlalchemy import text

from app.db.engine import session_scope

REQUESTS_BY_STATUS = text(
    """
    SELECT status, COUNT(*) AS count
    FROM plan_requests
    WHERE created_at > now() - make_interval(days => :window_days)
    GROUP BY status
    """
)

TOTALS = text(
    """
    SELECT COUNT(*)                        AS total_requests,
           COALESCE(SUM(llm_calls), 0)     AS llm_calls,
           COALESCE(SUM(input_tokens), 0)  AS input_tokens,
           COALESCE(SUM(output_tokens), 0) AS output_tokens,
           COUNT(DISTINCT user_id)         AS active_users
    FROM plan_requests
    WHERE created_at > now() - make_interval(days => :window_days)
    """
)

BY_AGENT = text(
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
    WHERE started_at > now() - make_interval(days => :window_days)
    GROUP BY agent_name
    ORDER BY invocations DESC
    """
)


def collect_metrics(window_days: int = 7) -> dict[str, Any]:
    params = {"window_days": window_days}

    with session_scope() as session:
        requests = session.execute(REQUESTS_BY_STATUS, params).mappings().all()
        totals = session.execute(TOTALS, params).mappings().one()
        agents = session.execute(BY_AGENT, params).mappings().all()

        return {
            "window_days": window_days,
            "total_requests": totals["total_requests"],
            "active_users": totals["active_users"],
            "requests_by_status": {row["status"]: row["count"] for row in requests},
            "llm_calls": totals["llm_calls"],
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
            # Real dicts — pydantic will not validate a RowMapping into list[AgentMetrics].
            "agents": [dict(row) for row in agents],
        }
