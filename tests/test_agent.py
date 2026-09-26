"""Offline tests for the triage agent: scripted fake model, fake tools, no keys."""

import asyncio
import json

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import ToolException, tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

import agent
from agent import (
    MissingAPIKeyError,
    StructuredOutputFailedError,
    TicketNotFoundError,
    build_agent,
    make_model,
    system_prompt,
)

VALID = {
    "category": "billing",
    "priority": "P2",
    "route": "billing-team",
    "rationale": "Double charge puts money at stake, so P2 (Enterprise rule not met).",
}
BAD = {**VALID, "route": "bug-team"}  # route does not match category


class ScriptedModel(FakeMessagesListChatModel):
    """A fake chat model that accepts tool binding and replays scripted messages."""

    def bind_tools(self, tools, **kwargs):
        return self


calls: list[tuple[str, dict]] = []


@tool
def get_ticket(ticket_id: str) -> dict:
    """Return one support ticket by its ID."""
    calls.append(("get_ticket", {"ticket_id": ticket_id}))
    if ticket_id != "T-1042":
        raise ToolException(f"No ticket with ID {ticket_id}")
    return {"ticket_id": "T-1042", "customer_id": "C-77", "created_at": "x", "text": "Charged twice"}


get_ticket.handle_tool_error = True


@tool
def get_customer_history(customer_id: str) -> dict:
    """Return a customer's plan and open ticket count."""
    calls.append(("get_customer_history", {"customer_id": customer_id}))
    if customer_id == "C-BROKEN":
        raise ToolException(f"No customer with ID {customer_id}")
    return {"customer_id": customer_id, "name": "Northwind", "plan": "Enterprise",
            "open_tickets": "2", "ticket_ids": ["T-1042"]}


get_customer_history.handle_tool_error = True

TOOLS = [get_ticket, get_customer_history]


def call(name, args, i):
    return {"name": name, "args": args, "id": f"call-{i}", "type": "tool_call"}


def script(*outputs, ticket_id="T-1042", customer_id="C-77", lookups=True):
    """Lookup calls, then one TriageDecision output call per entry in ``outputs``."""
    msgs = []
    if lookups:
        msgs = [
            AIMessage(content="", tool_calls=[call("get_ticket", {"ticket_id": ticket_id}, 0)]),
            AIMessage(content="", tool_calls=[call("get_customer_history", {"customer_id": customer_id}, 1)]),
        ]
    for i, out in enumerate(outputs, start=2):
        msgs.append(AIMessage(content="", tool_calls=[call("TriageDecision", out, i)]))
    return ScriptedModel(responses=msgs)


def run(model, ticket_id="T-1042", tools=TOOLS):
    calls.clear()
    return asyncio.run(agent._run(build_agent(model, tools), ticket_id))


