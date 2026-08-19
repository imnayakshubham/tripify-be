"""HTTP endpoints over the orchestration layer.

Every route is a sync `def`, never `async def`. Graph nodes block, so FastAPI runs
these on a worker thread — which is what makes the ContextVar token accounting in
app/agents/base.py correct.
"""

import json
import logging
import time
import uuid
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from app.api.deps import current_user, require_admin
from app.configs import MODEL_NAME
from app.db import audit
from app.db.metrics import collect_metrics
from app.graph import selected_agents_in_order, travel_graph
from app.schema import (
    AgentContribution,
    AuditRequestDetail,
    AuditRequestSummary,
    CreatePlanRequest,
    CurrentUser,
    InvocationLogEntry,
    MetricsResponse,
    PlanResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def thread_config(plan_id: uuid.UUID) -> dict:
    """plan_id doubles as the LangGraph thread id — one identifier, no alias."""
    return {"configurable": {"thread_id": str(plan_id)}}


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def open_plan(request: CreatePlanRequest, user: CurrentUser) -> uuid.UUID:
    """Continue the given plan, or start a new one. Reusing the id resumes its thread."""
    if request.plan_id is not None:
        return request.plan_id

    plan_id = uuid.uuid4()
    audit.start_request(
        plan_id=plan_id,
        user_id=user.id,
        user_query=request.user_query,
        model_name=MODEL_NAME,
    )
    return plan_id


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/plans", response_model=PlanResponse)
def create_plan(
    request: CreatePlanRequest,
    user: CurrentUser = Depends(current_user),
) -> PlanResponse:
    plan_id = open_plan(request, user)

    started = time.monotonic()

    try:
        result = travel_graph.invoke(
            {
                "messages": [HumanMessage(content=request.user_query)],
                "plan_id": str(plan_id),
                "user_id": str(user.id),
                "user_query": request.user_query,
            },
            config=thread_config(plan_id),
        )
    except Exception as error:
        audit.finish_request(
            plan_id=plan_id,
            status="failed",
            error_message=f"{type(error).__name__}: {error}",
            duration_ms=elapsed_ms(started),
        )
        logger.exception("Plan %s failed", plan_id)
        raise HTTPException(status_code=500, detail="The planning run failed.") from error

    audit.finish_request(
        plan_id=plan_id,
        status="completed",
        trip_constraints=result.get("trip_constraints"),
        duration_ms=elapsed_ms(started),
    )

    return _plan_response(plan_id, result, user)


def _plan_response(plan_id: uuid.UUID, result: dict, user: CurrentUser) -> PlanResponse:
    response = PlanResponse(
        plan_id=plan_id,
        status="completed",
        answer=result.get("final_response", ""),
        contributing_agents=result.get("contributing_agents", []),
        supervisor_reasoning=result.get("supervisor_reasoning", ""),
        destination_results=result.get("destination_results", ""),
        itinerary=result.get("itinerary", ""),
        budget_results=result.get("budget_results", ""),
        trip_constraints=result.get("trip_constraints", {}) or {},
        # None rather than {}: "did not run" is distinct from "ran and found nothing".
        destination_choice=result.get("destination_choice") or None,
        itinerary_plan=result.get("itinerary_plan") or None,
        budget_assessment=result.get("budget_assessment") or None,
    )

    # Cost and per-agent timing are admin-only.
    if user.is_admin:
        detail = audit.get_request(plan_id) or {}
        response.llm_calls = detail.get("llm_calls")
        response.input_tokens = detail.get("input_tokens")
        response.output_tokens = detail.get("output_tokens")
        response.agent_details = [
            AgentContribution(
                agent_name=row["agent_name"],
                status=row["status"],
                duration_ms=row["duration_ms"],
                summary=(row["output_summary"] or "")[:200],
            )
            for row in detail.get("invocations", [])
        ]

    return response


# ------------------------------------------------------------- streaming

def _sse(event: str, data: dict) -> str:
    """One Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _agent_status(delta: dict, agent_name: str) -> str:
    """Read the outcome off the "(failed)" suffix @audited wrote, rather than inventing one."""
    labels = delta.get("contributing_agents") or []
    return "failed" if f"{agent_name} (failed)" in labels else "succeeded"


@router.post("/plans/stream")
def create_plan_stream(
    request: CreatePlanRequest,
    user: CurrentUser = Depends(current_user),
) -> StreamingResponse:
    """The same run as POST /plans, emitting each agent as it lands.

    The supervisor's update carries `selected_agents`, so the client knows the real
    chain from the first event. The generator is safe for the ContextVar accounting in
    app/agents/base.py: a node runs start to finish within one `next()`, so set/reset
    never straddle a yield.
    """
    plan_id = open_plan(request, user)

    def event_stream() -> Iterator[str]:
        started = time.monotonic()
        last_step = started
        final_state: dict = {}
        closed = False

        yield _sse("start", {"plan_id": str(plan_id)})

        try:
            for mode, chunk in travel_graph.stream(
                {
                    "messages": [HumanMessage(content=request.user_query)],
                    "plan_id": str(plan_id),
                    "user_id": str(user.id),
                    "user_query": request.user_query,
                },
                config=thread_config(plan_id),
                stream_mode=["updates", "values"],
            ):
                # "values" carries the whole state; the last one builds the payload.
                if mode == "values":
                    final_state = chunk
                    continue

                for agent_name, delta in (chunk or {}).items():
                    now = time.monotonic()
                    duration_ms = int((now - last_step) * 1000)
                    last_step = now

                    if agent_name == "supervisor":
                        yield _sse(
                            "routed",
                            {
                                # The helper the graph routes with, so the client's
                                # pipeline matches what actually runs.
                                "selected_agents": selected_agents_in_order(delta),
                                "supervisor_reasoning": delta.get("supervisor_reasoning", ""),
                            },
                        )

                    yield _sse(
                        "agent",
                        {
                            "agent_name": agent_name,
                            "status": _agent_status(delta, agent_name),
                            "duration_ms": duration_ms,
                        },
                    )

            audit.finish_request(
                plan_id=plan_id,
                status="completed",
                trip_constraints=final_state.get("trip_constraints"),
                duration_ms=elapsed_ms(started),
            )
            closed = True

            # After finish_request, so the admin cost rollup is final.
            yield _sse("done", _plan_response(plan_id, final_state, user).model_dump(mode="json"))

        except Exception as error:
            # Headers are already sent, so failure travels as an event, not a status.
            audit.finish_request(
                plan_id=plan_id,
                status="failed",
                error_message=f"{type(error).__name__}: {error}",
                duration_ms=elapsed_ms(started),
            )
            closed = True
            logger.exception("Plan %s failed", plan_id)
            yield _sse("error", {"detail": "The planning run failed."})

        finally:
            if not closed:
                # GeneratorExit: the client went away. Close the row rather than
                # strand it in 'running'.
                audit.finish_request(
                    plan_id=plan_id,
                    status="failed",
                    error_message="The client disconnected before the run finished.",
                    duration_ms=elapsed_ms(started),
                )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/plans/{plan_id}/result", response_model=PlanResponse)
def get_plan_result(
    plan_id: uuid.UUID,
    user: CurrentUser = Depends(current_user),
) -> PlanResponse:
    """Re-open a finished plan from the LangGraph checkpoint.

    The answer lives in the checkpoint, reachable because `plan_requests.id` *is* the
    thread id. No second copy to drift.
    """
    # Ownership first — the checkpoint tables carry no user_id, so a guessed id
    # would otherwise read someone else's thread.
    if audit.get_request(plan_id, user_id=None if user.is_admin else user.id) is None:
        raise HTTPException(status_code=404, detail=f"No plan '{plan_id}'.")

    try:
        snapshot = travel_graph.get_state(thread_config(plan_id))
    except Exception as error:  # no checkpointer configured, or nothing stored
        logger.warning("No checkpoint for plan %s: %s", plan_id, error)
        raise HTTPException(
            status_code=404, detail="This plan's contents are no longer available."
        ) from error

    values = getattr(snapshot, "values", None) or {}
    if not values.get("final_response"):
        raise HTTPException(
            status_code=404, detail="This plan did not finish, so there is nothing to show."
        )

    return _plan_response(plan_id, values, user)


@router.get("/plans/{plan_id}", response_model=AuditRequestDetail)
def get_plan(
    plan_id: uuid.UUID,
    user: CurrentUser = Depends(current_user),
) -> AuditRequestDetail:
    """Read a stored plan's audit record."""
    detail = audit.get_request(plan_id, user_id=None if user.is_admin else user.id)

    if detail is None:
        raise HTTPException(status_code=404, detail=f"No plan '{plan_id}'.")

    return AuditRequestDetail(**detail, agents=[i["agent_name"] for i in detail["invocations"]])


# ---------------------------------------------------------------- audit

@router.get("/audit/requests", response_model=list[AuditRequestSummary])
def list_audit_requests(
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(current_user),
) -> list[AuditRequestSummary]:
    """Request log. Non-admins are scoped to their own rows in the SQL WHERE."""
    rows = audit.list_requests(
        limit=limit,
        user_id=None if user.is_admin else user.id,
    )
    return [AuditRequestSummary(**row) for row in rows]


@router.get("/audit/invocations", response_model=list[InvocationLogEntry])
def list_audit_invocations(
    limit: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(require_admin),
) -> list[InvocationLogEntry]:
    """Flat agent log across all requests, newest first."""
    return [InvocationLogEntry(**row) for row in audit.list_invocations(limit=limit)]


@router.get("/metrics", response_model=MetricsResponse)
def metrics(
    window_days: int = Query(default=7, ge=1, le=90),
    _: CurrentUser = Depends(require_admin),
) -> MetricsResponse:
    return MetricsResponse(**collect_metrics(window_days=window_days))
