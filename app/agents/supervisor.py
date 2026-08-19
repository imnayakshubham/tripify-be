"""Orchestrator: decides which agents a query needs and extracts constraints."""

from langchain_core.messages import AIMessage

from app.agents.base import ask_llm, audited, parse_json_response, to_number
from app.prompts.supervisor import SYSTEM, supervisor_prompt
from app.schema import TravelState

KNOWN_AGENTS = {"destination_agent", "itinerary_agent", "budget_agent"}

# final_response is what the UI renders, so it must never be empty.
OFF_TOPIC_REPLY = (
    "I plan trips. Tell me roughly where you would like to go — or ask me to suggest "
    "somewhere — how long you have, and any budget, and I'll put a plan together."
)


def _transcript(state: TravelState) -> str:
    """Earlier turns, oldest first. The last message is this turn's query, sent separately."""
    messages = (state.get("messages") or [])[:-1]

    lines = []
    for message in messages:
        text = str(getattr(message, "content", "") or "").strip()
        if not text:
            continue
        speaker = "User" if message.__class__.__name__ == "HumanMessage" else "Assistant"
        lines.append(f"{speaker}: {text}")

    return "\n\n".join(lines)


def _merge_constraints(existing: dict, extracted: dict) -> dict:
    """Later turns refine the trip, they do not restart it.

    A follow-up like "make it cheaper" carries no destination, and last-write-wins state
    would blank the one the destination agent already chose. Only real values overwrite.
    """
    merged = dict(existing)
    for key, value in extracted.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


@audited("supervisor")
def supervisor_agent(state: TravelState):
    user_query = state["user_query"]

    routing_plan = parse_json_response(
        ask_llm(SYSTEM, supervisor_prompt(user_query, _transcript(state)))
    )

    # Ignore anything the model invents that is not a real agent.
    selected_agents = [
        agent for agent in routing_plan.get("selected_agents", []) if agent in KNOWN_AGENTS
    ]

    trip_constraints = _merge_constraints(
        state.get("trip_constraints") or {}, routing_plan.get("trip_constraints", {}) or {}
    )

    # The model can return a budget_amount while omitting budget_agent — well-formed
    # but contradictory, and an unchecked budget is the worst way to exceed one. Runs
    # before the empty check below: a stated budget means this really is a trip.
    if to_number(trip_constraints.get("budget_amount")) is not None:
        if "budget_agent" not in selected_agents:
            selected_agents.append("budget_agent")

    # Nothing to route: not a trip, or too vague to plan from. The supervisor answers
    # and the graph ends here rather than inventing a trip the user never asked for.
    if not selected_agents:
        return {
            "selected_agents": [],
            "trip_constraints": trip_constraints,
            "supervisor_reasoning": routing_plan.get("reasoning", ""),
            "final_response": routing_plan.get("direct_reply", "").strip() or OFF_TOPIC_REPLY,
            "messages": [AIMessage(content="No specialist needed.")],
        }

    return {
        "selected_agents": selected_agents,
        "trip_constraints": trip_constraints,
        "supervisor_reasoning": routing_plan.get("reasoning", ""),
        "messages": [AIMessage(content=f"Routing to: {', '.join(selected_agents)}")],
    }
