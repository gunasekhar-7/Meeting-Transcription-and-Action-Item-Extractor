ifeq ($(OS),Windows_NT)
PY := .venv/Scripts/python.exe
else
PY := .venv/bin/python
endif

.PHONY: setup up down logs migrate test lint typecheck fmt eval verify

setup:
	python -m venv .venv
	uv pip install --python $(PY) -e "./backend[dev]"
	uv pip install --python $(PY) -e "./frontend[dev]"

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api worker

migrate:
	cd backend && ../$(PY) -m alembic upgrade head

test:
	cd backend && ../$(PY) -m pytest
	cd frontend && ../$(PY) -m pytest

lint:
	cd backend && ../$(PY) -m ruff check app tests
	cd frontend && ../$(PY) -m ruff check streamlit_app tests

typecheck:
	cd backend && ../$(PY) -m mypy app

fmt:
	cd backend && ../$(PY) -m ruff format app tests
	cd frontend && ../$(PY) -m ruff format streamlit_app tests

eval:
	$(PY) eval/scripts/run_pipeline_eval.py

verify: lint typecheck test eval