@pytest.fixture
def clean_env(monkeypatch):
    for var in ("PROVIDER", "MODEL", "GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_groq_switch(clean_env):
    clean_env.setenv("PROVIDER", "groq")
    clean_env.setenv("GROQ_API_KEY", "test-groq-key")
    model = make_model()
    assert isinstance(model, ChatGroq)
    assert model.model_name == "openai/gpt-oss-120b"
    assert model.groq_api_key.get_secret_value() == "test-groq-key"


def test_gemini_default(clean_env):
    clean_env.setenv("MODEL", "x")
    clean_env.setenv("GEMINI_API_KEY", "test-gemini-key")
    model = make_model()
    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model.removeprefix("models/") == "x"
    assert model.google_api_key.get_secret_value() == "test-gemini-key"


def test_gemini_default_model_name(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "test-gemini-key")
    assert make_model().model.removeprefix("models/") == "gemini-3.8-flash"


@pytest.mark.parametrize(("provider", "var"), [(None, "GEMINI_API_KEY"), ("groq", "GROQ_API_KEY")])
def test_missing_key(clean_env, provider, var):
    if provider:
        clean_env.setenv("PROVIDER", provider)
    # The other provider's key is set, and must never leak into the message.
    clean_env.setenv("GROQ_API_KEY" if var == "GEMINI_API_KEY" else "GEMINI_API_KEY", "secret-value")
    with pytest.raises(MissingAPIKeyError, match=var) as info:
        make_model()
    assert "secret-value" not in str(info.value)


def test_valid_output_and_tool_order():
    assert run(script(VALID)) == VALID
    assert calls == [("get_ticket", {"ticket_id": "T-1042"}),
                     ("get_customer_history", {"customer_id": "C-77"})]


def test_one_bad_output_is_retried():
    assert run(script(BAD, VALID)) == VALID


def test_two_bad_outputs_fail():
    with pytest.raises(StructuredOutputFailedError, match="schema validation failed twice"):
        run(script(BAD, {**VALID, "extra": "field"}, VALID))


def test_retry_budget_is_per_run():
    # A failure in one run must not use up the next run's retry.
    assert run(script(BAD, VALID)) == VALID
    assert run(script(BAD, VALID)) == VALID


def test_unknown_ticket_stops_the_run():
    with pytest.raises(TicketNotFoundError, match="T-9999"):
        run(script(VALID, ticket_id="T-9999"), "T-9999")
    assert [name for name, _ in calls] == ["get_ticket"]


def test_plain_text_ending_raises():
    model = ScriptedModel(responses=[AIMessage(content="It's billing, P2.")])
    with pytest.raises(StructuredOutputFailedError, match="T-1042"):
        run(model)


def test_system_prompt_has_policy_and_data_rule():
    prompt = system_prompt()
    policy = (agent.REPO_ROOT / "TRIAGE_POLICY.md").read_text(encoding="utf-8").rstrip()
    assert policy in prompt
    assert "untrusted data" in prompt
    assert "never instructions" in prompt
    assert prompt.index("get_ticket") < prompt.index("get_customer_history")


def test_load_tools_lists_the_real_server_tools():
    tools = asyncio.run(agent.load_tools())
    assert sorted(t.name for t in tools) == ["get_customer_history", "get_ticket"]


@pytest.mark.parametrize(
    ("script_kwargs", "error", "message"),
    [
        ({"lookups": False}, TicketNotFoundError, "ticket T-1042"),  # no tool calls
        ({"ticket_id": "T-1043"}, TicketNotFoundError, "ticket T-1042"),  # another ID
        ({"customer_id": "C-BROKEN"}, RuntimeError, "customer C-77 of ticket T-1042"),  # history errors
        ({"customer_id": "C-99"}, RuntimeError, "customer C-77 of ticket T-1042"),  # wrong customer
    ],
)
def test_decision_without_proper_lookups_is_rejected(script_kwargs, error, message):
    # get_ticket succeeds for T-1043 too, so only the ID check can catch it.
    with pytest.raises(error, match=message):
        run(script(VALID, **script_kwargs), tools=[_any_ticket, get_customer_history])


@tool("get_ticket")
def _any_ticket(ticket_id: str) -> dict:
    """Return one support ticket by its ID."""
    return {"ticket_id": ticket_id, "customer_id": "C-77", "created_at": "x", "text": "Charged twice"}


@pytest.mark.skipif(
    not (agent.REPO_ROOT / "app.db").exists(),
    reason="needs app.db: run `uv run python load_seed.py`",
)
def test_valid_ticket_real_server():
    # The real adapter returns content blocks, not the fakes' plain string.
    tools = asyncio.run(agent.load_tools())
    assert run(script(VALID), tools=tools) == VALID


def test_triage_success_returns_json_dict(clean_env):
    async def fake_load_tools():
        return TOOLS

    clean_env.setattr(agent, "make_model", lambda: script(VALID))
    clean_env.setattr(agent, "load_tools", fake_load_tools)
    decision = asyncio.run(agent.triage("T-1042"))
    assert type(decision) is dict
    assert json.loads(json.dumps(decision)) == VALID


def test_system_prompt_has_escalation_rule():
    prompt = " ".join(system_prompt().split())
    assert "no escalate_to_human tool" not in prompt
    assert (
        "When the final priority is P1 and the customer is on the Enterprise plan, "
        "call `escalate_to_human`" in prompt
    )
    assert "if it is rejected, do not retry it" in prompt
    assert prompt.index("get_ticket") < prompt.index("get_customer_history")


def test_unknown_ticket_real_server():
    tools = asyncio.run(agent.load_tools())
    with pytest.raises(TicketNotFoundError, match="T-9999"):
        run(script(VALID, ticket_id="T-9999"), "T-9999", tools=tools)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("openai", None), (" Groq ", ChatGroq), ("gemini", ChatGoogleGenerativeAI)],
)
def test_provider_selection(clean_env, provider, expected):
    clean_env.setenv("PROVIDER", provider)
    clean_env.setenv("GEMINI_API_KEY", "k")
    clean_env.setenv("GROQ_API_KEY", "k")
    if expected is None:
        with pytest.raises(ValueError, match="Unknown PROVIDER"):
            make_model()
    else:
        assert isinstance(make_model(), expected)


