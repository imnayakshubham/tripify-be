"""Budget agent.

Brief: "It must never silently exceed the budget. It flags the overage and
proposes a cheaper alternative."

"Never" is not something a prompt guarantees, so the checks are in code, and they
fail *closed*: anything this module cannot verify is reported as unverified
rather than passed as fine.

Three things are enforced here rather than asked for:

1. The comparison is anchored on the budget the *user* stated. The model echoes
   a budget back and that echo can drift upward; trusting it would turn a real
   overage into a verified-looking pass, which is worse than no check at all.
2. `within_budget` is recomputed, and deleted outright when it cannot be
   recomputed. A figure that will not parse, or a currency mismatch, yields None
   ("could not verify") — never True.
3. The cheaper alternative is checked against the shortfall. The brief asks the
   agent to propose one; a proposal that does not actually close the gap is
   reported as insufficient instead of presented as the solution.
"""

from langchain_core.messages import AIMessage

from app.agents.base import (
    ask_llm,
    audited,
    normalise_currency,
    parse_json_response,
    to_number,
)
from app.prompts.budget import SYSTEM, budget_prompt
from app.schema import TravelState

# Local alias: this module reads as arithmetic, and `_number` is what the
# formatting helpers below have always called it.
_number = to_number


@audited("budget_agent")
def budget_agent(state: TravelState):
    trip_constraints = state.get("trip_constraints", {}) or {}

    assessment = parse_json_response(
        ask_llm(
            SYSTEM,
            budget_prompt(
                user_query=state["user_query"],
                trip_constraints=trip_constraints,
                itinerary=state.get("itinerary", ""),
                destination_results=state.get("destination_results", ""),
            ),
        )
    )

    _verify(assessment, trip_constraints)

    return {
        "budget_results": _format(assessment),
        "budget_assessment": assessment,
        "messages": [AIMessage(content="Budget agent costed the plan.")],
    }


def _verify(assessment: dict, trip_constraints: dict) -> None:
    """Recompute the verdict in place. Fails closed."""
    estimated_total = _number(assessment.get("estimated_total"))

    # The user's stated budget wins. The model's is only a fallback for when the
    # user never gave one — never an override of one they did.
    stated_budget = _number(trip_constraints.get("budget_amount"))
    budget_amount = (
        stated_budget if stated_budget is not None else _number(assessment.get("budget_amount"))
    )

    # Carry the resolved figure so downstream readers compare against the same
    # number this verdict used, instead of the model's version or nothing.
    if budget_amount is not None:
        assessment["budget_amount"] = budget_amount

    if budget_amount is None:
        # No budget anywhere: there is nothing to exceed, so there is no claim
        # to make. Drop the model's flag rather than let it assert one.
        assessment.pop("within_budget", None)
        assessment.pop("overage_amount", None)
        return

    # Comparing bare floats across currencies is meaningless. But only flag a
    # mismatch when both sides are *recognised and different*: the supervisor
    # extracts the user's wording ("pounds") while this agent returns a code
    # ("GBP"), and treating that as a mismatch reported a real overage as
    # unverifiable — hiding exactly what this check exists to surface.
    stated_currency = normalise_currency(trip_constraints.get("budget_currency"))
    quoted_currency = normalise_currency(assessment.get("currency"))
    currency_mismatch = bool(
        stated_currency and quoted_currency and stated_currency != quoted_currency
    )

    if estimated_total is None or currency_mismatch:
        # Unverifiable. None is a third state, distinct from "within budget".
        assessment["within_budget"] = None
        assessment["overage_amount"] = None
        assessment["unverified_reason"] = (
            f"the estimate is quoted in {quoted_currency} but the budget is in {stated_currency}"
            if currency_mismatch
            else "the estimated total could not be read as a number"
        )
        return

    assessment.pop("unverified_reason", None)
    assessment["within_budget"] = estimated_total <= budget_amount
    assessment["overage_amount"] = max(0.0, round(estimated_total - budget_amount, 2))

    if not assessment["within_budget"]:
        _verify_alternative(assessment, estimated_total, budget_amount)


