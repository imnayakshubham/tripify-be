"""Itinerary agent prompt.

Behavioural constraint from the brief: each day must be realistic on travel time
and sequencing, and it must say so when it is uncertain.

The output is structured rather than free prose so the UI can render a real
day-by-day plan. Note what that does to the uncertainty rule: instead of asking
for the words "Uncertain: ..." somewhere in a paragraph, uncertainty gets its own
field per segment. The obligation is unchanged; it is just addressable now.
"""

from typing import Any

# The closed set the UI colour-codes by. Free-form categories would produce an
# unbounded palette, so the prompt is told to pick from these and nothing else.
CATEGORIES = (
    "transport",
    "food",
    "sightseeing",
    "accommodation",
    "activity",
    "other",
)

SYSTEM = (
    "You are an itinerary planner. You keep each day realistic on travel time and "
    "sequencing, and you state your uncertainty plainly instead of inventing "
    "specifics you cannot know. Return strict JSON only."
)


def itinerary_prompt(
    user_query: str,
    trip_constraints: dict[str, Any],
    destination_results: str,
) -> str:
    destination_context = (
        f"""
Context from the destination specialist:
{destination_results}
"""
        if destination_results
        else ""
    )

    return f"""
Build a day-by-day itinerary.

User request:
{user_query}

Destination: {trip_constraints.get("destination")}
Duration: {trip_constraints.get("duration_days")} days
Hard constraints (must not be broken): {trip_constraints.get("hard_constraints") or []}
Soft preferences: {trip_constraints.get("soft_preferences") or []}
{destination_context}
Rules you must follow:
1. Each day must be physically realistic. Account for travel time between
   locations, and do not schedule things that cannot be reached in the time given.
2. Sequence the days sensibly — group activities by area, and do not bounce back
   and forth across a region.
3. Where you are uncertain, SAY SO. Opening hours, seasonal closures, exact
   journey times, and current prices are things you cannot verify. Put the doubt
   in that segment's "uncertainty" field rather than stating an unverified
   specific as fact, and list anything that should be checked before booking in
   the top-level "uncertainties" array. Leave "uncertainty" as "" when you are
   genuinely confident.
4. Do not invent precise prices, timetables, or booking details.
5. "category" must be exactly one of: {", ".join(CATEGORIES)}.
6. "part_of_day" must be exactly one of: morning, afternoon, evening.

Return only JSON with this schema:
{{
  "summary": "One short paragraph framing the trip.",
  "days": [
    {{
      "day": 1,
      "title": "Short label for the day, e.g. 'Arrival and the old town'.",
      "segments": [
        {{
          "part_of_day": "morning",
          "activity": "What the traveller actually does, in one sentence.",
          "category": "sightseeing",
          "duration": "Rough time it takes, e.g. '~3h'.",
          "uncertainty": "What you cannot verify here, or empty string."
        }}
      ]
    }}
  ],
  "uncertainties": ["Things to check before booking."]
}}
"""
