COMPOSE := podman-compose
PROXY := HTTP_PROXY=http://fwdproxy:8080 HTTPS_PROXY=http://fwdproxy:8080

# Detect if workbench-meta overlay exists
META_DIR := $(HOME)/workspace/workbench-meta
COMPOSE_FILES := -f docker-compose.yml
ifneq (,$(wildcard $(META_DIR)/docker-compose.override.yml))
  COMPOSE_FILES += -f $(META_DIR)/docker-compose.override.yml
endif

.PHONY: build up down logs health triage setup test migrate

build:
	$(PROXY) $(COMPOSE) $(COMPOSE_FILES) build \
		--build-arg HTTP_PROXY=http://fwdproxy:8080 \
		--build-arg HTTPS_PROXY=http://fwdproxy:8080

up: build
	$(PROXY) $(COMPOSE) $(COMPOSE_FILES) up -d

down:
	$(COMPOSE) $(COMPOSE_FILES) down

logs:
	$(COMPOSE) $(COMPOSE_FILES) logs -f

health:
	@curl -s http://localhost:8421/health | python3 -m json.tool

triage:
	workbench triage --token $${WORKBENCH_API_TOKEN:-change-me}

setup:
	python3 -m venv $(HOME)/.venv/workbench
	$(PROXY) $(HOME)/.venv/workbench/bin/pip install -e ".[dev]" podman-compose
	@if [ -d "$(META_DIR)" ]; then \
		echo "Installing workbench-meta..."; \
		$(PROXY) $(HOME)/.venv/workbench/bin/pip install -e $(META_DIR); \
	fi
	@echo "Activate with: source ~/.venv/workbench/bin/activate"

test:
	python -m pytest tests/ -v --tb=short

migrate:
	alembic upgrade head
