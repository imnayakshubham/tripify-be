"""Itinerary agent.

Realistic timing and stated uncertainty live in the prompt alone — no code can verify
them. `_format` is load-bearing: synthesis reads only the markdown.
"""

import logging

from langchain_core.messages import AIMessage
from langchain_core.utils.json import parse_partial_json

from app.agents.base import ask_llm, audited, parse_json_response
from app.prompts.itinerary import SYSTEM, itinerary_prompt
from app.schema import TravelState

logger = logging.getLogger(__name__)


@audited("itinerary_agent")
def itinerary_agent(state: TravelState):
    response = ask_llm(
        SYSTEM,
        itinerary_prompt(
            user_query=state["user_query"],
            trip_constraints=state.get("trip_constraints", {}) or {},
            # "May consult the Destination Agent for context" — this is that link.
            destination_results=state.get("destination_results", ""),
        ),
    )

    truncated = False
    try:
        plan = parse_json_response(response)
    except (ValueError, KeyError, TypeError):
        plan = _salvage(response)
        truncated = plan is not None

    if plan is None:
        if "{" in response:
            # Broken JSON, not prose. Passing it on as markdown is what put a wall of raw
            # JSON in front of the user; fail instead, so @audited records it and
            # synthesis tells them the itinerary is missing.
            raise ValueError("Itinerary JSON was unparseable and unsalvageable.")

        # No brace at all means the model answered in prose. That still reads as
        # markdown, so keep it — this is the case the fallback was written for.
        logger.warning("Itinerary came back as prose, not JSON; keeping the raw text.")
        return {
            "itinerary": response,
            "itinerary_plan": {},
            "messages": [AIMessage(content="Itinerary agent produced a day-by-day plan.")],
        }

    if truncated:
        _drop_incomplete(plan)

    if not plan.get("days"):
        # Without this the agent reports success while `itinerary` is empty, because
        # _format returns "" for a plan it cannot recognise.
        raise ValueError("Itinerary JSON parsed but carried no days.")

    itinerary = _format(plan)

    if truncated:
        # Synthesis and the budget agent read only this markdown, so the warning has to
        # live in it — a flag they never look at would let both present a short plan as
        # if it were complete.
        plan["truncated"] = True
        itinerary += (
            "\n\n> The model's reply was cut off, so this plan stops after day "
            f"{len(plan['days'])}. Ask for the remaining days to continue."
        )
        logger.warning("Itinerary was truncated; salvaged %d day(s).", len(plan["days"]))

    return {
        "itinerary": itinerary,
        "itinerary_plan": plan,
        "messages": [AIMessage(content="Itinerary agent produced a day-by-day plan.")],
    }


def _salvage(response_text: str) -> dict | None:
    """Recover what did arrive when the reply was cut off mid-JSON.

    `parse_partial_json` closes the containers the model never got to close — it is what
    LangChain uses to read half-streamed tool-call arguments. It parses from the first
    brace, not from prose or a code fence, and it will happily return a list or an empty
    dict; neither is a plan, so both come back as None.
    """
    first_brace = response_text.find("{")
    if first_brace == -1:
        return None

    try:
        plan = parse_partial_json(response_text[first_brace:])
    except ValueError:
        return None

    return plan if isinstance(plan, dict) and plan else None


def _drop_incomplete(plan: dict) -> None:
    """Strip the half-written tail truncation leaves behind.

    A cut-off reply ends in a segment with no activity, or a day with no segments. Both
    render as blank rows, which is worse than not showing them at all.
    """
    days = []
    for day in plan.get("days") or []:
        day["segments"] = [
            segment for segment in day.get("segments") or [] if segment.get("activity")
        ]
        if day["segments"]:
            days.append(day)
    plan["days"] = days


def _format(plan: dict) -> str:
    lines = []

    if plan.get("summary"):
        lines.append(plan["summary"])
        lines.append("")

    for day in plan.get("days") or []:
        heading = f"### Day {day.get('day', '?')}"
        if day.get("title"):
            heading += f" — {day['title']}"
        lines.append(heading)

        for segment in day.get("segments") or []:
            part = str(segment.get("part_of_day", "")).capitalize()
            activity = segment.get("activity", "")
            duration = segment.get("duration", "")

            entry = f"- **{part}:** {activity}" if part else f"- {activity}"
            if duration:
                entry += f" *({duration})*"
            lines.append(entry)

            if segment.get("uncertainty"):
                lines.append(f"  - Uncertain: {segment['uncertainty']}")

        lines.append("")

    uncertainties = plan.get("uncertainties") or []
    if uncertainties:
        lines.append("### Uncertainties and assumptions")
        lines.extend(f"- {item}" for item in uncertainties)

    return "\n".join(lines).strip()
