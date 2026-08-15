"""Budget agent prompt.

Behavioural constraint from the brief: must never silently exceed the budget. It
flags the overage and proposes a cheaper alternative. The output is structured so
the agent can verify that in code — a prompt instruction alone is not a guarantee.
"""

from typing import Any

SYSTEM = (
    "You are a travel budget analyst. You never let a plan quietly exceed the "
    "user's budget: you state the overage explicitly and always offer a cheaper "
    "alternative. Return strict JSON only."
)


def budget_prompt(
    user_query: str,
    trip_constraints: dict[str, Any],
    itinerary: str,
    destination_results: str,
) -> str:
    return f"""
Estimate what this plan actually costs, and check it against the user's budget.

User request:
{user_query}

Stated budget: {trip_constraints.get("budget_amount")} {trip_constraints.get("budget_currency")}
Duration: {trip_constraints.get("duration_days")} days
Destination: {trip_constraints.get("destination")}
Hard constraints: {trip_constraints.get("hard_constraints") or []}

The plan to cost:
{itinerary or "(no itinerary was produced — cost the trip described in the request)"}

Destination notes:
{destination_results or "(none)"}

Rules you must follow:
1. Break the estimate into categories: flights, accommodation, food, local
   transport, activities, and a contingency.
2. If the total exceeds the budget you MUST set within_budget to false, put the
   shortfall in overage_amount, and give a concrete cheaper_alternative that would
   bring it within budget. Never report an over-budget plan without an alternative.
3. If it fits, still say how much headroom is left.
4. These are estimates from general knowledge, not live prices. Say so.
5. Every money value must be a plain number — no currency symbols, no thousands
   separators, no ranges. Put the currency in the "currency" field only.
6. The cheaper alternative's savings must be itemised and must add up to at
   least the overage. The saving is checked against the shortfall in code, and
   an alternative that does not close the gap is reported to the user as
   insufficient — so do not pad it or guess.

Return only JSON with this schema:
{{
  "currency": "GBP",
  "estimated_total": 1450,
  "budget_amount": 1500,
  "within_budget": true,
  "overage_amount": 0,
  "breakdown": [{{"category": "flights", "estimate": 220, "notes": ""}}],
  "cheaper_alternative": {{
    "description": "One sentence on the concrete swap.",
    "changes": [{{"change": "Hostel instead of hotel", "saving": 200}}],
    "estimated_saving": 200
  }},
  "assessment": "A short plain-language verdict for the traveller."
}}
"""
