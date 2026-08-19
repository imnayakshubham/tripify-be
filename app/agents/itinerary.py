"""Itinerary agent.

Realistic timing and stated uncertainty live in the prompt alone — no code can verify
them. `_format` is load-bearing: synthesis reads only the markdown.
"""

import logging

from langchain_core.messages import AIMessage

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

    try:
        plan = parse_json_response(response)
        itinerary = _format(plan)
    except (ValueError, KeyError, TypeError):
        # Keep the raw text rather than failing the agent — the UI renders it as
        # markdown, so a bad parse costs the day-by-day view and nothing else.
        logger.warning("Itinerary JSON did not parse; falling back to raw text.")
        plan = {}
        itinerary = response

    return {
        "itinerary": itinerary,
        "itinerary_plan": plan,
        "messages": [AIMessage(content="Itinerary agent produced a day-by-day plan.")],
    }


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
