---
id: SPEC-epic-1
companions: [../../../mcp/triage_server.py]
sources: [../../../INTENT.md]
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Epic 1: triage data and schema

## Why

The workshop's triage agent (Epic 2) and its eval (Epic 3) both depend on two things that do not exist yet: a strict shape for a triage decision, and the ticket and customer data in `app.db` that `mcp/triage_server.py` already expects to read. Epic 1 is the foundation both later epics build against, so it must exist and be exact before any agent work starts.

## Capabilities

- **CAP-1**
  - **intent:** Every triage decision is checked against one schema: a JSON object with a `category`, a `priority`, a `route` and a one-sentence `rationale`, and anything else is rejected with a clear error.
  - **success:** A decision with category in `billing | bug | access | performance | how-to`, priority in `P1 | P2 | P3 | P4`, route in `billing-team | bug-team | access-team | performance-team | how-to-team` and a rationale validates. A bad category, bad priority, bad route, missing field or empty rationale is each rejected with an error that names the offending field.

- **CAP-2**
  - **intent:** One command loads the seed data into a local SQLite database the MCP server can read.
  - **success:** After `uv run python load_seed.py`, `app.db` holds tables `tickets` and `customers` with the same columns and row counts as `seed/tickets.csv` and `seed/customers.csv`, and `mcp/triage_server.py`'s `get_ticket("T-1042")` and `get_customer_history("C-77")` return rows from them.

- **CAP-3**
  - **intent:** Reloading the seed data is safe to repeat.
  - **success:** Running `load_seed.py` a second time leaves both tables' contents identical to after the first run: no duplicated rows.

## Constraints

- Python 3.12 or newer, managed with uv; packages are added with `uv add`, never pip.
- `seed/` is read-only: the loader reads the CSVs and never writes to them.
- No network calls and no API keys anywhere in this epic.
- `mcp/triage_server.py`'s table and column names must keep working: `tickets(ticket_id, customer_id, created_at, text)` and `customers(customer_id, name, plan, open_tickets)`, in `app.db` at the repo root.
- The schema is the contract Epics 2 and 3 build against: Epic 2 returns it as the agent's structured output, and Epic 3's `valid_schema` scorer validates against it.
- `app.db` is never committed.

## Non-goals

- The agent, the MCP tools, evals and any user interface.

## Success signal

`uv run python load_seed.py`, run twice, leaves an `app.db` from which `mcp/triage_server.py` returns T-1042 and customer C-77 (Northwind); and `uv run pytest` shows the schema accepting a valid decision and rejecting each invalid field with a named error.

## Assumptions

- Extra fields beyond the four are rejected: "anything else is rejected" is read as covering unknown keys too.

## Open Questions

- Must `route` match `category` (billing → billing-team and so on, the 1:1 mapping in `TRIAGE_POLICY.md`), or is any valid category with any valid route accepted?
- How strictly is "one-sentence rationale" enforced: non-empty only, or also checked to be a single sentence?
- Should `customers.open_tickets` be stored as an integer (the Enterprise rule compares it to 3) or kept as CSV text?
