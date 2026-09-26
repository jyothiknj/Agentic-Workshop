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
  - `rationale`: a non-empty string (after trimming whitespace); it is not checked to be one sentence
- `route` must be the one the policy pairs with `category` (billing → billing-team, bug → bug-team, access → access-team, performance → performance-team, how-to → how-to-team); a mismatched pair is rejected, naming `route`.
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
- Decisions made by the stories (the Epic 1 `SPEC.md` still lists these as open questions):
  - `route` must match `category` 1:1 (story 1.1).
  - The rationale is only checked for being non-empty (story 1.1).
  - Every column in `app.db` is TEXT, including `customers.open_tickets`, so `get_customer_history` returns `"open_tickets": "2"`; Epic 2 converts it before the Enterprise rule's "3 or more" comparison (story 1.2).

## Cross-Story Dependencies

- Story 1.1 (schema) ships first because Epics 2 and 3 import it.
- Story 1.2 (loader) is independent of 1.1 within this epic. Epic 2's MCP tool calls depend on the `app.db` it produces.
