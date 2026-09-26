## Deferred from: code review of 1-the-triage-decision-schema (2026-09-26)

- Epic 1 `SPEC.md` CAP-1 still allows any category with any route and asks for a one-sentence rationale, while the story (and code) require the matching route and only a non-empty rationale; its Open Questions still list both as unresolved. Epics 2 and 3 treat SPEC.md as canonical. Update through `/bmad-spec`.
- Commit `984d093 spec: epic1` sits on `story/Jyothi-1.1`, so SPEC.md, stories.yaml and .memlog.md ride along in the story's merge. Merge the spec branch to main first so the story diff holds only story code.
- `customers.open_tickets` storage type (integer vs CSV text) is still an open question in SPEC.md and feeds the Enterprise rule's "3 or more" comparison; settle it in story 2.
- `validate_decision` rejects an already-built `TriageDecision` ("not a JSON object: got TriageDecision"); Epic 2 re-validates the agent's structured output, which LangChain returns as a model instance. Reason for deferring: Epic 2 owns how structured output is re-validated.

## Deferred from: code review of 2-the-seed-loader (2026-09-26)

- `app.db-journal` is not git-ignored. `load_seed.py` writes `app.db` in a rollback-journal transaction, so a load killed mid-write leaves `app.db-journal` in the repo root, where `git add -A` would pick it up. Fix: add `app.db-*` to `.gitignore` (outside story 2's scope).

## Deferred from: build review of 1-the-triage-agent (2026-09-26)

- `triage()` starts `mcp/triage_server.py` for every call, and `MultiServerMCPClient.get_tools()` without an explicit session opens a new stdio subprocess per tool call, so each ticket spawns about three Python processes. Fine for one ticket; slow for Epic 3's 20-ticket eval. Consider one `client.session(...)` per run, or letting callers pass tools in.

## Deferred from: code review of 1-the-triage-agent (2026-09-26)

- Story 2.1's live verification is incomplete. `PROVIDER=groq run_agent.py T-1042` has never passed: Groq rejected the configured `GROQ_API_KEY` (401). The live Gemini runs of T-1042 and T-1099 predate the review fixes (the `_check_lookups` guard). Nobody has inspected whether the autologged MCP tool spans sit under the `triage` span in `mlflow.db` with `get_ticket` before `get_customer_history` (CAP-3's success signal). Needs a valid Groq key and the user's go-ahead for live model calls.
