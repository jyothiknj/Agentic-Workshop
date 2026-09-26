"""Triage one support ticket with the agent and print the decision.

Usage: uv run python run_agent.py T-1042
"""

import asyncio
import json
import sys

import mlflow
from dotenv import load_dotenv


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: uv run python run_agent.py <ticket_id>")
    ticket_id = sys.argv[1]

    load_dotenv()
    mlflow.set_tracking_uri("sqlite:///mlflow.db")
    mlflow.set_experiment("triage-agent")
    mlflow.langchain.autolog()

    try:
        from agent import ask_at_terminal, triage
    except ImportError:
        raise SystemExit("The agent isn't built yet. That's Epic 2: _bmad-output/specs/spec-epic-2/SPEC.md")

    answers: list[bool] = []

    def approve(request: dict) -> bool:
        answer = ask_at_terminal(request)
        answers.append(answer)
        return answer

    with mlflow.start_span(name="triage", span_type="AGENT") as span:
        span.set_inputs({"ticket_id": ticket_id})
        decision = asyncio.run(triage(ticket_id, approve))
        span.set_outputs(decision)
    print(json.dumps(decision, indent=2))
    if answers:
        print(f"Escalated to a person: {'yes' if any(answers) else 'no (declined)'}")


if __name__ == "__main__":
    main()
