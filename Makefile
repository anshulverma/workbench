COMPOSE := docker compose
COMPOSE_FILES ?= -f docker-compose.yml
# Use the venv created by `make setup`; override with `make logs PYTHON=...`.
PYTHON ?= $(HOME)/.venv/workbench/bin/python

.PHONY: build up down logs health triage setup test migrate

build:
	$(COMPOSE) $(COMPOSE_FILES) build

up: build
	$(COMPOSE) $(COMPOSE_FILES) up -d

down:
	$(COMPOSE) $(COMPOSE_FILES) down

logs:
	$(PYTHON) scripts/logview.py data/logs

health:
	@curl -s http://localhost:8421/health | python3 -m json.tool

triage:
	workbench triage --token $${WORKBENCH_API_TOKEN:-change-me}

setup:
	python3 -m venv $(HOME)/.venv/workbench
	$(HOME)/.venv/workbench/bin/pip install -e ".[dev]"
	@echo "Activate with: source ~/.venv/workbench/bin/activate"

test:
	python -m pytest tests/ -v --tb=short

migrate:
	alembic upgrade head
