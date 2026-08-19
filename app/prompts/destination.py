"""Destination agent prompt.

`respects_hard_constraints` is a machine-readable flag so app/agents/destination.py
can enforce the rule in code rather than trusting the model to obey it.
"""

from typing import Any

SYSTEM = (
    "You are a destination specialist. You justify every suggestion against the "
    "user's stated preferences, and you never propose a destination that breaks a "
    "hard constraint. Return strict JSON only."
)


def destination_prompt(
    user_query: str,
    trip_constraints: dict[str, Any],
) -> str:
    hard_constraints = trip_constraints.get("hard_constraints") or []
    soft_preferences = trip_constraints.get("soft_preferences") or []
    named_destination = trip_constraints.get("destination") or ""

    already_chosen = (
        f"""
The user has already named a destination: {named_destination}
Validate it against the constraints rather than replacing it. Keep it as
recommended_destination unless it breaks a hard constraint, in which case put it
in "rejected" and recommend the closest viable alternative.
"""
        if named_destination
        else """
The user has not named a destination. Suggest 3 to 4 candidates.
"""
    )

    return f"""
Suggest destinations that fit this request.

User request:
{user_query}

HARD constraints (non-negotiable — a destination that breaks any of these is unacceptable):
{hard_constraints}

Soft preferences (desirable, may flex):
{soft_preferences}

Other known constraints:
duration_days: {trip_constraints.get("duration_days")}
budget: {trip_constraints.get("budget_amount")} {trip_constraints.get("budget_currency")}
origin: {trip_constraints.get("origin")}
{already_chosen}
Rules you must follow:
1. Every candidate must carry a justification that references the user's actual
   stated preferences, not generic praise.
2. Set "respects_hard_constraints" to false for any candidate that breaks even one
   hard constraint, and say which one in "violated_constraints".
3. Put destinations you considered and ruled out in "rejected", each with the
   constraint that ruled it out. This is what makes the reasoning auditable.
4. recommended_destination must be a candidate with respects_hard_constraints true.

Return only JSON with this schema:
{{
  "recommended_destination": "City, Country",
  "candidates": [
    {{
      "destination": "City, Country",
      "justification": "Why this fits the stated preferences.",
      "estimated_cost": "Rough total for the trip, with currency.",
      "respects_hard_constraints": true,
      "violated_constraints": []
    }}
  ],
  "rejected": [
    {{"destination": "City, Country", "reason": "Which hard constraint it breaks."}}
  ]
}}
"""
