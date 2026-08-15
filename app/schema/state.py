import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage


class TravelState(TypedDict, total=False):
    """State threaded through every node.

    Only the two Annotated fields accumulate; everything else is
    last-write-wins, which is what lets the destination agent overwrite
    trip_constraints with its chosen destination.
    """

    messages: Annotated[list[AnyMessage], operator.add]

    # Set by the API before invoke; agents read it to attribute audit rows.
    plan_id: str
    user_id: str
    user_query: str

    # Orchestration
    trip_constraints: dict[str, Any]
    selected_agents: list[str]
    supervisor_reasoning: str

    # Agent outputs. Each specialist produces both a markdown rendering (which
    # the synthesis agent reads) and the structure it was built from (which the
    # UI renders). The markdown is a view of the structure, not the source.
    destination_results: str
    destination_choice: dict[str, Any]
    itinerary: str
    itinerary_plan: dict[str, Any]
    budget_results: str
    budget_assessment: dict[str, Any]

    # Which agents actually contributed, accumulated as the chain runs.
    contributing_agents: Annotated[list[str], operator.add]

    final_response: str
