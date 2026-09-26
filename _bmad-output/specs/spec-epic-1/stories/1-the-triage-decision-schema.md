---
title: 'The triage-decision schema'
type: 'feature'
created: '2026-09-26'
status: 'done'
baseline_commit: '984d093b5a0bb5b55ab0121f1dbe0153b55d62d0'
route: 'dispatch'
review_loop_iteration: 0
context: ['{project-root}/_bmad-output/specs/spec-epic-1/SPEC.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** There is no single definition of a triage decision, and Epic 2 (the agent's structured output) and Epic 3 (the `valid_schema` scorer) both need one to build and score against (Epic 1 CAP-1).

**Approach:** Add one importable schema: a JSON object with exactly four fields, `category`, `priority`, `route` and `rationale`, each restricted to the values the policy allows. Anything else is rejected with an error that names the offending field.

## Boundaries & Constraints

**Always:** Allowed values are exactly: category `billing | bug | access | performance | how-to`; priority `P1 | P2 | P3 | P4`; route `billing-team | bug-team | access-team | performance-team | how-to-team`. Values are case-sensitive and never coerced. Unknown extra fields are rejected. Every rejection names the field that failed. Validation runs locally with no network and no API keys.

**Decisions:**
- `route` must be the one `TRIAGE_POLICY.md` pairs with `category` (billing → billing-team, bug → bug-team, access → access-team, performance → performance-team, how-to → how-to-team). A mismatched pair is rejected with an error naming `route`.
- The rationale is checked only for being non-empty after trimming whitespace. It is not checked to be a single sentence.

**Never:** No agent, MCP, loader, eval or UI code. Do not touch `seed/`, `TRIAGE_POLICY.md`, `eval/labelled_tickets.csv` or `mcp/triage_server.py`. Add no new dependencies; `pydantic` is already declared.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid dict | `{"category":"billing","priority":"P2","route":"billing-team","rationale":"Double charge puts money at stake, so P2."}` | Returns a validated decision | N/A |
| Valid JSON string | The same object as a JSON string | Returns the same validated decision | N/A |
| Bad category | `category: "sales"` | Rejected | Error names `category` |
| Bad priority | `priority: "P5"` or `"p2"` | Rejected | Error names `priority` |
| Bad route | `route: "sales-team"` | Rejected | Error names `route` |
| Mismatched route | `category: "billing"`, `route: "bug-team"` (every valid field, wrong pair) | Rejected | Error names `route` and the expected `billing-team` |
| Multi-sentence rationale | `rationale: "Money at stake. Enterprise rule not met."` | Accepted | N/A |
| Missing field | Any of the four keys absent | Rejected | Error names the missing field |
| Empty rationale | `rationale: ""` or whitespace only | Rejected | Error names `rationale` |
| Extra field | Adds `"confidence": 0.9` | Rejected | Error names `confidence` |
| Not an object | Malformed JSON string, a list, or `null` | Rejected | Clear error saying the input is not a JSON object |

</frozen-after-approval>

## Code Map

- `pyproject.toml` -- `pydantic>=2.8` is already declared; `[tool.pytest.ini_options] testpaths = ["tests"]`. The project isn't installed as a package, so tests can't import a root-level module yet.
- `run_agent.py` -- Epic 2's entry point prints `json.dumps(decision)`, so a decision must dump to a plain dict. Do not change it.
- `mcp/triage_server.py` -- read-only; nothing here touches it.
- `_bmad-output/specs/spec-epic-2/SPEC.md` (CAP-4) and `spec-epic-3/SPEC.md` (CAP-2) -- consumers: the agent's structured output, and `valid_schema`'s pass/fail check.
- `TRIAGE_POLICY.md` -- source of the category, route and priority values.
- `tests/` -- does not exist yet.

## Tasks & Acceptance

