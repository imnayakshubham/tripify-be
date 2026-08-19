"""Destination agent. Candidates the model flagged as breaking a hard constraint are
filtered out here, so a flagged suggestion cannot reach the user."""

from langchain_core.messages import AIMessage

from app.agents.base import ask_llm, audited, parse_json_response
from app.prompts.destination import SYSTEM, destination_prompt
from app.schema import TravelState


@audited("destination_agent")
def destination_agent(state: TravelState):
    trip_constraints = state.get("trip_constraints", {}) or {}

    choice = parse_json_response(
        ask_llm(
            SYSTEM,
            destination_prompt(state["user_query"], trip_constraints),
        )
    )

    all_candidates = choice.get("candidates", []) or []
    rejected = list(choice.get("rejected", []) or [])

    # Enforce the hard-constraint rule rather than trusting the model to.
    viable = []
    for candidate in all_candidates:
        if candidate.get("respects_hard_constraints", False):
            viable.append(candidate)
        else:
            rejected.append(
                {
                    "destination": candidate.get("destination", ""),
                    "reason": "Breaks a hard constraint: "
                    + ", ".join(candidate.get("violated_constraints") or ["unspecified"]),
                }
            )

    recommended = choice.get("recommended_destination", "")

    # The recommendation must itself be viable; fall back to the first that is.
    if recommended not in {candidate.get("destination", "") for candidate in viable}:
        recommended = viable[0]["destination"] if viable else ""

    return {
        "destination_results": _format(recommended, viable, rejected),
        "destination_choice": {
            "recommended_destination": recommended,
            "candidates": viable,
            "rejected": rejected,
        },
        # Feed the chain: itinerary and budget both need a concrete destination.
        "trip_constraints": {**trip_constraints, "destination": recommended},
        "messages": [AIMessage(content=f"Destination agent recommends: {recommended}")],
    }


def _format(recommended: str, viable: list[dict], rejected: list[dict]) -> str:
    if not viable:
        return (
            "No destination could be recommended without breaking one of your "
            "hard constraints.\n\n"
            + "\n".join(
                f"- Ruled out **{entry.get('destination', '?')}** — {entry.get('reason', '')}"
                for entry in rejected
            )
        )

    lines = [f"**Recommended: {recommended}**", ""]

    for candidate in viable:
        lines.append(f"### {candidate.get('destination', '?')}")
        lines.append(candidate.get("justification", ""))
        if candidate.get("estimated_cost"):
            lines.append(f"\n*Rough cost:* {candidate['estimated_cost']}")
        lines.append("")

    if rejected:
        lines.append("### Considered and ruled out")
        for entry in rejected:
            lines.append(f"- **{entry.get('destination', '?')}** — {entry.get('reason', '')}")

    return "\n".join(lines)
