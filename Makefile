VENV ?= $(CURDIR)/.venv
PYTHON ?= $(VENV)/bin/python
ENV_FILE ?= $(CURDIR)/.env
HOST ?= 127.0.0.1
PORT ?= 8000

export PATH := $(VENV)/bin:$(PATH)

DOTENV = $(PYTHON) -m dotenv -f $(ENV_FILE) run --

.DEFAULT_GOAL := help

.PHONY: help install check-env migrate revision seed user dev test run clean

help:
	@printf '%s\n' \
		'Wiki Parchino backend commands:' \
		'  make install              Create .venv and install development dependencies' \
		'  make migrate              Apply all database migrations' \
		'  make revision MESSAGE=""  Generate a migration after model changes' \
		'  make seed                 Load demo users and content' \
		'  make user                 Interactively create or update a fixed account' \
		'  make dev                  Start the development API server' \
		'  make test                 Run the complete backend test suite' \
		'  make run CMD="<command>"  Run any command with variables from .env' \
		'  make clean                Remove reproducible caches and build output' \
		'' \
		'Overrides: ENV_FILE=<path> HOST=<host> PORT=<port>'

$(PYTHON):
	python3 -m venv $(VENV)

install: $(PYTHON)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

check-env:
	@test -f "$(ENV_FILE)" || { \
		echo "Missing environment file: $(ENV_FILE)"; \
		echo "Create it with: cp .env.example .env"; \
		exit 1; \
	}

migrate: check-env
	$(DOTENV) $(PYTHON) -m alembic upgrade head

revision: check-env
	@test -n "$(MESSAGE)" || { echo 'Usage: make revision MESSAGE="describe the schema change"'; exit 1; }
	$(DOTENV) $(PYTHON) -m alembic revision --autogenerate -m "$(MESSAGE)"

seed: migrate
	$(DOTENV) $(PYTHON) -m app.seed

user: migrate
	$(DOTENV) $(PYTHON) -m app.manage_users

dev: check-env
	$(DOTENV) $(PYTHON) -m uvicorn app.main:app --reload --host $(HOST) --port $(PORT)

test: check-env
	$(DOTENV) $(PYTHON) -m pytest

run: check-env
	@test -n "$(CMD)" || { echo 'Usage: make run CMD="<command>"'; exit 1; }
	$(DOTENV) $(CMD)

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist htmlcov
	rm -f .coverage .coverage.* coverage.xml
	find app alembic tests -type d -name __pycache__ -prune -exec rm -rf {} +
	find app alembic tests -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
	find . -maxdepth 1 -type d -name '*.egg-info' -exec rm -rf {} +
