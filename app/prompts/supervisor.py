"""Orchestrator prompt: pick the agents, and separate hard constraints from soft ones."""

SYSTEM = "You route work to specialist agents. Return strict JSON only."


def supervisor_prompt(user_query: str) -> str:
    return f"""
You are the orchestrator of a multi-agent travel planning system.

Decide which specialist agents this request needs, and extract the user's constraints.

Available agents:
- destination_agent: needed when the user has NOT named a specific destination, or wants
  suggestions or validation of where to go.
- itinerary_agent: needed when the user wants a day-by-day plan for a trip.
- budget_agent: needed when the user mentions cost, budget, affordability, or a price cap.

Agents run in the order destination -> itinerary -> budget, and later agents see
earlier results. Select every agent the request genuinely needs.

Separate the constraints carefully:
- hard_constraints: things the user stated as non-negotiable. A suggestion that
  breaks one of these is unacceptable. Examples: "under 1500 pounds",
  "in Europe", "exactly five days", "no flights over 4 hours".
- soft_preferences: things the user would like but that can flex. Examples:
  "somewhere warm", "good food", "not too touristy".

Return only JSON with this schema:
{{
  "selected_agents": ["destination_agent", "itinerary_agent", "budget_agent"],
  "trip_constraints": {{
    "destination": "",
    "origin": "",
    "duration_days": null,
    "budget_amount": null,
    "budget_currency": "",
    "hard_constraints": [],
    "soft_preferences": []
  }},
  "reasoning": "One or two sentences on why these agents, in plain language."
}}

Use an ISO 4217 code for "budget_currency" ("GBP", not "pounds"), so it can be
compared with the budget agent's own currency.

Leave "destination" as an empty string when the user has not named one.
Use null for numbers you cannot determine.

User request:
{user_query}
"""
