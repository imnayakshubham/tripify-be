"""Shared plumbing: LLM calls, token accounting, and the audit decorator.

Never import from app.agents here — that would be circular.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage

from app.db import audit
from app.llms import get_llm
from app.schema import TravelState

logger = logging.getLogger(__name__)

llm = get_llm()

# Per-invocation token accounting. A ContextVar rather than a global because
# FastAPI runs each sync request in its own worker thread.
_usage: contextvars.ContextVar[dict[str, int]] = contextvars.ContextVar("agent_usage")

AGENT_SEQUENCE = {
    "supervisor": 0,
    "destination_agent": 1,
    "itinerary_agent": 2,
    "budget_agent": 3,
    "synthesis": 4,
}


def ask_llm(system_message: str, user_prompt: str) -> str:
    """One-shot LLM call, recording the provider's real token counts."""
    response = llm.invoke(
        [
            SystemMessage(content=system_message),
            HumanMessage(content=user_prompt),
        ]
    )

    usage = _usage.get(None)
    if usage is not None:
        # Measured counts from the provider, not an estimate.
        metadata = getattr(response, "usage_metadata", None) or {}
        usage["llm_calls"] += 1
        usage["input_tokens"] += metadata.get("input_tokens", 0)
        usage["output_tokens"] += metadata.get("output_tokens", 0)

    return response.content


def parse_json_response(response_text: str) -> dict:
    """Pull the JSON object out of a reply that may wrap it in prose."""
    first_brace = response_text.index("{")
    last_brace = response_text.rindex("}") + 1
    return json.loads(response_text[first_brace:last_brace])


_CURRENCY_ALIASES = {
    "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "sterling": "GBP", "£": "GBP",
    "usd": "USD", "dollar": "USD", "dollars": "USD", "$": "USD",
    "eur": "EUR", "euro": "EUR", "euros": "EUR", "€": "EUR",
    "inr": "INR", "rupee": "INR", "rupees": "INR", "₹": "INR",
    "jpy": "JPY", "yen": "JPY", "¥": "JPY",
    "aud": "AUD", "cad": "CAD", "chf": "CHF",
}


def normalise_currency(value: Any) -> str | None:
    """Map a currency written any which way ("pounds", "GBP", "£") onto an ISO code.

    Returns None for anything unrecognised — callers must read that as unknown,
    never as different.
    """
    text = str(value or "").strip().lower()
    return _CURRENCY_ALIASES.get(text)


def to_number(value: Any) -> float | None:
    """Coerce a model-supplied number: '£1,200', '1200 GBP', 1200.

    Mirrors `toNumber` in trip-planner-fe/src/lib/trip.ts — the two must agree or
    client and server reach different verdicts on identical data.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    cleaned = "".join(character for character in value if character.isdigit() or character in ".-")
    try:
        return float(cleaned)
    except ValueError:
        return None


def audited(agent_name: str) -> Callable:
    """Time an agent, record it in the audit trail, and attribute it.

    One place, so attribution and audit cannot drift. A failing agent is recorded and
    the chain continues rather than the request returning a 500.
    """

    def decorator(agent_fn: Callable[[TravelState], dict]) -> Callable:
        @wraps(agent_fn)
        def wrapper(state: TravelState) -> dict:
            usage = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
            token = _usage.set(usage)

            started_at = datetime.now(timezone.utc)
            started_monotonic = time.monotonic()
            status = "succeeded"
            error_message = None

            try:
                delta = agent_fn(state)
            except Exception as error:
                status = "failed"
                error_message = f"{type(error).__name__}: {error}"
                logger.exception("%s failed", agent_name)
                delta = {}
            finally:
                _usage.reset(token)

            duration_ms = int((time.monotonic() - started_monotonic) * 1000)

            plan_id = state.get("plan_id")
            if plan_id:
                audit.record_agent_invocation(
                    plan_id=uuid.UUID(plan_id),
                    agent_name=agent_name,
                    sequence_index=AGENT_SEQUENCE.get(agent_name, 99),
                    status=status,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    duration_ms=duration_ms,
                    output_summary=_summarise(delta),
                    error_message=error_message,
                    **usage,
                )

            label = agent_name if status == "succeeded" else f"{agent_name} (failed)"
            return {**delta, "contributing_agents": [label]}

        return wrapper

    return decorator


def _summarise(delta: dict[str, Any]) -> str:
    """Longest text the agent produced — enough to audit, not a full copy."""
    texts = [value for value in delta.values() if isinstance(value, str)]
    return max(texts, key=len) if texts else ""
