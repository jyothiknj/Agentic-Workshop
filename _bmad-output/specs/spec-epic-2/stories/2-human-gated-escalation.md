---
title: 'Human-gated escalation'
type: 'feature'
created: '2026-09-26'
status: 'done'
baseline_commit: 'fe1b0e8091b93f98c3301c9bb58341c519077d59'
route: 'dispatch'
review_loop_iteration: 0
context: ['{project-root}/_bmad-output/specs/spec-epic-2/SPEC.md', '{project-root}/_bmad-output/specs/spec-epic-2/stories/1-the-triage-agent.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The policy says to escalate P1 tickets from Enterprise customers to a person, with their approval, but the agent has no escalation tool and its prompt says so (Epic 2 CAP-5).

**Approach:** Add a local `escalate_to_human` tool gated by LangChain's `HumanInTheLoopMiddleware`: when the model calls it, the run pauses, an approver answers yes or no, and `triage()` resumes the run until it has a decision. `run_agent.py` asks at the terminal; other callers (Epic 3's eval) pass their own approver.

## Boundaries & Constraints

**Always:** `escalate_to_human(ticket_id, reason)` is defined in `agent.py` (not in `mcp/triage_server.py`) and is always interrupted before it runs, with only `approve` and `reject` allowed. It runs only on an explicit yes; a no rejects it and the run still returns the decision. `triage(ticket_id, approve=None) -> dict` still returns the four-key `TriageDecision` dump, never an escalation field. `approve` is a callable taking the escalation request (ticket ID, reason) and returning `True` to escalate; the default asks at the terminal. The terminal prompt names the ticket and the reason; only `y` or `yes` (any case) means yes — anything else, an empty answer or end of input means no. The agent's instructions replace story 2.1's "no escalation tool" line with: when the final priority is P1 and the customer is on the Enterprise plan, call `escalate_to_human` before returning the decision, and don't retry after a rejection. Story 2.1's lookup check and one-retry rule still apply.

**Decisions:**
- Approved escalation does nothing outside the run: the tool returns a confirmation message, and the escalation is visible in the trace. No email, ticket update or file write.
- `run_agent.py` prints the four-key decision JSON as today, then, only when escalation was asked, one more line: `Escalated to a person: yes` or `Escalated to a person: no (declined)`. Output for tickets that don't escalate is unchanged.
- `triage()` checks for a pending approval before reading the decision, so an escalation sent in the same model turn as the decision is still asked about.

**Never:** Escalate without a yes. Change `mcp/triage_server.py`, `triage_schema.py`, `TRIAGE_POLICY.md`, `seed/`, or the MLflow lines in `run_agent.py`. Add dependencies. Network or keys in `uv run pytest`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Approved | Model calls `escalate_to_human` for a P1 Enterprise ticket; approver says yes | Tool runs once; decision returned | N/A |
| Declined | Same; approver says no | Tool never runs; model is told it was rejected; decision returned | N/A |
| No escalation | T-1042 script (P2) | Approver never called; decision returned | N/A |
| Same-turn escalation | Escalation and decision in one model message | Approver still asked before `triage()` returns | N/A |
| Terminal answers | `y`, `Yes`, `n`, empty, end of input | Only `y` / `Yes` escalate | Non-yes is no |
| Live escalation | `run_agent.py T-1044` (C-91, Enterprise, 3 open) | Pauses with a yes/no prompt; prints the P1 decision, then `Escalated to a person: yes` or `no (declined)` | N/A |

</frozen-after-approval>

## Code Map

