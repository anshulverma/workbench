# Step 1: Docker Stack

Parent spec: [workbench-design.md](../2026-05-21-workbench-design.md)

## Goal

A docker-compose stack that starts the API server and PostgreSQL database with a single command. The server boots, connects to the database, and responds to a health check.

## Files to Create

```
server/
  Dockerfile
  docker-compose.yml
  requirements.txt
  main.py              -- FastAPI app with /health endpoint only
  config.py            -- configuration from environment variables
```

## Dockerfile

- Base image: `python:3.12-slim`
- Install dependencies from `requirements.txt`
- Copy `server/` into the image
- Expose port 8000
- Entrypoint: `uvicorn main:app --host 0.0.0.0 --port 8000`

## docker-compose.yml

Three services:

```yaml
services:
  workbench-server:
    build: ./server
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://workbench:workbench@workbench-db:5432/workbench
      - SECRET_KEY=${SECRET_KEY:-dev-secret-change-me}
    depends_on:
      workbench-db:
        condition: service_healthy

  workbench-db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=workbench
      - POSTGRES_PASSWORD=workbench
      - POSTGRES_DB=workbench
    volumes:
      - workbench-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U workbench"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  workbench-data:
```

The optional `workbench-worker` service is not needed yet — the scheduler will run in-process with the server initially.

## requirements.txt

```
fastapi>=0.115
uvicorn[standard]>=0.30
sqlalchemy[asyncio]>=2.0
asyncpg>=0.30
alembic>=1.14
pydantic>=2.0
pydantic-settings>=2.0
```

## config.py

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://workbench:workbench@localhost:5432/workbench"
    secret_key: str = "dev-secret-change-me"
    debug: bool = False

    class Config:
        env_prefix = ""
```

## main.py

Minimal FastAPI app:

```python
from fastapi import FastAPI

app = FastAPI(title="Workbench", version="0.1.0")

@app.get("/health")
async def health():
    return {"status": "ok"}
```

Database connection setup will be added in Step 2 when models are created.

## Implementation Plan

_To be finalized._

## Acceptance Criteria

1. `docker-compose up --build` starts both containers without errors
2. `curl http://localhost:8000/health` returns `{"status": "ok"}`
3. PostgreSQL is accessible from the server container
4. `docker-compose down` stops everything cleanly
5. Data persists across restarts via the named volume