@pytest.mark.parametrize("var", ["MODEL", "GEMINI_API_KEY"])
def test_whitespace_counts_as_unset(clean_env, var):
    clean_env.setenv("GEMINI_API_KEY", "k")
    clean_env.setenv(var, "   ")
    if var == "MODEL":
        assert make_model().model.removeprefix("models/") == "gemini-3.8-flash"
    else:
        with pytest.raises(MissingAPIKeyError, match="GEMINI_API_KEY"):
            make_model()


def test_triage_missing_key_skips_tools(clean_env):
    loaded = []

    async def fake_load_tools():
        loaded.append(True)
        return TOOLS

    clean_env.setattr(agent, "load_tools", fake_load_tools)
    with pytest.raises(MissingAPIKeyError, match="GEMINI_API_KEY"):
        asyncio.run(agent.triage("T-1042"))
    assert loaded == []


# --- Story 2.2: human-gated escalation ---------------------------------------

P1 = {
    "category": "billing",
    "priority": "P1",
    "route": "billing-team",
    "rationale": "Money at stake and Enterprise with 3+ open tickets, so bumped to P1.",
}
ESCALATION = {"ticket_id": "T-1042", "reason": "P1 ticket from an Enterprise customer"}


class RecordingModel(ScriptedModel):
    """A scripted model that also records the messages it was shown."""

    seen: list = []

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


def escalation_script(same_turn=False):
    """Lookups, then escalate_to_human and a P1 decision (together or in turn)."""
    lookups = script(P1).responses[:2]
    esc = call("escalate_to_human", ESCALATION, 5)
    out = call("TriageDecision", P1, 6)
    if same_turn:
        tail = [AIMessage(content="", tool_calls=[esc, out])]
    else:
        tail = [AIMessage(content="", tool_calls=[esc]), AIMessage(content="", tool_calls=[out])]
    return RecordingModel(responses=lookups + tail, seen=[])


@pytest.fixture
def escalations(monkeypatch):
    """Replace the escalation tool with a spy that records each execution."""
    ran = []
    real = agent.escalate_to_human

    @tool("escalate_to_human")
    def spy(ticket_id: str, reason: str) -> str:
        """Escalate a ticket to a person."""
        ran.append({"ticket_id": ticket_id, "reason": reason})
        return real.invoke({"ticket_id": ticket_id, "reason": reason})

    monkeypatch.setattr(agent, "escalate_to_human", spy)
    return ran


def approver(answer):
    asked = []

    def approve(request):
        asked.append(request)
        return answer

    approve.asked = asked
    return approve


def escalation_results(model):
    """The escalate_to_human tool results the model was shown on its last turn."""
    last = model.seen[-1]
    ids = {tc["id"] for m in last if isinstance(m, AIMessage) for tc in m.tool_calls
           if tc["name"] == "escalate_to_human"}
    return [m for m in last if isinstance(m, ToolMessage) and m.tool_call_id in ids]


def run_escalation(model, approve):
    calls.clear()
    return asyncio.run(agent._run(build_agent(model, TOOLS), "T-1042", approve))


def test_escalation_approved(escalations):
    model, approve = escalation_script(), approver(True)
    assert run_escalation(model, approve) == P1
    assert approve.asked == [ESCALATION]
    assert escalations == [ESCALATION]
    [result] = escalation_results(model)
    assert result.status != "error"
    assert "escalated to a person" in result.text


@pytest.mark.parametrize("answer", [False, None, "yes", 1])
def test_escalation_declined(escalations, answer):
    # Anything but an explicit True is a no.
    model, approve = escalation_script(), approver(answer)
    assert run_escalation(model, approve) == P1
    assert approve.asked == [ESCALATION]
    assert escalations == []
    [result] = escalation_results(model)
    assert result.status == "error"
    assert "declined" in result.text


