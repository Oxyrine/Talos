.PHONY: demo eval test test-all lint

demo:
	uv run talos demo

eval:
	uv run talos eval

test:
	uv run pytest -m "not exasol"

test-all:
	uv run pytest

lint:
	uv run ruff check .
