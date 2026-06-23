# Makefile for ambient-expense-agent

.PHONY: install playground lint test generate-traces grade

install:
	uv sync

playground:
	uv run uvicorn expense_agent.web_service:app --host 127.0.0.1 --port 8080

lint:
	agents-cli lint

test:
	uv run pytest tests/

generate-traces:
	uv run python tests/eval/generate_traces.py

grade:
	agents-cli eval grade --traces artifacts/traces/generated_traces.json --config tests/eval/eval_config.yaml
