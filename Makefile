COMPOSE := docker compose
COMPOSE_FILES ?= -f docker-compose.yml
PYTHON ?= $(HOME)/.venv/workbench/bin/python
PIP ?= $(HOME)/.venv/workbench/bin/pip
EXCLUDE ?= dcat
WORKBENCH_API_TOKEN ?= change-me

.PHONY: setup ui-setup ui-build ui-test gen-api build up down serve test migrate lint format logs health triage clean

setup:
	python3 -m venv $(HOME)/.venv/workbench
	$(PIP) install -e ".[dev]"
	@echo "Activate with: source ~/.venv/workbench/bin/activate"

ui-setup:
	cd ui && npm install

ui-build:
	cd ui && npm run build

ui-test:
	cd ui && npm run test

gen-api:
	cd ui && npm run gen:api

build: ui-build
	$(COMPOSE) $(COMPOSE_FILES) build

up: build
	$(COMPOSE) $(COMPOSE_FILES) up -d

down:
	$(COMPOSE) $(COMPOSE_FILES) down

serve:
	$(PYTHON) -m workbench

test:
	$(PYTHON) -m pytest tests/ -v --tb=short

migrate:
	$(PYTHON) -m alembic upgrade head

lint:
	$(PYTHON) -m ruff check src/ tests/ scripts/

format:
	$(PYTHON) -m ruff format src/ tests/ scripts/

logs:
	$(PYTHON) scripts/logview.py data/logs --exclude dcat --exclude access --exclude-logger uvicorn.access $(if $(EXCLUDE),--exclude $(EXCLUDE))

health:
	@curl -s http://localhost:8421/health | python3 -m json.tool

triage:
	$(PYTHON) scripts/triage.py --token $(WORKBENCH_API_TOKEN)

clean:
	rm -rf ui/dist .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