- `agent.py` -- `AGENT_INSTRUCTIONS` (replace the no-escalation paragraph), `build_agent` (add the tool, the middleware and a checkpointer), `triage`/`_run` (resume loop). `_StopOnMissingTicket` and `_check_lookups` stay; `_check_lookups` ignores `escalate_to_human` calls.
- Middleware (langchain 1.4.2): `from langchain.agents.middleware import HumanInTheLoopMiddleware`; `interrupt_on={"escalate_to_human": {"allowed_decisions": ["approve", "reject"], "description": ...}}`. Needs a checkpointer: `InMemorySaver` from `langgraph.checkpoint.memory`, with `config={"configurable": {"thread_id": <new per triage() call>}}` on every call. A paused `ainvoke` returns `__interrupt__` (list; `[0].value["action_requests"]` has `name`, `args`, `description`); resume with `Command(resume={"decisions": [{"type": "approve"}]})` or `{"type": "reject", "message": ...}` — one decision per request. Middleware order doesn't matter; after a reject the model gets an error `ToolMessage` and still returns its decision; `structured_response` is present after resume. If a paused result already has `structured_response`, the interrupt must still be handled first.
- `InMemorySaver` logs "Deserializing unregistered type triage_schema.TriageDecision"; harmless in this version.
- `run_agent.py` -- may change except its MLflow lines; passes a terminal approver.
- `tests/test_agent.py` -- reuse `ScriptedModel`, `script`, `TOOLS`, `run`; replace `test_system_prompt_says_no_escalation_tool`.
- Tickets that should escalate: T-1044 (C-91), T-1048 (C-05), T-1057 (C-66), all Enterprise with 3+ open tickets and labelled P1. Epic 3's eval calls `triage()` unattended and auto-approves via `approve`.

## Tasks & Acceptance

**Execution:**
- [x] `agent.py` -- add `escalate_to_human`, the `HumanInTheLoopMiddleware`, a per-call checkpointer and thread ID, the `approve` parameter with a terminal default, and a resume loop in `_run`; update `AGENT_INSTRUCTIONS` -- implements CAP-5 behind story 2.1's seams.
- [x] `run_agent.py` -- pass a terminal approver that records the answer, and print the `Escalated to a person: ...` line after the decision only when it was asked -- outside the MLflow lines.
- [x] `tests/test_agent.py` -- one test per offline matrix row with the scripted model; the terminal-answer test monkeypatches `input` -- live row is covered by Verification.

### Review Findings

Code review of `main...story/Jyothi-2.2` (2026-09-26).

- [x] [Review][Patch] Wrong-ticket check compares IDs exactly, so `t-1044` or `T-1044 ` silently rejects a real escalation and no one is asked [agent.py:_decide]
- [x] [Review][Patch] Resume loop has no cap; each resume gets a fresh recursion limit, so a model that keeps escalating never stops [agent.py:_run]
- [x] [Review][Patch] `run_agent.py`'s approver wrapper is only tested for its printed line, not that its return value drives the real approval path [tests/test_agent.py:test_run_agent_output]
- [x] [Review][Patch] Escalation-prompt test matches "do not retry" anywhere (the P1 + Enterprise condition was already asserted; that half of the finding was false) [tests/test_agent.py:test_system_prompt_has_escalation_rule]
- [x] [Review][Defer] Live escalation row never run: whether Gemini calls `escalate_to_human` for T-1044 is untested [run_agent.py] — deferred: needs the user's key and an interactive terminal (`! uv run python run_agent.py T-1044`).

