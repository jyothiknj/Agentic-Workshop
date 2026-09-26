# Epic 1 Context: Triage data and schema

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Lay the foundation that the triage agent (Epic 2) and its eval (Epic 3) build against: a strict, exact schema for a triage decision, and a one-command, repeatable loader that puts the seed ticket and customer data into a local SQLite `app.db` that the existing MCP server already reads. Nothing in the later epics can start until both exist. (Note: this repo has no planning artifacts directory, so there is no PRD, architecture or UX doc. This context is compiled only from the Epic 1 spec and its story list.)

## Stories

- Story 1.1: The triage-decision schema
- Story 1.2: The seed loader

## Requirements & Constraints

- **Schema:** a triage decision is a JSON object with exactly four fields:
  - `category`: one of `billing | bug | access | performance | how-to`
  - `priority`: one of `P1 | P2 | P3 | P4`
  - `route`: one of `billing-team | bug-team | access-team | performance-team | how-to-team`
  - `rationale`: a non-empty, one-sentence string
- A bad value for any field, a missing field, an empty rationale, or any extra field is rejected with an error that **names the offending field**.
- **Loader:** `uv run python load_seed.py` loads `seed/tickets.csv` and `seed/customers.csv` into `app.db` at the repo root, as tables `tickets` and `customers`. Their columns and row counts must match the CSVs.
- **Idempotent:** a second run leaves both tables exactly as they were after the first run, with no duplicate rows.
- **Success signal:** after running the loader twice, the MCP server's `get_ticket("T-1042")` and `get_customer_history("C-77")` return rows (C-77 is Northwind), and `uv run pytest` shows the schema accepting a valid decision and rejecting each invalid field with a named error.
- `seed/` is read-only: the loader reads the CSVs and never writes to them.
- No network calls and no API keys anywhere in this epic.
- `app.db` is never committed.
- Out of scope: the agent, the MCP tools, evals and any UI.

## Technical Decisions

- Python 3.12 or newer, managed with uv. Add packages with `uv add`, never pip.
- The table and column names are fixed by `mcp/triage_server.py`, which must keep working unchanged:
  - `tickets(ticket_id, customer_id, created_at, text)`
  - `customers(customer_id, name, plan, open_tickets)`
  - The server resolves `app.db` relative to the repo root.
- The schema is a shared contract. Epic 2 returns it as the agent's structured output, and Epic 3's `valid_schema` scorer validates against it. It must be importable, and its field names and allowed values must not drift.
- Open questions the spec leaves unresolved (do not invent answers; raise them if a story depends on one):
  - Must `route` match `category` 1:1 (the policy's billing to billing-team mapping and so on), or is any valid pairing accepted?
  - Is "one sentence" enforced beyond non-empty?
  - Should `customers.open_tickets` be stored as an integer (a later Enterprise rule compares it to 3) or as CSV text?

## Cross-Story Dependencies

- Story 1.1 (schema) ships first because Epics 2 and 3 import it.
- Story 1.2 (loader) is independent of 1.1 within this epic. Epic 2's MCP tool calls depend on the `app.db` it produces.
