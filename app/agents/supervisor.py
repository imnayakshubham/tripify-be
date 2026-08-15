"""Orchestrator: decides which agents a query needs and extracts constraints."""

from langchain_core.messages import AIMessage

from app.agents.base import ask_llm, audited, parse_json_response, to_number
from app.prompts.supervisor import SYSTEM, supervisor_prompt
from app.schema import TravelState

KNOWN_AGENTS = {"destination_agent", "itinerary_agent", "budget_agent"}


@audited("supervisor")
def supervisor_agent(state: TravelState):
    user_query = state["user_query"]

    routing_plan = parse_json_response(
        ask_llm(SYSTEM, supervisor_prompt(user_query))
    )

    # Ignore anything the model invents that is not a real agent.
    selected_agents = [
        agent for agent in routing_plan.get("selected_agents", []) if agent in KNOWN_AGENTS
    ]

    # Every request needs at least one specialist, or there is nothing to synthesise.
    if not selected_agents:
        selected_agents = ["itinerary_agent"]

    trip_constraints = routing_plan.get("trip_constraints", {}) or {}

    # The brief says the budget must never be silently exceeded. A budget that is
    # never checked is the worst version of that, and the model is free to return
    # a budget_amount while omitting budget_agent — well-formed but contradictory.
    # Reconcile the two here rather than trusting the routing decision.
    if to_number(trip_constraints.get("budget_amount")) is not None:
        if "budget_agent" not in selected_agents:
            selected_agents.append("budget_agent")

    return {
        "selected_agents": selected_agents,
        "trip_constraints": trip_constraints,
        "supervisor_reasoning": routing_plan.get("reasoning", ""),
        "messages": [AIMessage(content=f"Routing to: {', '.join(selected_agents)}")],
    }