def _verify_alternative(assessment: dict, estimated_total: float, budget_amount: float) -> None:
    """Check the proposed alternative actually brings the trip within budget."""
    alternative = assessment.get("cheaper_alternative")

    # Accept the older plain-string shape so a model that ignores the schema
    # still produces something usable — just unverifiable.
    if isinstance(alternative, str):
        alternative = {"description": alternative.strip()} if alternative.strip() else None
        assessment["cheaper_alternative"] = alternative

    if not isinstance(alternative, dict):
        assessment["alternative_closes_gap"] = None
        return

    saving = _number(alternative.get("estimated_saving"))
    if saving is None:
        # Fall back to summing the itemised changes.
        changes = alternative.get("changes") or []
        savings = [_number(change.get("saving")) for change in changes if isinstance(change, dict)]
        known = [value for value in savings if value is not None]
        saving = sum(known) if known else None

    if saving is None:
        assessment["alternative_closes_gap"] = None
        return

    resulting_total = round(estimated_total - saving, 2)
    assessment["alternative_estimated_saving"] = saving
    assessment["alternative_resulting_total"] = resulting_total
    assessment["alternative_closes_gap"] = resulting_total <= budget_amount


def _format(assessment: dict) -> str:
    currency = assessment.get("currency", "")
    total = assessment.get("estimated_total")
    budget = assessment.get("budget_amount")
    # No default: a missing flag means unverified, never "fine".
    within_budget = assessment.get("within_budget")
    overage = assessment.get("overage_amount") or 0
    alternative = assessment.get("cheaper_alternative")

    lines = [f"**Estimated total: {currency} {total}**"]

    if budget is not None:
        lines.append(f"Your budget: {currency} {budget}")

    if within_budget is None and budget is not None:
        reason = assessment.get("unverified_reason", "the figures could not be compared")
        lines.append("")
        lines.append(
            f"⚠️ **This estimate could not be checked against your budget** — {reason}. "
            "Treat the total as unverified."
        )
    elif within_budget is False:
        lines.append("")
        lines.append(f"⚠️ **Over budget by {currency} {overage}.**")
        lines.extend(_alternative_lines(assessment, alternative, currency))
    elif within_budget is True:
        headroom = _number(budget)
        spent = _number(total)
        if headroom is not None and spent is not None:
            lines.append(
                f"\n✅ Within budget, with {currency} {round(headroom - spent, 2)} of headroom."
            )
        else:
            lines.append("\n✅ Within budget.")

    breakdown = assessment.get("breakdown") or []
    if breakdown:
        lines.append("\n| Category | Estimate | Notes |")
        lines.append("| --- | --- | --- |")
        for item in breakdown:
            lines.append(
                f"| {item.get('category', '')} | {currency} {item.get('estimate', '')} "
                f"| {item.get('notes', '')} |"
            )

    if assessment.get("assessment"):
        lines.append(f"\n{assessment['assessment']}")

    return "\n".join(lines)


def _alternative_lines(assessment: dict, alternative, currency: str) -> list[str]:
    """The overage is never reported without an alternative, or without saying
    the alternative is missing or insufficient."""
    if not isinstance(alternative, dict) or not alternative.get("description"):
        # The constraint is enforced here, not left to the model.
        return [
            "\n**Cheaper alternative:** none was produced. Treat this plan as "
            "unaffordable as specified — reduce the trip length, move to a "
            "lower-cost destination, or raise the budget before booking."
        ]

    lines = [f"\n**Cheaper alternative:** {alternative['description']}"]

    for change in alternative.get("changes") or []:
        if not isinstance(change, dict):
            continue
        saving = _number(change.get("saving"))
        suffix = f" (saves {currency} {saving})" if saving is not None else ""
        lines.append(f"- {change.get('change', '')}{suffix}")

    closes_gap = assessment.get("alternative_closes_gap")
    resulting = assessment.get("alternative_resulting_total")

    if closes_gap is True:
        lines.append(f"\nThat would bring the trip to about {currency} {resulting} — within budget.")
    elif closes_gap is False:
        still_over = round(resulting - _number(assessment.get("budget_amount")), 2)
        lines.append(
            f"\n⚠️ Even with this change the trip is about {currency} {resulting}, "
            f"still {currency} {still_over} over. It does not bring the trip within budget."
        )
    else:
        lines.append(
            "\n⚠️ The saving from this change was not quantified, so it is not "
            "confirmed to bring the trip within budget."
        )

    return lines
