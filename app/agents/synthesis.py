"""Synthesis: one coherent answer, naming the agents that produced it."""

from langchain_core.messages import AIMessage

from app.agents.base import ask_llm, audited
from app.prompts.synthesis import SYSTEM, synthesis_prompt
from app.schema import TravelState


@audited("synthesis")
def synthesis_agent(state: TravelState):
    contributed = state.get("contributing_agents", []) or []

    # A successful supervisor is orchestration, not a knowledge contribution, so
    # it is not named as a source. A *failed* one must still be reported: it
    # means no specialist ran at all, and matching on the "supervisor" prefix
    # used to drop "supervisor (failed)" into neither list, so the answer was
    # assembled from three empty sections with no sign anything had broken.
    failed = [
        name.removesuffix(" (failed)") for name in contributed if name.endswith("(failed)")
    ]
    succeeded = [
        name for name in contributed if name != "supervisor" and not name.endswith("(failed)")
    ]

    answer = ask_llm(
        SYSTEM,
        synthesis_prompt(
            user_query=state["user_query"],
            contributing_agents=succeeded,
            destination_results=state.get("destination_results", ""),
            itinerary=state.get("itinerary", ""),
            budget_results=state.get("budget_results", ""),
            failed_agents=failed,
        ),
    )

    return {
        "final_response": answer,
        "messages": [AIMessage(content=answer)],
    }
