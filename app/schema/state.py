import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage


def add_turn_agents(existing: list[str], new: list[str]) -> list[str]:
    """Accumulate contributors, but only for the current turn.

    Every turn starts at the supervisor, so its label begins a fresh list. Continuing a
    conversation resumes the thread, and without this the previous turn's contributors
    would be inherited from the checkpoint and reported again.
    """
    if new and new[0].startswith("supervisor"):
        return list(new)

    return existing + new


class TravelState(TypedDict, total=False):
    """State threaded through every node.

    Only the Annotated fields accumulate. Everything else is last-write-wins, which
    is what lets the destination agent overwrite `trip_constraints`.
    """

    messages: Annotated[list[AnyMessage], operator.add]

    # Set by the API before invoke; agents read plan_id to attribute audit rows.
    plan_id: str
    user_id: str
    user_query: str

    # Orchestration
    trip_constraints: dict[str, Any]
    selected_agents: list[str]
    supervisor_reasoning: str

    # Each specialist produces markdown, which synthesis reads, and the structure it
    # was built from, which the UI renders.
    destination_results: str
    destination_choice: dict[str, Any]
    itinerary: str
    itinerary_plan: dict[str, Any]
    budget_results: str
    budget_assessment: dict[str, Any]

    contributing_agents: Annotated[list[str], add_turn_agents]

    final_response: str