Rejected:
- Escalations rejected in code aren't shown in CLI output — low: with the ID normalised these are misbehaviour cases, recorded in the trace; fix adds output paths.
- Terminal prompt goes to stdout next to the JSON — false as a new defect: an escalated run's stdout already has the non-JSON `Escalated to a person` line by the user's decision.
- Escalation with a missing or empty reason can be approved, then fails validation while "yes" prints; triage-log #11 claim — low: the tool schema requires `reason`; fix adds a guard; the log claim would need editing this spec.
- Escalation before lookups or for a non-P1 decision — carried from triage log #7 and #12.
- An approver that raises aborts the run — low: a loud failure; no decision is returned.
- Only `interrupts[0]` is answered — false: the middleware raises one interrupt per model turn (triage log #4).
- Approval prompt lacks priority and plan facts — the request shape (ticket ID, reason) is set by this spec.
- Human wait time counted in the MLflow span — low: only interactive runs wait; Epic 3 auto-approves.
- Middleware `description` unused; action name unchecked — carried from triage log #8.
- A second request is rejected after an approval too — false as a defect: the escalation still runs once.
- "Yes" line reports the answer, not the tool run — carried from triage log #11.
- `langgraph` imported without being declared — false: it ships with `langchain`, and the Code Map names these imports.
- `review_loop_iteration: 0` after a review — false: the counter only counts loopbacks.

**Acceptance Criteria:**
- Given the repo after this story, when `uv run pytest` runs with no network and no keys, then every test passes, including story 2.1's.
- Given any run, when the approver never answers yes, then `escalate_to_human` never executes.

## Implementation Notes

- `approve` receives the tool's args as a dict, `{"ticket_id": ..., "reason": ...}`; only a return value that `is True` approves. Any other value, including truthy ones like `"yes"`, is a reject.
- `build_agent` appends `escalate_to_human` to the given tools and gives each built agent its own `InMemorySaver`. `_run` makes a fresh `thread_id` per call and loops on `__interrupt__` before it reads `structured_response`.
- `run_agent.py` wraps `ask_at_terminal` so it can record answers. The extra line prints `yes` if any answer was yes. The MLflow setup lines are unchanged; only the `triage(...)` call inside the span gained the `approve` argument.
- The live row (`run_agent.py T-1044`) has not been run yet: it needs a key and the user's go-ahead.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Route | Evidence |
|---|---|---|---|---|---|
| 1 | blind, edge-case | Escalation `ticket_id` not checked against the ticket being triaged | medium | patch | `_decide` passes model args straight to the approver; ticket text is untrusted, so the person can be asked about a different ticket. |
| 2 | blind, edge-case | Terminal prompt prints the model-written reason raw | medium | patch | Newlines or ANSI escapes in `reason` can fake or hide the question the person answers. |
| 3 | blind, edge-case, verification-gap | Approver asked on every escalation: no code-side "don't retry", and two escalations in one turn untested | medium | patch | The resume loop asks each time; only the prompt says not to retry. Fix: ask at most once per run. |
| 4 | blind, verification-gap | `len(interrupts) > 1` resume branch untested and unreachable | low | patch | `HumanInTheLoopMiddleware` raises one interrupt per model turn (`human_in_the_loop.py:481`); removing it is a deletion. |
| 5 | blind | Default approver can block on a non-TTY stdin | low | reject | EOF counts as no; Epic 3 passes its own approver per its spec; fix adds a branch. |
| 6 | blind | Synchronous approver blocks the event loop | low | reject | No async approver is needed yet; fix changes the approver contract. |
| 7 | blind, edge-case | P1 + Enterprise rule not checked in code (missed or unneeded escalation) | false | reject | Story 2.1's frozen decision leaves the policy to the model; the fix would edit the spec. Epic 3 measures escalations. |
| 8 | blind | `_decide` ignores the action name; empty `action_requests` | low | reject | Only one tool is gated; guards a state not shown to occur. |
| 9 | blind | Approval answer not recorded as span data | low | reject | The spec keeps escalation visible through the tool call in the trace; Epic 3 counts via its own approver. |
| 10 | blind | Story file untracked; `stories.yaml` and sprint status not updated | false | reject | The story file is committed at the end of the build; there is no sprint-status file. |
| 11 | blind | Output line reports the answer, not whether the tool ran | low | reject | After #1 and #3 an approved request always runs; the tool only returns a message. |
| 12 | edge-case | Escalation approved, then the run fails, so no decision and no output line | low | reject | Needs a later schema or lookup failure after escalation; fix adds ordering logic. |
| 13 | verification-gap | `any(answers)` in `run_agent.py` untested with several answers | low | reject | After #3 the approver is asked at most once per run. |

## Verification

**Commands:**
- `uv run pytest` -- expected: all tests pass.
- `uv run python run_agent.py T-1044` (needs `GEMINI_API_KEY`; ask the user before running) -- expected: a yes/no prompt, then a `P1` decision.