**Execution:**
- [x] `triage_schema.py` -- add the `TriageDecision` Pydantic model (Literal fields, `extra="forbid"`, strict strings, rationale must not be blank, a model validator enforcing the category → route pairing) and `validate_decision(data: dict | str) -> TriageDecision`, which parses a JSON string or accepts a dict and raises `ValueError` naming the offending field -- the one schema that Epic 2 passes as structured output and Epic 3 validates against.
- [x] `pyproject.toml` -- add `pythonpath = ["."]` under `[tool.pytest.ini_options]` -- so tests can import root-level modules.
- [x] `tests/test_triage_schema.py` -- one test per I/O matrix row, including a parametrised test over every allowed value of each field -- this proves both acceptance and rejection.

**Acceptance Criteria:**
- Given a valid decision, when it is dumped with `model_dump()`, then the result is a plain dict with exactly the four keys that `json.dumps` can serialise.
- Given the repo after this story, when `uv run pytest` runs, then every test passes with no network access and no API keys set.

## Implementation Notes

- The category → route pairing is enforced by a `field_validator` on `route` (reading the already-validated `category`) rather than a model validator, so the Pydantic error location is `route` as the matrix requires. It runs only when `category` itself is valid.
- `ROUTE_FOR_CATEGORY` is exported for the parametrised tests.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Route | Evidence |
|---|---|---|---|---|---|
| 1 | edge-case | Deeply nested JSON string raises `RecursionError`, not `ValueError` | medium | patch | Reproduced: `validate_decision('['*100000)` raised RecursionError; Epic 3 scorer would crash instead of scoring 0. |
| 2 | edge-case, blind | Rationale of only zero-width chars (`​`) accepted | low | reject | Reproduced, but matches the frozen decision ("non-empty after trimming whitespace"); unlikely from an LLM and the fix adds Unicode-category logic. |
| 3 | edge-case | Task text says model validator; code uses `field_validator` on `route` | false | reject | Deviation is required by the frozen matrix (error must name `route`) and is recorded in Implementation Notes; only fix is editing this spec. |
| 4 | verification-gap, blind | Pairing tests derive expected pairs from `ROUTE_FOR_CATEGORY`; a swapped/missing entry or Literal drift (bare `KeyError`) passes every test | medium | patch | Confirmed: `test_every_allowed_value_accepted` parametrises from the table under test; no independent assertion of the policy mapping. |
| 5 | blind | `assert_rejected` checks message substrings, not error `loc` | low | patch | Confirmed: mismatch message itself contains "route", so a loc regression would pass. Direct test correction. |
| 6 | blind | No `Field(description=...)` to guide the LLM's structured output | maybe-false | reject | Epic 2 CAP-4 feeds TRIAGE_POLICY.md as the agent's instructions and retries once on schema failure; if real, only low. |
| 7 | blind | Strict typing only tested for `priority` | low | patch | Confirmed gap for non-string `category`/`route`/`rationale`; adding a parametrised test is a direct correction. |
| 8 | blind | `bytes` input gives "got bytes"; signature narrower than accepted inputs | low | reject | No caller passes bytes (Epic 3 feeds str output); fix adds a branch. |
| 9 | blind | No upper length limit on rationale | false | reject | Frozen decision checks only non-empty; fix would edit this spec. |
| 10 | blind | Duplicate JSON keys resolved last-wins | maybe-false | reject | Result is still validated against the allowed values and pairing; if real, only low. |

## Design Notes

A Pydantic model is the natural shape because LangChain's structured output accepts one directly (Epic 2), and `ValidationError` already names each failing field by location. `validate_decision` wraps it so that callers holding raw JSON (Epic 3) get one entry point, and so that non-object input gets a clear message rather than a Pydantic internals error. `ValidationError` subclasses `ValueError`, so re-raising it satisfies "raises ValueError".

## Verification

**Commands:**
- `uv run pytest` -- expected: all tests pass.
- `uv run python -c "from triage_schema import validate_decision; print(validate_decision({'category':'billing','priority':'P2','route':'billing-team','rationale':'Money at stake.'}).model_dump())"` -- expected: prints the four-key dict.