def test_no_escalation_never_asks(escalations):
    def approve(request):
        raise AssertionError("approver must not be called")

    assert run_escalation(script(VALID), approve) == VALID
    assert escalations == []


@pytest.mark.parametrize("answer", [True, False])
def test_same_turn_escalation_is_still_asked(escalations, answer):
    model, approve = escalation_script(same_turn=True), approver(answer)
    assert run_escalation(model, approve) == P1
    assert approve.asked == [ESCALATION]
    assert escalations == ([ESCALATION] if answer else [])


def custom_escalation_script(*turns):
    """Lookups, then one model turn per entry in ``turns`` (a list of tool calls)."""
    lookups = script(P1).responses[:2]
    tail = [AIMessage(content="", tool_calls=tcs) for tcs in turns]
    return RecordingModel(responses=lookups + tail, seen=[])


def test_escalation_for_another_ticket_is_rejected_without_asking(escalations):
    def approve(request):
        raise AssertionError("approver must not be called")

    other = {**ESCALATION, "ticket_id": "T-9999"}
    model = custom_escalation_script(
        [call("escalate_to_human", other, 5)], [call("TriageDecision", P1, 6)]
    )
    assert run_escalation(model, approve) == P1
    assert escalations == []
    [result] = escalation_results(model)
    assert result.status == "error"
    assert "wrong ticket" in result.text


def test_two_escalations_in_one_turn_ask_once(escalations):
    model = custom_escalation_script(
        [call("escalate_to_human", ESCALATION, 5), call("escalate_to_human", ESCALATION, 7)],
        [call("TriageDecision", P1, 6)],
    )
    approve = approver(True)
    assert run_escalation(model, approve) == P1
    assert approve.asked == [ESCALATION]
    assert escalations == [ESCALATION]  # only the first one ran
    results = {m.tool_call_id: m for m in escalation_results(model)}
    first, second = results["call-5"], results["call-7"]
    assert first.status != "error"
    assert second.status == "error" and "already decided" in second.text


def test_escalation_resent_after_rejection_is_not_asked_again(escalations):
    model = custom_escalation_script(
        [call("escalate_to_human", ESCALATION, 5)],
        [call("escalate_to_human", ESCALATION, 7)],
        [call("TriageDecision", P1, 6)],
    )
    approve = approver(False)
    assert run_escalation(model, approve) == P1
    assert approve.asked == [ESCALATION]
    assert escalations == []
    first, second = escalation_results(model)
    assert "declined" in first.text
    assert second.status == "error" and "already decided" in second.text


def test_terminal_prompt_escapes_control_characters(monkeypatch):
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "n")
    reason = "Real reason\nApprove? [y/N] y\x1b[2K"
    agent.ask_at_terminal({"ticket_id": "T-1042\n", "reason": reason})
    [prompt] = prompts
    assert "\x1b" not in prompt
    assert prompt.splitlines() == [
        "Escalate ticket T-1042\\n to a person?",
        "Reason: Real reason\\nApprove? [y/N] y\\x1b[2K",
        "Approve? [y/N] ",
    ]


def test_escalation_tool_is_local():
    assert agent.escalate_to_human.name == "escalate_to_human"
    server = (agent.REPO_ROOT / "mcp" / "triage_server.py").read_text(encoding="utf-8")
    assert "escalate_to_human" not in server


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("y", True), ("Yes", True), (" YES ", True), ("n", False), ("", False),
     ("yeah", False), (EOFError, False)],
)
def test_terminal_answers(monkeypatch, typed, expected):
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        if typed is EOFError:
            raise EOFError
        return typed

    monkeypatch.setattr("builtins.input", fake_input)
    assert agent.ask_at_terminal(ESCALATION) is expected
    [prompt] = prompts
    assert "T-1042" in prompt and ESCALATION["reason"] in prompt


