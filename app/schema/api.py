"""Request and response models for the HTTP API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ------------------------------------------------------------- identity

class CurrentUser(BaseModel):
    """Resolved caller. See app/api/deps.py — identity is asserted, not proven."""

    id: UUID
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# ---------------------------------------------------------------- plans

class CreatePlanRequest(BaseModel):
    user_query: str = Field(
        ...,
        min_length=1,
        description="The trip request in plain language.",
        examples=["a five day trip somewhere warm in Europe for under 1500 pounds"],
    )


class AgentContribution(BaseModel):
    """What one agent produced, so the answer can show its sources."""

    agent_name: str
    status: str
    duration_ms: int | None = None
    summary: str = ""


class PlanResponse(BaseModel):
    plan_id: UUID
    status: str
    answer: str
    contributing_agents: list[str] = []
    supervisor_reasoning: str = ""
    destination_results: str = ""
    itinerary: str = ""
    budget_results: str = ""
    trip_constraints: dict[str, Any] = {}

    # What the agents actually decided, before it was flattened into markdown.
    # Typed as plain dicts on purpose: this is unvalidated model output, where a
    # cost may arrive as "£1,200" or 1200 and any key may be missing. Strict
    # models here would turn a model quirk into a 500 on an otherwise good run,
    # so the shape is enforced in the TypeScript client instead, where getting
    # it wrong is a compile error rather than a failed request.
    destination_choice: dict[str, Any] | None = None
    itinerary_plan: dict[str, Any] | None = None
    budget_assessment: dict[str, Any] | None = None
    # Admin-only detail; omitted for ordinary users.
    llm_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    agent_details: list[AgentContribution] | None = None


# ---------------------------------------------------------------- audit

class AuditRequestSummary(BaseModel):
    id: UUID
    user_email: str
    user_query: str
    status: str
    agents: list[str] = []
    model_name: str | None = None
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int | None = None
    created_at: datetime


class AuditInvocation(BaseModel):
    agent_name: str
    sequence_index: int
    status: str
    error_message: str | None = None
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int | None = None
    output_summary: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class AuditRequestDetail(AuditRequestSummary):
    trip_constraints: dict[str, Any] | None = None
    error_message: str | None = None
    invocations: list[AuditInvocation] = []


class InvocationLogEntry(BaseModel):
    request_id: UUID
    agent_name: str
    status: str
    user_query: str
    duration_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    error_message: str | None = None
    started_at: datetime


# -------------------------------------------------------------- metrics

class AgentMetrics(BaseModel):
    agent_name: str
    invocations: int
    succeeded: int
    failed: int
    avg_duration_ms: int | None = None
    p95_duration_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class MetricsResponse(BaseModel):
    window_days: int
    total_requests: int
    active_users: int
    requests_by_status: dict[str, int] = {}
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    agents: list[AgentMetrics] = []
