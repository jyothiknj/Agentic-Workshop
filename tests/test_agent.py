"""Offline tests for the triage agent: scripted fake model, fake tools, no keys."""

import asyncio

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
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
