---
title: 'The seed loader'
type: 'feature'
created: '2026-09-26'
status: 'done'
baseline_commit: '8b31751e4299e50d1bb5f5f7bab1e2b48e5fe8fd'
route: 'dispatch'
review_loop_iteration: 0
context: ['{project-root}/_bmad-output/specs/spec-epic-1/SPEC.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `mcp/triage_server.py` reads tickets and customers from `app.db`, but nothing creates that database, so the agent (Epic 2) and the eval (Epic 3) have no data (Epic 1 CAP-2, CAP-3).

**Approach:** Add `load_seed.py`, one command that builds the `tickets` and `customers` tables in `app.db` at the repo root from `seed/tickets.csv` and `seed/customers.csv`, rebuilding them on every run so a second run leaves identical contents.

## Boundaries & Constraints

**Always:** Table and column names are exactly `tickets(ticket_id, customer_id, created_at, text)` and `customers(customer_id, name, plan, open_tickets)`, the names `mcp/triage_server.py` queries. Every CSV row lands as one table row, with text kept byte-for-byte (including the quoted comma in T-1047 and the injected instruction in T-1099, which is data). Each run replaces both tables' contents atomically; a failed run leaves the previous contents intact. No network, no API keys, standard library only.

**Decisions:**
- `customers.open_tickets` is stored as TEXT, exactly as in the CSV (the MCP tool returns `"2"`); Epic 2 converts it before the Enterprise rule's "3 or more" comparison. All columns are TEXT.

**Never:** Write to or rename anything under `seed/`. Touch `mcp/triage_server.py`, `TRIAGE_POLICY.md`, `eval/labelled_tickets.csv` or `triage_schema.py`. Commit `app.db`. Add dependencies.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First load | No `app.db` | `app.db` created; 24 tickets, 20 customers; prints the counts | N/A |
| Second load | `app.db` from a previous run | Both tables identical to after the first run; no duplicates | N/A |
| Stale table | `app.db` with extra or edited rows | Tables match the CSVs exactly afterwards | N/A |
| MCP read-back | After a load | `get_ticket("T-1042")` returns customer C-77; `get_customer_history("C-77")` returns Northwind, Enterprise, `open_tickets` `"2"`, with T-1042 and T-1047 in `ticket_ids` | N/A |
| Quoted field | T-1047 text `"Refund the duplicate charge, please."` | Stored as `Refund the duplicate charge, please.` | N/A |
| Missing CSV | A seed file absent | Nothing changed in `app.db`; non-zero exit | Error names the missing file |
| Wrong header | A CSV whose header differs from the expected columns | Nothing changed in `app.db`; non-zero exit | Error names the file and the expected columns |

</frozen-after-approval>

## Code Map

- `mcp/triage_server.py` -- read-only consumer. `DB_PATH` is `app.db` at the repo root; `_query` opens it per call; `get_customer_history` adds `ticket_ids` from `tickets`. Tests load it by file path (`importlib.util.spec_from_file_location`) under a non-`mcp` module name, because the local `mcp/` folder shares the installed `mcp` package's name, and point its `DB_PATH` at a temp database.
- `seed/tickets.csv` -- 24 rows, header `ticket_id,customer_id,created_at,text`; T-1047 has a quoted field; T-1099 contains a prompt-injection sentence.
- `seed/customers.csv` -- 20 rows, header `customer_id,name,plan,open_tickets`.
- `.gitignore` -- already ignores `app.db`.
- `pyproject.toml` -- `pythonpath = ["."]` is set (story 1), so tests can import `load_seed`.
- `triage_schema.py`, `tests/test_triage_schema.py` -- story 1; do not change.

## Tasks & Acceptance

**Execution:**
- [x] `load_seed.py` -- add `load_seed(db_path=<repo>/app.db, seed_dir=<repo>/seed) -> dict[str, int]` returning the row count per table, and a `__main__` that runs it and prints the counts. Read CSVs with `csv.DictReader` (UTF-8), check each header, then drop, recreate and fill both tables in one transaction -- so reruns are idempotent and a bad run changes nothing.
- [x] `tests/test_load_seed.py` -- one test per I/O matrix row, each against a temp database (and a temp seed dir for the missing/wrong-header rows); the MCP read-back test calls `get_ticket` and `get_customer_history` from the path-loaded server -- proves CAP-2 and CAP-3 without touching the real `app.db`.

### Review Findings

Code review of `main...story/Jyothi-1.2` (2026-09-26).

- [x] [Review][Patch] Reject a seed CSV with a header but no data rows (decided: fail the load, leave `app.db` unchanged) [load_seed.py:27]
- [x] [Review][Patch] No test that a CSV with a byte-order mark still loads [load_seed.py:27]
- [x] [Review][Patch] Test helper `csv_rows` decodes differently from the loader (`utf-8` vs `utf-8-sig`, blank lines) [tests/test_load_seed.py:27]
- [x] [Review][Patch] No test that `seed/` is unchanged after a load [tests/test_load_seed.py:44]
- [x] [Review][Patch] `epic-1-context.md` still lists route pairing, rationale strictness and `open_tickets` as open, and says "one-sentence" rationale [_bmad-output/implementation-artifacts/epic-1-context.md:38]
- [x] [Review][Defer] `app.db-journal` is not git-ignored [.gitignore] — deferred: only left behind if a load is killed mid-write; the one-line `.gitignore` change is outside this story (AGENTS.md: say so instead of doing it).

Rejected:
- Rows with an empty ID load silently — low: the seed has none and is read-only; fix adds a guard.
- Unreadable / non-UTF-8 / malformed CSV ends in a traceback — carried from triage log #10.
- `unlink` of a new `app.db` can raise and hide the original error — low: needs another process to lock a file created milliseconds earlier; fix adds a guard.
- Short/long-row test's expected line number breaks with extra trailing newlines — low: seed files are read-only and end with one newline; tests pass.
- Story marked `done` / `review_loop_iteration: 0` / Implementation Notes omit the patches — false: the build workflow sets `done`, the counter only counts loopbacks, and the patches are in the triage log; nothing is merged.
- MCP read-back test checks only some fields — false: it asserts everything the matrix row requires.
- Command-line exit code not tested as a script — carried from triage log #12.
- `utf-8-sig` differs from "UTF-8" in the task — false: a superset that only drops a leading byte-order mark.
- Deleting a new `app.db` after a failed first run goes beyond the spec — false: it only applies with no previous database and keeps the constraint.

**Acceptance Criteria:**
- Given the repo after this story, when `uv run pytest` runs, then every test (story 1's included) passes with no network and no API keys set.
- Given `uv run python load_seed.py` has run twice, when `app.db` is queried, then `tickets` has 24 rows and `customers` has 20, and `git status` shows no change under `seed/` and no tracked `app.db`.

## Implementation Notes

- `main()` reads the module-level `DEFAULT_DB_PATH` and `DEFAULT_SEED_DIR` so tests can point it at temp paths; there is no command-line option for other paths.
- Both CSVs are read and header-checked before the database is opened, so a missing file or bad header never creates `app.db`.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Route | Evidence |
|---|---|---|---|---|---|
| 1 | edge-case, blind, verification-gap | Short or long CSV rows load silently (NULLs / dropped fields) | medium | patch | Reproduced: `C-99,Short` loaded as `('C-99','Short',None,None)`; breaks "every CSV row lands byte-for-byte". |
| 2 | edge-case, blind | Failed first run leaves an empty `app.db` | medium | patch | Reproduced: DB error with no prior file left `app.db` with no tables; MCP then says "no such table" instead of "app.db not found". |
| 3 | edge-case, blind | `main()` lets `sqlite3.Error` escape as a traceback | low | patch | Confirmed: only `SeedError` is caught. Direct correction. |
| 4 | edge-case, blind | CSV with a byte-order mark fails the header check | low | patch | Confirmed: `utf-8` keeps `﻿` in the first header name. One-word fix (`utf-8-sig`). |
| 5 | edge-case, blind | Explicit rollback can mask the original error | low | patch | `closing()` with `autocommit=False` already rolls back on close; fix is a deletion. |
| 6 | verification-gap | No wrong-header case with an extra column | low | patch | Confirmed: a subset check would pass both existing cases. |
| 7 | blind | Wrong-header test doesn't prove the expected list is named | low | patch | Confirmed: bad headers already contain most expected names. |
| 8 | blind | "Nothing created" tested only for missing `tickets.csv` | low | patch | Confirmed: single case. Direct parametrisation. |
| 9 | blind | Test connections never closed | low | patch | Confirmed: `with sqlite3.connect()` commits, doesn't close. Direct fix. |
| 10 | edge-case, blind | Unreadable / non-UTF-8 / malformed CSV ends in a traceback | low | reject | Still exits non-zero; seed is read-only and fixed; fix adds exception-mapping branches. |
| 11 | edge-case, blind | Duplicate IDs load silently; no primary key | low | reject | Seed has no duplicates and is read-only; fix changes the schema definitions. |
| 12 | verification-gap | Script exit code not tested at the command boundary | low | reject | Real gap, but only a hypothetical `sys.exit` removal breaks it; a subprocess test needs copied files and paths. |
| 13 | blind | Rollback test uses a Python-side `ProgrammingError` | false | reject | The test still proves atomicity: switching to `autocommit=True` makes it fail (implementer and verification-gap both confirmed). |
| 14 | blind | A future test could overwrite the real `app.db` | false | reject | No current test calls `load_seed()` without a temp path; guards a state not shown to occur. |
| 15 | blind | Empty CSV reports "has header None" | low | reject | Cosmetic and unlikely with a read-only seed; fix adds a branch. |

## Design Notes

Dropping and recreating both tables inside one transaction is the simplest way to make reruns identical: it also removes rows deleted from a CSV and any hand edits, which an `INSERT OR REPLACE` would keep. SQLite rolls the transaction back on error, so a missing file or bad header leaves the last good load in place. Python's default `sqlite3` mode only opens a transaction before DML, so the `DROP`/`CREATE` must be inside an explicit one: connect with `autocommit=False` (Python 3.12+) or `isolation_level=None` plus `BEGIN`. Headers are checked before any write so that a changed CSV fails loudly instead of loading shifted columns.

## Verification

**Commands:**
- `uv run pytest` -- expected: all tests pass.
- `uv run python load_seed.py` (run twice) -- expected: both runs print 24 tickets and 20 customers.
- `uv run python -c "import sqlite3; c=sqlite3.connect('app.db'); print(c.execute('select count(*) from tickets').fetchone(), c.execute('select count(*) from customers').fetchone())"` -- expected: `(24,) (20,)`.
