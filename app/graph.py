"""Orchestration: the supervisor picks the specialists, routing chains them in
dependency order and falls through to synthesis. Picking none ends the run — the
supervisor has already answered."""

from langgraph.graph import END, START, StateGraph

from app.agents import (
    budget_agent,
    destination_agent,
    itinerary_agent,
    supervisor_agent,
    synthesis_agent,
)
from app.configs import DATABASE_URL
from app.db import build_checkpointer
from app.schema import TravelState

# Sequential, never parallel — each agent reads what the last one wrote. You cannot
# plan days without a destination, or cost a plan that does not exist.
AGENT_ORDER = [
    "destination_agent",
    "itinerary_agent",
    "budget_agent",
]

# Every hop either lands on the next selected specialist or on synthesis. END is only
# reachable from the supervisor, which answers directly when no specialist is needed.
ROUTE_TARGETS = AGENT_ORDER + ["synthesis", END]


def selected_agents_in_order(state: TravelState) -> list[str]:
    """The supervisor's picks, sorted into dependency order."""
    selected_agents = state.get("selected_agents") or []
    return [agent for agent in AGENT_ORDER if agent in selected_agents]


def route_from_supervisor(state: TravelState) -> str:
    # No specialist means there is nothing to synthesise — the supervisor already wrote
    # final_response, so ending here saves a pointless LLM call.
    selected_agents = selected_agents_in_order(state)
    return selected_agents[0] if selected_agents else END


def route_after_agent(current_agent: str):
    """Build the router that runs once `current_agent` finishes."""

    def route(state: TravelState) -> str:
        selected_agents = selected_agents_in_order(state)
        current_position = AGENT_ORDER.index(current_agent)

        for next_agent in AGENT_ORDER[current_position + 1:]:
            if next_agent in selected_agents:
                return next_agent

        return "synthesis"

    return route


def build_graph():
    builder = StateGraph(TravelState)

    builder.add_node("supervisor", supervisor_agent)
    builder.add_node("destination_agent", destination_agent)
    builder.add_node("itinerary_agent", itinerary_agent)
    builder.add_node("budget_agent", budget_agent)
    builder.add_node("synthesis", synthesis_agent)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", route_from_supervisor, ROUTE_TARGETS)

    for agent_name in AGENT_ORDER:
        builder.add_conditional_edges(agent_name, route_after_agent(agent_name), ROUTE_TARGETS)

    builder.add_edge("synthesis", END)

    if DATABASE_URL:
        return builder.compile(checkpointer=build_checkpointer())

    return builder.compile()


travel_graph = build_graph()
