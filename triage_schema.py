"""The triage-decision schema (Epic 1, CAP-1).

One definition of a triage decision: Epic 2 passes ``TriageDecision`` to the
agent as its structured output, and Epic 3's ``valid_schema`` scorer checks
raw output with ``validate_decision``. Allowed values come from
``TRIAGE_POLICY.md``. Validation is local: no network, no API keys.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

Category = Literal["billing", "bug", "access", "performance", "how-to"]
Priority = Literal["P1", "P2", "P3", "P4"]
Route = Literal[
    "billing-team", "bug-team", "access-team", "performance-team", "how-to-team"
]

# The 1:1 category -> route pairing from TRIAGE_POLICY.md.
ROUTE_FOR_CATEGORY: dict[str, str] = {
    "billing": "billing-team",
    "bug": "bug-team",
    "access": "access-team",
    "performance": "performance-team",
    "how-to": "how-to-team",
}


class TriageDecision(BaseModel):
    """A triage decision: category, priority, route and a rationale."""

    model_config = ConfigDict(extra="forbid", strict=True)

    category: Category
    priority: Priority
    route: Route
    rationale: str

    @field_validator("rationale")
    @classmethod
    def _rationale_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale must not be empty")
        return value

    @field_validator("route")
    @classmethod
    def _route_matches_category(cls, value: str, info: ValidationInfo) -> str:
        # Only checked when category itself is valid; otherwise the category
        # error is the one to report.
        category = info.data.get("category")
        if category is not None:
            expected = ROUTE_FOR_CATEGORY[category]
            if value != expected:
                raise ValueError(
                    f"route {value!r} does not match category {category!r}; "
                    f"expected {expected!r}"
                )
        return value


def validate_decision(data: dict[str, Any] | str) -> TriageDecision:
    """Validate a decision given as a dict or a JSON string.

    Raises ``ValueError`` (a ``pydantic.ValidationError`` for field problems)
    whose message names the offending field.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        # ValueError also covers JSONDecodeError and oversized integers.
        except (ValueError, RecursionError) as exc:
            raise ValueError(
                f"triage decision is not a JSON object: invalid JSON ({exc})"
            ) from exc
    if not isinstance(data, dict):
        raise ValueError(
            "triage decision is not a JSON object: "
            f"got {type(data).__name__}"
        )
    return TriageDecision.model_validate(data)