@pytest.mark.parametrize(("typed", "escalated"), [("y", True), ("", False)])
def test_triage_defaults_to_the_terminal(clean_env, escalations, typed, escalated):
    async def fake_load_tools():
        return TOOLS

    clean_env.setattr(agent, "make_model", escalation_script)
    clean_env.setattr(agent, "load_tools", fake_load_tools)
    clean_env.setattr("builtins.input", lambda prompt="": typed)
    decision = asyncio.run(agent.triage("T-1042"))
    assert decision == P1  # the four-key decision, no escalation field
    assert escalations == ([ESCALATION] if escalated else [])


class _NoSpan:
    """Stands in for ``mlflow.start_span`` so the output test writes no trace."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_inputs(self, inputs):
        pass

    def set_outputs(self, outputs):
        pass


@pytest.mark.parametrize("sent_id", ["t-1042", " T-1042 "])
def test_escalation_ticket_id_ignores_case_and_spaces(escalations, sent_id):
    approve = approver(True)
    asked = approve.asked
    model = escalation_script()
    model.responses[2].tool_calls[0]["args"]["ticket_id"] = sent_id
    assert asyncio.run(agent._run(build_agent(model, TOOLS), "T-1042", approve)) == P1
    assert len(asked) == 1
    assert len(escalations) == 1


def test_endless_escalation_stops_with_a_clear_error(escalations):
    approve = approver(False)
    asked = approve.asked
    lookups = script(P1).responses[:2]
    repeats = [
        AIMessage(content="", tool_calls=[call("escalate_to_human", ESCALATION, 10 + i)])
        for i in range(agent.MAX_RESUMES + 2)
    ]
    model = RecordingModel(responses=lookups + repeats, seen=[])
    with pytest.raises(StructuredOutputFailedError, match="kept requesting escalation"):
        asyncio.run(agent._run(build_agent(model, TOOLS), "T-1042", approve))
    assert len(asked) == 1
    assert escalations == []


def test_run_agent_approval_drives_the_real_path(monkeypatch, tmp_path, capsys, escalations):
    import run_agent

    async def fake_load_tools():
        return TOOLS

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_agent.mlflow, "set_tracking_uri", lambda uri: None)
    monkeypatch.setattr(run_agent.mlflow, "set_experiment", lambda name: None)
    monkeypatch.setattr(run_agent.mlflow.langchain, "autolog", lambda *a, **k: None)
    monkeypatch.setattr(run_agent.mlflow, "start_span", _NoSpan)
    monkeypatch.setattr(run_agent, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(agent, "make_model", escalation_script)
    monkeypatch.setattr(agent, "load_tools", fake_load_tools)
    monkeypatch.setattr(agent, "ask_at_terminal", lambda request: True)
    monkeypatch.setattr("sys.argv", ["run_agent.py", "T-1042"])
    run_agent.main()
    assert escalations == [ESCALATION]  # the wrapper's answer reached _decide
    assert capsys.readouterr().out.strip().splitlines()[-1] == "Escalated to a person: yes"


@pytest.mark.parametrize(
    ("answer", "last_line"),
    [(None, None), (True, "Escalated to a person: yes"),
     (False, "Escalated to a person: no (declined)")],
)
def test_run_agent_output(monkeypatch, tmp_path, capsys, answer, last_line):
    import run_agent

    async def fake_triage(ticket_id, approve=None):
        if answer is not None:
            approve(ESCALATION)
        return P1

    monkeypatch.chdir(tmp_path)  # mlflow.db is created here, not in the repo
    # Keep MLflow's global state (tracking URI, autolog) from leaking into other tests.
    monkeypatch.setattr(run_agent.mlflow, "set_tracking_uri", lambda uri: None)
    monkeypatch.setattr(run_agent.mlflow, "set_experiment", lambda name: None)
    monkeypatch.setattr(run_agent.mlflow.langchain, "autolog", lambda *a, **k: None)
    monkeypatch.setattr(run_agent.mlflow, "start_span", _NoSpan)
    monkeypatch.setattr(run_agent, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(agent, "triage", fake_triage)
    monkeypatch.setattr(agent, "ask_at_terminal", lambda request: answer)
    monkeypatch.setattr("sys.argv", ["run_agent.py", "T-1042"])
    run_agent.main()
    lines = capsys.readouterr().out.strip().splitlines()
    decision_lines = lines if last_line is None else lines[:-1]
    assert json.loads("\n".join(decision_lines)) == P1
    if last_line is not None:
        assert lines[-1] == last_line
