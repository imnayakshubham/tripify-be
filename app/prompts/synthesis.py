"""Synthesis prompt: fold the specialists into one coherent answer.

The brief asks that the answer show which agents contributed, because
transparency matters in a real tool — so the contributing agents are named in the
prompt and the model is told to attribute.
"""

SYSTEM = (
    "You combine specialist agent outputs into one coherent travel answer. You "
    "attribute what came from where, and you never quietly drop a warning an "
    "agent raised."
)


def synthesis_prompt(
    user_query: str,
    contributing_agents: list[str],
    destination_results: str,
    itinerary: str,
    budget_results: str,
    failed_agents: list[str],
) -> str:
    failure_note = (
        f"""
These agents failed and produced nothing: {failed_agents}
Say plainly which part of the answer is missing as a result. Do not paper over it.
"""
        if failed_agents
        else ""
    )

    return f"""
Write a single coherent answer to the user's request, drawing on the specialist
outputs below.

User request:
{user_query}

Agents that contributed: {contributing_agents}

--- Destination specialist ---
{destination_results or "(did not run)"}

--- Itinerary specialist ---
{itinerary or "(did not run)"}

--- Budget specialist ---
{budget_results or "(did not run)"}
{failure_note}
Rules you must follow:
1. One flowing answer, not three reports stapled together.
2. Carry forward every warning the specialists raised — especially a budget
   overage or an uncertainty flagged in the itinerary. Never silently drop one.
3. Attribute inline where it helps the reader trust the answer, for example
   "the budget check found...".
4. End with a short "Agents consulted" line naming exactly the agents listed above.
5. Use markdown. Be concise; do not repeat the full itinerary if it is already clear.
"""
