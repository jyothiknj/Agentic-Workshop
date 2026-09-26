"""Tests for the triage-decision schema: one test per I/O matrix row."""

import json
from typing import get_args

import pytest
from pydantic import ValidationError

from triage_schema import (
    ROUTE_FOR_CATEGORY,
    Category,
    Route,
    TriageDecision,
    validate_decision,
)

VALID = {
    "category": "billing",
    "priority": "P2",
    "route": "billing-team",
    "rationale": "Double charge puts money at stake, so P2.",
}


def with_(**changes):
    return {**VALID, **changes}


def assert_rejected(data, field, *fragments):
    """Assert rejection; a field error must be located on ``field``."""
    with pytest.raises(ValueError) as exc_info:
        validate_decision(data)
    exc = exc_info.value
    if isinstance(exc, ValidationError):
        locs = [error["loc"][0] for error in exc.errors() if error["loc"]]
        assert field in locs, f"{field!r} not in error locations: {locs}"
    message = str(exc)
    for fragment in (field, *fragments):
        assert fragment in message, f"{fragment!r} not in error: {message}"


def test_route_for_category_matches_policy():
    assert ROUTE_FOR_CATEGORY == {
        "billing": "billing-team",
        "bug": "bug-team",
        "access": "access-team",
        "performance": "performance-team",
        "how-to": "how-to-team",
    }
    assert set(ROUTE_FOR_CATEGORY) == set(get_args(Category))
    assert set(ROUTE_FOR_CATEGORY.values()) == set(get_args(Route))


def test_valid_dict():
    decision = validate_decision(VALID)
    assert isinstance(decision, TriageDecision)
    assert decision.model_dump() == VALID


def test_valid_json_string():
    assert validate_decision(json.dumps(VALID)) == validate_decision(VALID)


def test_model_dump_is_plain_four_key_dict():
    dumped = validate_decision(VALID).model_dump()
    assert type(dumped) is dict
    assert set(dumped) == {"category", "priority", "route", "rationale"}
    assert json.loads(json.dumps(dumped)) == VALID


@pytest.mark.parametrize("category, route", sorted(ROUTE_FOR_CATEGORY.items()))
@pytest.mark.parametrize("priority", ["P1", "P2", "P3", "P4"])
def test_every_allowed_value_accepted(category, route, priority):
    data = with_(category=category, route=route, priority=priority)
    assert validate_decision(data).model_dump() == data


@pytest.mark.parametrize("value", ["sales", "Billing", "BILLING", " billing"])
def test_bad_category(value):
    assert_rejected(with_(category=value), "category")


@pytest.mark.parametrize("value", ["P5", "p2", "P0", "2", 2])
def test_bad_priority(value):
    assert_rejected(with_(priority=value), "priority")


@pytest.mark.parametrize("value", ["sales-team", "Billing-Team", "billing"])
def test_bad_route(value):
    assert_rejected(with_(route=value), "route")


def test_mismatched_route():
    assert_rejected(with_(route="bug-team"), "route", "billing-team")


def test_multi_sentence_rationale_accepted():
    data = with_(rationale="Money at stake. Enterprise rule not met.")
    assert validate_decision(data).rationale == data["rationale"]


@pytest.mark.parametrize("field", ["category", "priority", "route", "rationale"])
def test_missing_field(field):
    data = {k: v for k, v in VALID.items() if k != field}
    assert_rejected(data, field)


@pytest.mark.parametrize("value", ["", "   ", "\n\t "])
def test_empty_rationale(value):
    assert_rejected(with_(rationale=value), "rationale")


@pytest.mark.parametrize("field", ["category", "route", "rationale"])
@pytest.mark.parametrize("value", [1, None])
def test_non_string_not_coerced(field, value):
    assert_rejected(with_(**{field: value}), field)


def test_extra_field():
    assert_rejected(with_(confidence=0.9), "confidence")


@pytest.mark.parametrize(
    "data",
    ["{not json", "[1, 2]", "null", "42", [VALID], None, "[" * 100000],
    ids=[
        "malformed-json",
        "json-list",
        "json-null",
        "json-number",
        "list",
        "none",
        "deeply-nested",
    ],
)
def test_not_an_object(data):
    with pytest.raises(ValueError, match="not a JSON object"):
        validate_decision(data)
