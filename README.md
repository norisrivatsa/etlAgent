# Kafka Pipeline Architect Agent

A multi-agent AI system that designs, evaluates, deploys, debugs, and verifies
Kafka Connect and ksqlDB pipelines from a natural-language conversation.

## What we're trying to do

This project is an experiment, not a product pitch: how well can a team of
LLM agents design, build, and operate a real Kafka ETL pipeline with minimal
human oversight? Building a Kafka Connect + ksqlDB pipeline correctly involves
a lot of judgment calls — connector modes, join/window semantics, DLQ
coverage, deployment order — and the question here is whether that judgment
can actually be delegated to subagents, and whether they produce pipelines
that are correct, not just plausible-looking.

Concretely, we're testing:

- Whether a **Planner** agent can gather requirements and make sound
  design decisions on its own, only escalating to the human when it
  genuinely needs a decision only they can make.
- Whether **subagents** (Connect, ksqlDB, Evaluator, Edge Case, Executor,
  Debug, Verification) can each do their narrow slice of the job well —
  producing connector configs and ksqlDB SQL that are actually correct,
  catching real edge cases before deployment, and diagnosing real failures.


Every step is visible: the Planner logs its reasoning and every dispatch to
other agents on a shared "whiteboard," so the whole design/build/deploy
process is auditable rather than a black box — which is also what makes it
possible to evaluate how well the agents are actually doing.

<!-- Screenshots coming soon -->

## How it works

The system is split into a **thinking layer** (plans and reviews) and an
**execution layer** (produces deployment artifacts and talks to the Kafka
stack):

- **Planner** — gathers requirements from the conversation and owns the
  session's shared state (the "whiteboard").
- **Evaluator** / **Edge Case Agent** — review the plan for correctness and
  failure modes (bad join keys, schema drift, DLQ coverage, etc.) before
  anything is deployed.
- **Connect Agent** — generates Kafka Connect source/sink connector configs.
- **ksqlDB Agent** — generates ksqlDB streams, tables, joins, and windowed SQL.
- **Executor** — deploys the generated artifacts via the Kafka Connect and
  ksqlDB REST APIs.
- **Debug Agent** — inspects logs when something fails.
- **Verification Agent** — checks the deployed pipeline is actually healthy
  (connector status, topic offsets, sink counts).

Each session persists its state (requirements, plan, generated artifacts,
decisions, deployment status) in MongoDB, so the full reasoning trail is
auditable. See [`backend/docs/how_it_works.md`](backend/docs/how_it_works.md)
and [`docs/agents.md`](docs/agents.md) for a deeper dive into the backend
implementation and agent architecture.

## Workflow

1. Create a session and describe your pipeline in chat.
2. The Planner asks clarifying questions until it has enough to propose a plan.
3. You approve the plan — the Connect, ksqlDB, and Evaluator agents run.
4. You approve the generated artifacts and deploy (`package` to just generate
   files, or `apply` to deploy them for real).
5. The Verification agent checks the deployed pipeline is healthy.

## Project structure

```
etlAgent/
├── backend/   FastAPI service — sessions, agents, LLM routing, deployment
├── frontend/  React + Vite UI — chat, whiteboard view, pipeline workspace
```
