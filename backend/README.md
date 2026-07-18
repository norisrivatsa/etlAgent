# Kafka Pipeline Architect Agent

Stateful, async FastAPI service for designing, evaluating, deploying, debugging,
and verifying Kafka Connect and ksqlDB pipelines.

## Run

Python 3.12 and MongoDB are required.

```bash
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload
```

OpenAPI documentation is available at `http://localhost:8000/docs`.

For OpenAI, set `OPENAI_API_KEY` and select `provider: openai` plus an OpenAI
model in the session's agent configuration. For Ollama, start Ollama, pull the
configured model, and select `provider: ollama`.

## Workflow

1. `POST /sessions`
2. `POST /sessions/{id}/message` until the planner requests approval
3. `POST /sessions/{id}/approve`
4. `POST /sessions/{id}/deploy` with `mode: package` or `mode: apply`
5. `POST /sessions/{id}/verify`

Each session owns a runtime containing its Planner, worker agents, an
`asyncio.Queue` for tasks, and an `asyncio.Queue` for events. Durable session
state, tasks, messages, and events are stored in MongoDB.

Package generation writes:

```text
deployment/
├── create_topics.sh
├── deploy_connectors.sh
├── deploy_ksql.sh
├── rollback.sh
├── connector_configs/
└── ksql/
```

Verification checks connector/task state, topic counts, offset movement, an
optional sink count endpoint, and optional ksqlDB duplicate and join queries.

## Test

```bash
uv run pytest
uv run ruff check app tests main.py
```
