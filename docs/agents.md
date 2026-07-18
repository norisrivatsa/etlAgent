# Kafka Pipeline Orchestrator — Agent Architecture

## Overview

The Kafka Pipeline Orchestrator is a multi-agent AI system that takes a natural language description of a source schema and target schema, and autonomously designs, evaluates, generates, and deploys a complete Kafka pipeline — including connector configs, ksqlDB SQL, topic configs, and error handling.

The system is split into two distinct layers:

- **Thinking Layer** — agents that reason, plan, and evaluate. Own the whiteboard. Talk to the user.
- **Execution Layer** — agents that receive a finalized instruction slice and translate it into exact deployment artifacts. No reasoning, deep domain knowledge only.

LLM backend is configurable per agent — Anthropic API or local Ollama models.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        USER                                  │
│         (Chat UI + Pipeline Creation Form + YAML Upload)     │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                   THINKING LAYER                             │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              PLANNER AGENT                          │    │
│  │  - Owns and manages the Whiteboard (shared state)   │    │
│  │  - Converses with user to extract requirements      │    │
│  │  - Orchestrates all other agents                    │    │
│  │  - Decides scope of re-runs on changes              │    │
│  │  - Switches between conversation / orchestration    │    │
│  └──────────────────┬──────────────────────────────────┘    │
│                     │                                        │
│         ┌───────────▼──────────────┐                        │
│         │     EVALUATOR AGENT      │◄──────┐                │
│         │  - Reviews full plan     │       │                 │
│         │  - Checks correctness    │       │                 │
│         │  - Two evaluation gates  │       │                 │
│         └───────────┬──────────────┘       │                │
│                     │                      │                 │
│         ┌───────────▼──────────────┐       │                │
│         │   EDGE CASE AGENT        │───────┘                │
│         │  - Adversarial reviewer  │  feeds findings back   │
│         │  - Thinks up failure     │  to Evaluator          │
│         │    scenarios per pipeline│                        │
│         └──────────────────────────┘                        │
└──────────────────────┬──────────────────────────────────────┘
                       │  finalized instruction slices
┌──────────────────────▼──────────────────────────────────────┐
│                   EXECUTION LAYER                            │
│                                                              │
│   ┌──────────────────┐      ┌──────────────────────────┐    │
│   │  CONNECT AGENT   │      │     ksqlDB AGENT         │    │
│   │  - Connector     │      │  - ksqlDB SQL generation │    │
│   │    configs (JSON)│      │  - Stream/Table/Join      │    │
│   │  - SMT configs   │      │    semantics              │    │
│   │  - DLQ setup     │      │  - Windowing logic        │    │
│   │  - Error handling│      │  - Syntax validation      │    │
│   └──────────────────┘      └──────────────────────────┘    │
│                                                              │
│   ┌──────────────────┐      ┌──────────────────────────┐    │
│   │  EXECUTOR AGENT  │      │     DEBUG AGENT          │    │
│   │  - Sequences     │      │  - Watches local logs    │    │
│   │    deployment    │      │  - Kafka / Connect /     │    │
│   │  - REST API calls│      │    ksqlDB log parsing    │    │
│   │  - Retry logic   │      │  - Reactive + proactive  │    │
│   │  - Partial fail  │      │  - Surfaces to whiteboard│    │
│   └──────────────────┘      └──────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│               KAFKA STACK (Self-hosted)                      │
│     Kafka 4.2.0 KRaft · Connect REST · ksqlDB REST          │
└─────────────────────────────────────────────────────────────┘
```

---

## The Whiteboard (Shared State)

The Planner owns and manages the Whiteboard — a structured state object that all agents read from and write to within their own section. It is the single source of truth for the entire pipeline design session.

### Structure

```
Whiteboard
├── requirements/          ← Planner writes (from user conversation / form)
│   ├── source             (type, connection, tables, CDC vs poll)
│   ├── sink               (type, connection, target topic)
│   ├── schema             (field mappings, types, transformations)
│   ├── joins              (pairs, type, windowing)
│   ├── scale              (eps, message size, retention, replication)
│   ├── validation         (rules per field, DLQ behaviour)
│   ├── naming_style       (topic naming conventions)
│   └── open_questions     (what the Planner still needs from user)
│
├── plan/                  ← Planner writes skeleton, agents fill sections
│   ├── topics             (names, partitions, retention, replication)
│   ├── connectors_needed  (source type, sink type, list of specs)
│   ├── ksqldb_objects     (streams, tables, joins, sequence)
│   └── dependencies       (deployment order graph)
│
├── agent_outputs/         ← Each agent writes to its own sub-section only
│   ├── connect            (connector configs, DLQ configs)
│   └── ksqldb             (SQL statements in order)
│
├── evaluation/            ← Evaluator + Edge Case Agent write here
│   ├── edge_cases         (adversarial scenarios found)
│   ├── findings           (issues flagged, severity)
│   ├── resolved           (issues addressed)
│   └── pending_user       (issues that need a user decision)
│
├── user_decisions/        ← Locked once set. Planner never re-asks.
│   ├── approved           (sections/decisions approved by user)
│   ├── rejected           (things explicitly rejected)
│   └── deferred           (acknowledged, deal with later)
│
├── decisions_log/         ← Planner writes — every decision, always
│   └── entries[]           (decision_id, timestamp, observation, reasoning, action, dispatched_task, awaiting)
│
├── tasks/                 ← Planner writes before dispatch — visible in UI
│   ├── pending[]           (tasks created, not yet dispatched)
│   ├── in_progress[]       (tasks currently running)
│   └── completed[]         (tasks done, with result summary)
│
└── execution_log/         ← Executor + Debug Agent write here
    ├── deployed            (what has been deployed, timestamps)
    ├── failed              (what failed, error details)
    └── debug_findings      (log signals surfaced by Debug Agent)
```

### Write Rules

- **Planner** — only agent that writes to `requirements/`, `plan/`, and top-level structure
- **Service agents** — write only to their own `agent_outputs/<name>/` section
- **Evaluator** — writes only to `evaluation/`
- **Edge Case Agent** — writes only to `evaluation/edge_cases`
- **Executor** — writes only to `execution_log/deployed` and `execution_log/failed`
- **Debug Agent** — writes only to `execution_log/debug_findings`
- **No agent writes to another agent's section**

### Context Slicing

Agents never receive the full whiteboard. The Planner passes only the relevant slice:

| Agent | Receives |
|---|---|
| Connect Agent | `requirements` + `plan.connectors_needed` + `plan.topics` |
| ksqlDB Agent | `requirements` + `plan.ksqldb_objects` + `plan.topics` |
| Evaluator | `plan` + `agent_outputs` + `evaluation.edge_cases` |
| Edge Case Agent | `plan` only |
| Executor | `agent_outputs` + `plan.dependencies` |
| Debug Agent | `execution_log` + `requirements.scale` |

---

## Agent Definitions

### Planner Agent

**Layer:** Thinking  
**Model:** 14b (Ollama) or Claude Sonnet (API)  
**Role:** Central nervous system. Owns the whiteboard. Runs the OBSERVE → DECIDE → LOG → ACT loop. Decides which agent to invoke next at every step — there is no hardcoded sequence.

**Two modes:**

*Conversation mode* — extracts requirements from user chat or ingests the pipeline creation form / YAML upload. Knows when it has enough to proceed. Asks only what it needs.

*Orchestration mode* — runs the decision loop. Reads whiteboard state, decides what the most important next action is, logs that decision with full reasoning, and dispatches a structured task to the appropriate agent. Determines the scope of each dispatch — if only a connector config changed, only the Connect Agent and Evaluator are re-run.

**The decision loop:**

```python
while pipeline_not_stable:
    state    = read_whiteboard()
    decision = llm_decide(state)        # reason about what to do next
    log_decision(decision)              # write to decisions_log — always
    if decision.action == "ask_user":
        response = ask_user(decision.question)
        write_whiteboard("requirements", response)
    elif decision.action == "invoke_agent":
        task = build_task(decision)
        write_whiteboard("tasks", task)  # task visible on whiteboard before dispatch
        result = invoke_agent(task)
        write_whiteboard(result.section, result.output)
    elif decision.action == "none":
        break                           # pipeline stable
```

**Tools:**
- `read_whiteboard(section?)` — read full or partial whiteboard
- `write_whiteboard(section, content)` — update state
- `log_decision(decision)` — append to `decisions_log` on whiteboard
- `ask_user(question)` — surface a question or decision to user
- `invoke_agent(task: AgentTask)` — dispatch a structured task to any agent
- `build_task(agent, instruction, context_slice, depends_on)` — construct an AgentTask

**Does not:**
- Write SQL or connector configs directly
- Make domain-specific Kafka decisions (delegates to service agents)
- Re-ask anything already in `user_decisions/`
- Skip logging a decision — every decision is always written, even trivial ones

---

### Evaluator Agent

**Layer:** Thinking  
**Model:** 14b (Ollama) or Claude Sonnet (API)  
**Role:** Reviews the full plan and agent outputs at two gates — before service agents run, and after they produce output. Collaborates with Edge Case Agent.

**Gate 1 — Plan review:** Receives the Planner's draft plan. Checks for logical correctness before any service agent is invoked. Flags issues back to Planner for resolution.

**Gate 2 — Output review:** Receives service agent outputs (connector configs + SQL). Checks that the generated artifacts match the plan and requirements. If wrong, sends back to the relevant service agent for a correction pass.

**Tools:**
- `read_whiteboard()` — reads plan + agent outputs + edge cases
- `write_evaluation(findings)` — writes to evaluation block
- `invoke_edge_case_agent()` — triggers adversarial review at Gate 1
- `flag_for_user(issue)` — escalates decisions that need user input

**Checks it performs:**
- Join key alignment (are the join fields actually present in both sides?)
- Schema compatibility (do source field types map cleanly to target?)
- KStream vs KTable semantics (is a slowly-changing dimension being treated as a table?)
- Ordering guarantees (does anything require same-partition delivery?)
- Consumer group conflicts (are any topics being consumed by multiple groups unintentionally?)
- Scale alignment (do topic partition counts match the expected throughput?)
- DLQ coverage (is every connector that needs a DLQ configured with one?)

---

### Edge Case Agent

**Layer:** Thinking  
**Model:** 7-8b (Ollama) or Claude Haiku (API)  
**Role:** Adversarial reviewer. Given the plan, thinks up the failure scenarios that are most likely to occur in this specific pipeline. Feeds findings to the Evaluator.

**Tools:**
- `read_whiteboard(plan)` — reads plan block only
- `kafka_version_lookup(version)` — checks known issues for the Kafka version in use
- `web_search(query)` — looks up known connector failure modes, ksqlDB gotchas by version
- `write_evaluation(edge_cases)` — writes scenarios to evaluation block

**Scenarios it considers:**
- Late arriving events (especially in stream-stream joins with windows)
- NULL join keys (breaks joins silently)
- Schema evolution mid-stream (field added/removed in source)
- Partition skew (hot keys sending all data to one partition)
- Duplicate CDC events (Debezium at-least-once delivery)
- Consumer lag buildup (sink slower than source)
- Connector TASK_FAILED on NULL timestamp columns (known JDBC gotcha)
- ksqlDB persistent query restart losing state

---

### Connect Agent

**Layer:** Execution  
**Model:** 7b (Ollama) or Claude Haiku (API) — small model, tight structured prompt  
**Role:** Receives a connector specification from the Planner and produces deployment-ready connector config JSON. Knows connector-specific behaviour deeply. Does not reason about the pipeline — only about its config.

**Tools:**
- `read_whiteboard(requirements + plan.connectors_needed)` — instruction slice only
- `web_search(query)` — version-specific config keys, known SMT patterns
- `validate_connector_config(config)` — structural validation before writing output
- `write_output(config)` — writes to `agent_outputs/connect/`

**Produces:**
- Source connector config JSON (JDBC, Debezium, S3, etc.)
- Sink connector config JSON
- DLQ topic config if required
- SMT (Single Message Transform) configs for field renaming, filtering, routing
- Error handling policy per connector

**Output format:** `temperature=0`, `format=json` — deterministic, no sampling.

---

### ksqlDB Agent

**Layer:** Execution  
**Model:** 7b (Ollama) or Claude Haiku (API) — small model, tight structured prompt  
**Role:** Receives a ksqlDB object specification from the Planner and produces correct, ordered ksqlDB SQL. Knows KStream vs KTable semantics, join types, windowing, and offset strategies deeply.

**Tools:**
- `read_whiteboard(requirements + plan.ksqldb_objects + plan.topics)` — instruction slice only
- `web_search(query)` — ksqlDB version-specific syntax, known join limitations
- `validate_sql(sql)` — syntax check before writing output
- `write_output(sql)` — writes to `agent_outputs/ksqldb/`

**Produces:**
- `CREATE STREAM` statements (append-only topics)
- `CREATE TABLE` statements (compacted / aggregated topics)
- `CREATE STREAM AS SELECT` / `CREATE TABLE AS SELECT` for transformations
- Join SQL with correct stream/table semantics
- Windowed aggregations with correct window type (tumbling / hopping / session)
- Data validation filters (WHERE clauses, CASE expressions)
- Correct `WITH` clause properties (topic, format, partitions, replicas)

**Output format:** `temperature=0`, `format=json` wrapping ordered SQL strings.

---

### Executor Agent

**Layer:** Execution  
**Model:** 7b (Ollama) or smaller — mostly REST calls, minimal reasoning  
**Role:** Sequences and deploys the finalized pipeline artifacts. Knows the correct deployment order. Handles partial failures and retries.

**Tools:**
- `kafka_rest_call(endpoint, payload)` — Kafka Admin API (topic creation)
- `connect_rest_call(endpoint, payload)` — Kafka Connect REST API
- `ksqldb_rest_call(statement)` — ksqlDB REST API
- `write_execution_log(entry)` — updates `execution_log/` on whiteboard

**Deployment order:**
1. Create all Kafka topics (from `plan.topics`)
2. Deploy source connectors
3. Wait for connector status = RUNNING
4. Execute ksqlDB statements in dependency order
5. Deploy sink connectors
6. Write execution log with timestamps and status

**On failure:** writes to `execution_log/failed`, surfaces to Planner for decision (retry / skip / abort).

---

### Debug Agent

**Layer:** Execution (async — runs in parallel with Executor)  
**Model:** 7b (Ollama) or Claude Haiku (API)  
**Role:** Watches local Kafka, Connect, and ksqlDB logs in real time. Surfaces meaningful signals. Invoked reactively (something broke) or proactively (monitor during Executor run).

**Tools:**
- `read_log_file(path)` — reads full log file
- `tail_log(path, lines)` — reads last N lines (live tail)
- `search_log(pattern)` — grep-style search across log files
- `web_search(query)` — looks up error messages, exception meanings
- `write_whiteboard(execution_log.debug_findings)` — surfaces findings

**Log files watched:**
```
/var/log/kafka-stack/kafka/         → broker logs
/var/log/kafka-stack/connect/connect.log  → Connect worker + connector task logs
/var/log/kafka-stack/ksqldb/ksqldb.log    → ksqlDB query + server logs
```

**What it surfaces:**
- Connector TASK_FAILED with root cause extracted
- Consumer lag threshold crossed
- ksqlDB query error / persistent query died
- Broker partition leader election
- Schema mismatch deserialization errors
- OOM or GC pressure warnings

---

## Pipeline Flow

There is no hardcoded pipeline sequence. The Planner decides at every step which agent to invoke next, what task to give it, and why. Every decision is logged to the whiteboard so the full reasoning trail is always visible.

### The Planner Loop

After each action — whether that's receiving user input, getting an agent result back, or reading a debug finding — the Planner runs a single reasoning step:

```
OBSERVE  → read current whiteboard state
DECIDE   → what is the most important next action?
LOG      → write the decision + rationale to decisions_log
ACT      → invoke an agent with a task, ask the user, or do nothing
```

It loops until the pipeline is deployed and stable, or it surfaces to the user for a decision it cannot make alone.

### What "Decide" Looks Like

The Planner is not rule-based. It reasons from the current state of the whiteboard. For example:

- *"Requirements are complete and no plan exists yet → produce a plan draft"*
- *"Plan exists but has not been evaluated → invoke Evaluator with the plan"*
- *"Evaluator flagged a NULL join key risk → invoke Edge Case Agent to expand on it, then re-evaluate"*
- *"Evaluation is clean but user has not reviewed → surface to user"*
- *"User approved. No connector configs exist yet → invoke Connect Agent with connector spec slice"*
- *"Connect Agent output exists but ksqlDB SQL does not → invoke ksqlDB Agent"*
- *"Both outputs exist → invoke Evaluator again on the artifacts"*
- *"Evaluation of artifacts is clean → ask user for final approval"*
- *"User approved artifacts → invoke Executor"*
- *"Executor reported TASK_FAILED on connector → invoke Debug Agent on connect.log"*
- *"Debug Agent found root cause → invoke Connect Agent with a correction task"*
- *"User added a new DLQ requirement mid-session → invoke Connect Agent only (ksqlDB untouched)"*

The key property: **the Planner decides scope**. It never re-runs everything when only one thing changed. It knows which agents are affected by a given change and invokes only those.

### Task Format

Every agent invocation carries a structured task — not a free-form prompt. The Planner writes the task to the whiteboard before dispatching so it is always visible.

```python
@dataclass
class AgentTask:
    task_id: str           # unique ID, e.g. "task_connect_001"
    agent: str             # which agent to invoke
    instruction: str       # what to do, in plain language
    context_slice: dict    # the whiteboard sections this agent needs
    depends_on: list[str]  # task IDs that must be complete first
    created_by: str        # always "planner"
    created_at: str        # ISO timestamp
```

Example task the Planner would produce for the Connect Agent:

```json
{
  "task_id": "task_connect_001",
  "agent": "connect",
  "instruction": "Generate a JDBC source connector config for PostgreSQL. The source table is 'orders' with primary key 'id' and timestamp column 'updated_at'. Use timestamp+incrementing mode. DLQ is required. Topic prefix is 'pg.kafka_source.'.",
  "context_slice": {
    "requirements.source": {},
    "requirements.scale": {},
    "plan.connectors_needed": {},
    "plan.topics": {}
  },
  "depends_on": [],
  "created_by": "planner",
  "created_at": "2025-06-13T10:32:00Z"
}
```

### Decision Log

Every decision the Planner makes is appended to `decisions_log` on the whiteboard — the reasoning, what it decided, and what it dispatched. This is what makes the system auditable and debuggable, and is what the Whiteboard UI renders as the "agent conversation" view.

```python
@dataclass
class PlannerDecision:
    decision_id: str       # unique ID
    timestamp: str         # ISO timestamp
    observation: str       # what the Planner read from the whiteboard
    reasoning: str         # why it made this decision
    action: str            # what it decided to do
    dispatched_task: str   # task_id if an agent was invoked, else None
    awaiting: str          # "user" | "agent:<name>" | "none"
```

Example decision log entry:

```json
{
  "decision_id": "decision_007",
  "timestamp": "2025-06-13T10:31:55Z",
  "observation": "Plan draft exists. Evaluator has not run yet. Edge cases not generated.",
  "reasoning": "Before dispatching to service agents, the plan must pass evaluation. Starting with Edge Case Agent first so Evaluator has adversarial scenarios to check against.",
  "action": "Invoke Edge Case Agent with plan slice, then Evaluator.",
  "dispatched_task": "task_edgecase_001",
  "awaiting": "agent:edge_case"
}
```

### Concrete Example Trace

For a simple Postgres → ksqlDB → MongoDB pipeline, a realistic Planner decision sequence might look like:

```
decision_001  observation: requirements incomplete — sink type missing
              action: ask_user("What is the target sink? MongoDB, Postgres, S3, or other?")

decision_002  observation: requirements now complete
              action: produce plan draft → write to whiteboard

decision_003  observation: plan draft written, no evaluation yet
              action: invoke Edge Case Agent [task_edgecase_001]

decision_004  observation: edge cases returned — NULL _id risk in MongoDB sink flagged
              action: invoke Evaluator with plan + edge cases [task_eval_001]

decision_005  observation: Evaluator flagged NULL _id as CRITICAL
              action: ask_user("MongoDB sink requires a scalar _id. Embed via FlinkSQL or UUID SMT?")

decision_006  observation: user chose FlinkSQL _id embedding, decision locked
              action: update plan, re-invoke Evaluator [task_eval_002]

decision_007  observation: Evaluator clean — no critical issues
              action: surface plan to user for review

decision_008  observation: user approved plan
              action: invoke Connect Agent [task_connect_001]

decision_009  observation: Connect Agent output complete
              action: invoke ksqlDB Agent [task_ksqldb_001]

decision_010  observation: both service agent outputs complete
              action: invoke Evaluator on artifacts [task_eval_003]

decision_011  observation: Evaluator clean on artifacts
              action: surface complete artifacts to user for final approval

decision_012  observation: user approved artifacts
              action: invoke Executor [task_exec_001]

decision_013  observation: Executor reported Connect TASK_FAILED
              action: invoke Debug Agent on connect.log [task_debug_001]

decision_014  observation: Debug Agent found missing table.whitelist config
              action: invoke Connect Agent with correction task [task_connect_002]

decision_015  observation: corrected config deployed, connector RUNNING
              action: invoke Executor to resume remaining deployment [task_exec_002]

decision_016  observation: all services RUNNING, no errors in logs
              action: none — pipeline stable, monitoring mode
```

This trace — every decision, every reasoning step — is exactly what the Whiteboard UI renders live as the system runs.

---

## Agent Base Classes

Two base classes — service agents and thinking agents have fundamentally different contracts.

### ThinkingAgent

```python
class ThinkingAgent:
    """
    Has full whiteboard access. Participates in the reasoning loop.
    Can surface to user. Can invoke other agents.
    """
    def run(self, context: WhiteboardSlice) -> ThinkingResult:
        raise NotImplementedError

    def write_whiteboard(self, section: str, content: dict): ...
    def read_whiteboard(self, section: str = None) -> dict: ...
    def ask_user(self, question: str) -> str: ...
```

### ServiceAgent

```python
class ServiceAgent:
    """
    Receives a finalized instruction slice only.
    No whiteboard write access outside own output section.
    No user interaction.
    Produces structured output deterministically.
    """
    def run(self, instruction_slice: dict) -> ServiceResult:
        raise NotImplementedError

    def write_output(self, content: dict): ...  # own section only
    def validate_output(self, output: dict) -> bool: ...
```

---

## LLM Backend Configuration

Each agent can be configured independently:

```yaml
agents:
  planner:
    backend: anthropic          # or ollama
    model: claude-sonnet-4-6    # or qwen2.5:14b
    temperature: 0.3
    max_tokens: 4096

  evaluator:
    backend: anthropic
    model: claude-sonnet-4-6
    temperature: 0.2
    max_tokens: 4096

  edge_case:
    backend: ollama
    model: llama3.1:8b
    temperature: 0.5            # slightly higher — adversarial creativity
    max_tokens: 2048

  connect:
    backend: ollama
    model: qwen2.5:7b
    temperature: 0              # deterministic config generation
    max_tokens: 2048
    format: json

  ksqldb:
    backend: ollama
    model: qwen2.5:7b
    temperature: 0
    max_tokens: 2048
    format: json

  executor:
    backend: ollama
    model: llama3.1:8b
    temperature: 0
    max_tokens: 1024

  debug:
    backend: ollama
    model: llama3.1:8b
    temperature: 0.1
    max_tokens: 2048
```

**Ollama performance notes for CPU-only:**
- Use `Q4_K_M` quantization for 14b models
- Set `num_ctx` explicitly per agent (don't default to 4096 for service agents — 2048 is enough)
- Set `num_thread` to physical core count
- Service agents use `format: json` for constrained generation — faster on CPU
- Cache web search results per session to avoid repeated LLM calls on the same query

---

## Tool Catalogue

| Tool | Used By | What It Does |
|---|---|---|
| `read_whiteboard` | Planner, Evaluator, Edge Case | Read full or partial whiteboard state |
| `write_whiteboard` | All agents (own section only) | Write to whiteboard section |
| `ask_user` | Planner, Evaluator | Surface question or decision to user |
| `invoke_agent` | Planner | Dispatch to any agent with instruction slice |
| `invoke_edge_case_agent` | Evaluator | Trigger adversarial scenario generation |
| `flag_for_user` | Evaluator | Escalate issue that needs user decision |
| `web_search` | Edge Case, Connect, ksqlDB, Debug | Search for version-specific docs, errors |
| `kafka_version_lookup` | Edge Case | Check known issues for Kafka version |
| `validate_connector_config` | Connect | Structural validation of connector JSON |
| `validate_sql` | ksqlDB | SQL syntax check before output |
| `kafka_rest_call` | Executor | Kafka Admin API (topics) |
| `connect_rest_call` | Executor | Kafka Connect REST API |
| `ksqldb_rest_call` | Executor | ksqlDB REST API |
| `read_log_file` | Debug | Read full log file |
| `tail_log` | Debug | Read last N lines of log |
| `search_log` | Debug | Grep-style search in logs |
| `write_execution_log` | Executor, Debug | Update execution log on whiteboard |

---

## Whiteboard UI

The whiteboard is visualised as a live canvas in the UI:

- Each agent has a **card/node** on the canvas
- When an agent writes to the whiteboard, the relevant section panel updates in real time
- When the Planner dispatches to an agent, a **message line** appears between their nodes
- When the Thinking Layer is iterating, you see Planner ↔ Evaluator messages passing live
- Whiteboard sections (requirements, plan, evaluation, decisions, execution log) are **visible panels** alongside the agent nodes — not hidden state
- You can click into any section and read exactly what the agents are looking at
- Chat window sits alongside for user ↔ Planner conversation
- Execution log panel shows live deploy status with colour-coded success/failure

---

## Project Structure

```
kafka-agent/
├── agents/
│   ├── base.py               # ThinkingAgent + ServiceAgent base classes
│   ├── planner.py            # Planner agent
│   ├── evaluator.py          # Evaluator agent
│   ├── edge_case.py          # Edge Case agent
│   ├── connect.py            # Connect agent
│   ├── ksqldb.py             # ksqlDB agent
│   ├── executor.py           # Executor agent
│   └── debug.py              # Debug agent
├── whiteboard/
│   ├── whiteboard.py         # Whiteboard state object (Pydantic model)
│   ├── sections.py           # Section schema definitions
│   └── store.py              # Persistence (SQLite for sessions)
├── tools/
│   ├── kafka_rest.py         # Kafka Admin API wrapper
│   ├── connect_rest.py       # Connect REST API wrapper
│   ├── ksqldb_rest.py        # ksqlDB REST API wrapper
│   ├── log_reader.py         # Log file tools
│   └── web_search.py         # Web search + session cache
├── llm/
│   ├── client.py             # Unified LLM client (Anthropic + Ollama)
│   └── config.py             # Per-agent model config
├── ui/
│   ├── app.py                # Main UI (React frontend)
│   ├── whiteboard_view/      # Live whiteboard canvas
│   └── chat/                 # Chat interface
├── pipeline_form/
│   ├── form.py               # Pipeline creation form schema
│   └── yaml_parser.py        # YAML upload → form auto-fill
└── kafka-stack/
    ├── configs/              # Kafka, Connect, ksqlDB configs
    └── scripts/              # Install, start, stop, status
```# Kafka Pipeline Orchestrator — Agent Architecture

## Overview

The Kafka Pipeline Orchestrator is a multi-agent AI system that takes a natural language description of a source schema and target schema, and autonomously designs, evaluates, generates, and deploys a complete Kafka pipeline — including connector configs, ksqlDB SQL, topic configs, and error handling.

The system is split into two distinct layers:

- **Thinking Layer** — agents that reason, plan, and evaluate. Own the whiteboard. Talk to the user.
- **Execution Layer** — agents that receive a finalized instruction slice and translate it into exact deployment artifacts. No reasoning, deep domain knowledge only.

LLM backend is configurable per agent — Anthropic API or local Ollama models.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        USER                                  │
│         (Chat UI + Pipeline Creation Form + YAML Upload)     │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                   THINKING LAYER                             │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              PLANNER AGENT                          │    │
│  │  - Owns and manages the Whiteboard (shared state)   │    │
│  │  - Converses with user to extract requirements      │    │
│  │  - Orchestrates all other agents                    │    │
│  │  - Decides scope of re-runs on changes              │    │
│  │  - Switches between conversation / orchestration    │    │
│  └──────────────────┬──────────────────────────────────┘    │
│                     │                                        │
│         ┌───────────▼──────────────┐                        │
│         │     EVALUATOR AGENT      │◄──────┐                │
│         │  - Reviews full plan     │       │                 │
│         │  - Checks correctness    │       │                 │
│         │  - Two evaluation gates  │       │                 │
│         └───────────┬──────────────┘       │                │
│                     │                      │                 │
│         ┌───────────▼──────────────┐       │                │
│         │   EDGE CASE AGENT        │───────┘                │
│         │  - Adversarial reviewer  │  feeds findings back   │
│         │  - Thinks up failure     │  to Evaluator          │
│         │    scenarios per pipeline│                        │
│         └──────────────────────────┘                        │
└──────────────────────┬──────────────────────────────────────┘
                       │  finalized instruction slices
┌──────────────────────▼──────────────────────────────────────┐
│                   EXECUTION LAYER                            │
│                                                              │
│   ┌──────────────────┐      ┌──────────────────────────┐    │
│   │  CONNECT AGENT   │      │     ksqlDB AGENT         │    │
│   │  - Connector     │      │  - ksqlDB SQL generation │    │
│   │    configs (JSON)│      │  - Stream/Table/Join      │    │
│   │  - SMT configs   │      │    semantics              │    │
│   │  - DLQ setup     │      │  - Windowing logic        │    │
│   │  - Error handling│      │  - Syntax validation      │    │
│   └──────────────────┘      └──────────────────────────┘    │
│                                                              │
│   ┌──────────────────┐      ┌──────────────────────────┐    │
│   │  EXECUTOR AGENT  │      │     DEBUG AGENT          │    │
│   │  - Sequences     │      │  - Watches local logs    │    │
│   │    deployment    │      │  - Kafka / Connect /     │    │
│   │  - REST API calls│      │    ksqlDB log parsing    │    │
│   │  - Retry logic   │      │  - Reactive + proactive  │    │
│   │  - Partial fail  │      │  - Surfaces to whiteboard│    │
│   └──────────────────┘      └──────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│               KAFKA STACK (Self-hosted)                      │
│     Kafka 4.2.0 KRaft · Connect REST · ksqlDB REST          │
└─────────────────────────────────────────────────────────────┘
```

---

## The Whiteboard (Shared State)

The Planner owns and manages the Whiteboard — a structured state object that all agents read from and write to within their own section. It is the single source of truth for the entire pipeline design session.

### Structure

```
Whiteboard
├── requirements/          ← Planner writes (from user conversation / form)
│   ├── source             (type, connection, tables, CDC vs poll)
│   ├── sink               (type, connection, target topic)
│   ├── schema             (field mappings, types, transformations)
│   ├── joins              (pairs, type, windowing)
│   ├── scale              (eps, message size, retention, replication)
│   ├── validation         (rules per field, DLQ behaviour)
│   ├── naming_style       (topic naming conventions)
│   └── open_questions     (what the Planner still needs from user)
│
├── plan/                  ← Planner writes skeleton, agents fill sections
│   ├── topics             (names, partitions, retention, replication)
│   ├── connectors_needed  (source type, sink type, list of specs)
│   ├── ksqldb_objects     (streams, tables, joins, sequence)
│   └── dependencies       (deployment order graph)
│
├── agent_outputs/         ← Each agent writes to its own sub-section only
│   ├── connect            (connector configs, DLQ configs)
│   └── ksqldb             (SQL statements in order)
│
├── evaluation/            ← Evaluator + Edge Case Agent write here
│   ├── edge_cases         (adversarial scenarios found)
│   ├── findings           (issues flagged, severity)
│   ├── resolved           (issues addressed)
│   └── pending_user       (issues that need a user decision)
│
├── user_decisions/        ← Locked once set. Planner never re-asks.
│   ├── approved           (sections/decisions approved by user)
│   ├── rejected           (things explicitly rejected)
│   └── deferred           (acknowledged, deal with later)
│
├── decisions_log/         ← Planner writes — every decision, always
│   └── entries[]           (decision_id, timestamp, observation, reasoning, action, dispatched_task, awaiting)
│
├── tasks/                 ← Planner writes before dispatch — visible in UI
│   ├── pending[]           (tasks created, not yet dispatched)
│   ├── in_progress[]       (tasks currently running)
│   └── completed[]         (tasks done, with result summary)
│
└── execution_log/         ← Executor + Debug Agent write here
    ├── deployed            (what has been deployed, timestamps)
    ├── failed              (what failed, error details)
    └── debug_findings      (log signals surfaced by Debug Agent)
```

### Write Rules

- **Planner** — only agent that writes to `requirements/`, `plan/`, and top-level structure
- **Service agents** — write only to their own `agent_outputs/<name>/` section
- **Evaluator** — writes only to `evaluation/`
- **Edge Case Agent** — writes only to `evaluation/edge_cases`
- **Executor** — writes only to `execution_log/deployed` and `execution_log/failed`
- **Debug Agent** — writes only to `execution_log/debug_findings`
- **No agent writes to another agent's section**

### Context Slicing

Agents never receive the full whiteboard. The Planner passes only the relevant slice:

| Agent | Receives |
|---|---|
| Connect Agent | `requirements` + `plan.connectors_needed` + `plan.topics` |
| ksqlDB Agent | `requirements` + `plan.ksqldb_objects` + `plan.topics` |
| Evaluator | `plan` + `agent_outputs` + `evaluation.edge_cases` |
| Edge Case Agent | `plan` only |
| Executor | `agent_outputs` + `plan.dependencies` |
| Debug Agent | `execution_log` + `requirements.scale` |

---

## Agent Definitions

### Planner Agent

**Layer:** Thinking  
**Model:** 14b (Ollama) or Claude Sonnet (API)  
**Role:** Central nervous system. Owns the whiteboard. Runs the OBSERVE → DECIDE → LOG → ACT loop. Decides which agent to invoke next at every step — there is no hardcoded sequence.

**Two modes:**

*Conversation mode* — extracts requirements from user chat or ingests the pipeline creation form / YAML upload. Knows when it has enough to proceed. Asks only what it needs.

*Orchestration mode* — runs the decision loop. Reads whiteboard state, decides what the most important next action is, logs that decision with full reasoning, and dispatches a structured task to the appropriate agent. Determines the scope of each dispatch — if only a connector config changed, only the Connect Agent and Evaluator are re-run.

**The decision loop:**

```python
while pipeline_not_stable:
    state    = read_whiteboard()
    decision = llm_decide(state)        # reason about what to do next
    log_decision(decision)              # write to decisions_log — always
    if decision.action == "ask_user":
        response = ask_user(decision.question)
        write_whiteboard("requirements", response)
    elif decision.action == "invoke_agent":
        task = build_task(decision)
        write_whiteboard("tasks", task)  # task visible on whiteboard before dispatch
        result = invoke_agent(task)
        write_whiteboard(result.section, result.output)
    elif decision.action == "none":
        break                           # pipeline stable
```

**Tools:**
- `read_whiteboard(section?)` — read full or partial whiteboard
- `write_whiteboard(section, content)` — update state
- `log_decision(decision)` — append to `decisions_log` on whiteboard
- `ask_user(question)` — surface a question or decision to user
- `invoke_agent(task: AgentTask)` — dispatch a structured task to any agent
- `build_task(agent, instruction, context_slice, depends_on)` — construct an AgentTask

**Does not:**
- Write SQL or connector configs directly
- Make domain-specific Kafka decisions (delegates to service agents)
- Re-ask anything already in `user_decisions/`
- Skip logging a decision — every decision is always written, even trivial ones

---

### Evaluator Agent

**Layer:** Thinking  
**Model:** 14b (Ollama) or Claude Sonnet (API)  
**Role:** Reviews the full plan and agent outputs at two gates — before service agents run, and after they produce output. Collaborates with Edge Case Agent.

**Gate 1 — Plan review:** Receives the Planner's draft plan. Checks for logical correctness before any service agent is invoked. Flags issues back to Planner for resolution.

**Gate 2 — Output review:** Receives service agent outputs (connector configs + SQL). Checks that the generated artifacts match the plan and requirements. If wrong, sends back to the relevant service agent for a correction pass.

**Tools:**
- `read_whiteboard()` — reads plan + agent outputs + edge cases
- `write_evaluation(findings)` — writes to evaluation block
- `invoke_edge_case_agent()` — triggers adversarial review at Gate 1
- `flag_for_user(issue)` — escalates decisions that need user input

**Checks it performs:**
- Join key alignment (are the join fields actually present in both sides?)
- Schema compatibility (do source field types map cleanly to target?)
- KStream vs KTable semantics (is a slowly-changing dimension being treated as a table?)
- Ordering guarantees (does anything require same-partition delivery?)
- Consumer group conflicts (are any topics being consumed by multiple groups unintentionally?)
- Scale alignment (do topic partition counts match the expected throughput?)
- DLQ coverage (is every connector that needs a DLQ configured with one?)

---

### Edge Case Agent

**Layer:** Thinking  
**Model:** 7-8b (Ollama) or Claude Haiku (API)  
**Role:** Adversarial reviewer. Given the plan, thinks up the failure scenarios that are most likely to occur in this specific pipeline. Feeds findings to the Evaluator.

**Tools:**
- `read_whiteboard(plan)` — reads plan block only
- `kafka_version_lookup(version)` — checks known issues for the Kafka version in use
- `web_search(query)` — looks up known connector failure modes, ksqlDB gotchas by version
- `write_evaluation(edge_cases)` — writes scenarios to evaluation block

**Scenarios it considers:**
- Late arriving events (especially in stream-stream joins with windows)
- NULL join keys (breaks joins silently)
- Schema evolution mid-stream (field added/removed in source)
- Partition skew (hot keys sending all data to one partition)
- Duplicate CDC events (Debezium at-least-once delivery)
- Consumer lag buildup (sink slower than source)
- Connector TASK_FAILED on NULL timestamp columns (known JDBC gotcha)
- ksqlDB persistent query restart losing state

---

### Connect Agent

**Layer:** Execution  
**Model:** 7b (Ollama) or Claude Haiku (API) — small model, tight structured prompt  
**Role:** Receives a connector specification from the Planner and produces deployment-ready connector config JSON. Knows connector-specific behaviour deeply. Does not reason about the pipeline — only about its config.

**Tools:**
- `read_whiteboard(requirements + plan.connectors_needed)` — instruction slice only
- `web_search(query)` — version-specific config keys, known SMT patterns
- `validate_connector_config(config)` — structural validation before writing output
- `write_output(config)` — writes to `agent_outputs/connect/`

**Produces:**
- Source connector config JSON (JDBC, Debezium, S3, etc.)
- Sink connector config JSON
- DLQ topic config if required
- SMT (Single Message Transform) configs for field renaming, filtering, routing
- Error handling policy per connector

**Output format:** `temperature=0`, `format=json` — deterministic, no sampling.

---

### ksqlDB Agent

**Layer:** Execution  
**Model:** 7b (Ollama) or Claude Haiku (API) — small model, tight structured prompt  
**Role:** Receives a ksqlDB object specification from the Planner and produces correct, ordered ksqlDB SQL. Knows KStream vs KTable semantics, join types, windowing, and offset strategies deeply.

**Tools:**
- `read_whiteboard(requirements + plan.ksqldb_objects + plan.topics)` — instruction slice only
- `web_search(query)` — ksqlDB version-specific syntax, known join limitations
- `validate_sql(sql)` — syntax check before writing output
- `write_output(sql)` — writes to `agent_outputs/ksqldb/`

**Produces:**
- `CREATE STREAM` statements (append-only topics)
- `CREATE TABLE` statements (compacted / aggregated topics)
- `CREATE STREAM AS SELECT` / `CREATE TABLE AS SELECT` for transformations
- Join SQL with correct stream/table semantics
- Windowed aggregations with correct window type (tumbling / hopping / session)
- Data validation filters (WHERE clauses, CASE expressions)
- Correct `WITH` clause properties (topic, format, partitions, replicas)

**Output format:** `temperature=0`, `format=json` wrapping ordered SQL strings.

---

### Executor Agent

**Layer:** Execution  
**Model:** 7b (Ollama) or smaller — mostly REST calls, minimal reasoning  
**Role:** Sequences and deploys the finalized pipeline artifacts. Knows the correct deployment order. Handles partial failures and retries.

**Tools:**
- `kafka_rest_call(endpoint, payload)` — Kafka Admin API (topic creation)
- `connect_rest_call(endpoint, payload)` — Kafka Connect REST API
- `ksqldb_rest_call(statement)` — ksqlDB REST API
- `write_execution_log(entry)` — updates `execution_log/` on whiteboard

**Deployment order:**
1. Create all Kafka topics (from `plan.topics`)
2. Deploy source connectors
3. Wait for connector status = RUNNING
4. Execute ksqlDB statements in dependency order
5. Deploy sink connectors
6. Write execution log with timestamps and status

**On failure:** writes to `execution_log/failed`, surfaces to Planner for decision (retry / skip / abort).

---

### Debug Agent

**Layer:** Execution (async — runs in parallel with Executor)  
**Model:** 7b (Ollama) or Claude Haiku (API)  
**Role:** Watches local Kafka, Connect, and ksqlDB logs in real time. Surfaces meaningful signals. Invoked reactively (something broke) or proactively (monitor during Executor run).

**Tools:**
- `read_log_file(path)` — reads full log file
- `tail_log(path, lines)` — reads last N lines (live tail)
- `search_log(pattern)` — grep-style search across log files
- `web_search(query)` — looks up error messages, exception meanings
- `write_whiteboard(execution_log.debug_findings)` — surfaces findings

**Log files watched:**
```
/var/log/kafka-stack/kafka/         → broker logs
/var/log/kafka-stack/connect/connect.log  → Connect worker + connector task logs
/var/log/kafka-stack/ksqldb/ksqldb.log    → ksqlDB query + server logs
```

**What it surfaces:**
- Connector TASK_FAILED with root cause extracted
- Consumer lag threshold crossed
- ksqlDB query error / persistent query died
- Broker partition leader election
- Schema mismatch deserialization errors
- OOM or GC pressure warnings

---

## Pipeline Flow

There is no hardcoded pipeline sequence. The Planner decides at every step which agent to invoke next, what task to give it, and why. Every decision is logged to the whiteboard so the full reasoning trail is always visible.

### The Planner Loop

After each action — whether that's receiving user input, getting an agent result back, or reading a debug finding — the Planner runs a single reasoning step:

```
OBSERVE  → read current whiteboard state
DECIDE   → what is the most important next action?
LOG      → write the decision + rationale to decisions_log
ACT      → invoke an agent with a task, ask the user, or do nothing
```

It loops until the pipeline is deployed and stable, or it surfaces to the user for a decision it cannot make alone.

### What "Decide" Looks Like

The Planner is not rule-based. It reasons from the current state of the whiteboard. For example:

- *"Requirements are complete and no plan exists yet → produce a plan draft"*
- *"Plan exists but has not been evaluated → invoke Evaluator with the plan"*
- *"Evaluator flagged a NULL join key risk → invoke Edge Case Agent to expand on it, then re-evaluate"*
- *"Evaluation is clean but user has not reviewed → surface to user"*
- *"User approved. No connector configs exist yet → invoke Connect Agent with connector spec slice"*
- *"Connect Agent output exists but ksqlDB SQL does not → invoke ksqlDB Agent"*
- *"Both outputs exist → invoke Evaluator again on the artifacts"*
- *"Evaluation of artifacts is clean → ask user for final approval"*
- *"User approved artifacts → invoke Executor"*
- *"Executor reported TASK_FAILED on connector → invoke Debug Agent on connect.log"*
- *"Debug Agent found root cause → invoke Connect Agent with a correction task"*
- *"User added a new DLQ requirement mid-session → invoke Connect Agent only (ksqlDB untouched)"*

The key property: **the Planner decides scope**. It never re-runs everything when only one thing changed. It knows which agents are affected by a given change and invokes only those.

### Task Format

Every agent invocation carries a structured task — not a free-form prompt. The Planner writes the task to the whiteboard before dispatching so it is always visible.

```python
@dataclass
class AgentTask:
    task_id: str           # unique ID, e.g. "task_connect_001"
    agent: str             # which agent to invoke
    instruction: str       # what to do, in plain language
    context_slice: dict    # the whiteboard sections this agent needs
    depends_on: list[str]  # task IDs that must be complete first
    created_by: str        # always "planner"
    created_at: str        # ISO timestamp
```

Example task the Planner would produce for the Connect Agent:

```json
{
  "task_id": "task_connect_001",
  "agent": "connect",
  "instruction": "Generate a JDBC source connector config for PostgreSQL. The source table is 'orders' with primary key 'id' and timestamp column 'updated_at'. Use timestamp+incrementing mode. DLQ is required. Topic prefix is 'pg.kafka_source.'.",
  "context_slice": {
    "requirements.source": {},
    "requirements.scale": {},
    "plan.connectors_needed": {},
    "plan.topics": {}
  },
  "depends_on": [],
  "created_by": "planner",
  "created_at": "2025-06-13T10:32:00Z"
}
```

### Decision Log

Every decision the Planner makes is appended to `decisions_log` on the whiteboard — the reasoning, what it decided, and what it dispatched. This is what makes the system auditable and debuggable, and is what the Whiteboard UI renders as the "agent conversation" view.

```python
@dataclass
class PlannerDecision:
    decision_id: str       # unique ID
    timestamp: str         # ISO timestamp
    observation: str       # what the Planner read from the whiteboard
    reasoning: str         # why it made this decision
    action: str            # what it decided to do
    dispatched_task: str   # task_id if an agent was invoked, else None
    awaiting: str          # "user" | "agent:<name>" | "none"
```

Example decision log entry:

```json
{
  "decision_id": "decision_007",
  "timestamp": "2025-06-13T10:31:55Z",
  "observation": "Plan draft exists. Evaluator has not run yet. Edge cases not generated.",
  "reasoning": "Before dispatching to service agents, the plan must pass evaluation. Starting with Edge Case Agent first so Evaluator has adversarial scenarios to check against.",
  "action": "Invoke Edge Case Agent with plan slice, then Evaluator.",
  "dispatched_task": "task_edgecase_001",
  "awaiting": "agent:edge_case"
}
```

### Concrete Example Trace

For a simple Postgres → ksqlDB → MongoDB pipeline, a realistic Planner decision sequence might look like:

```
decision_001  observation: requirements incomplete — sink type missing
              action: ask_user("What is the target sink? MongoDB, Postgres, S3, or other?")

decision_002  observation: requirements now complete
              action: produce plan draft → write to whiteboard

decision_003  observation: plan draft written, no evaluation yet
              action: invoke Edge Case Agent [task_edgecase_001]

decision_004  observation: edge cases returned — NULL _id risk in MongoDB sink flagged
              action: invoke Evaluator with plan + edge cases [task_eval_001]

decision_005  observation: Evaluator flagged NULL _id as CRITICAL
              action: ask_user("MongoDB sink requires a scalar _id. Embed via FlinkSQL or UUID SMT?")

decision_006  observation: user chose FlinkSQL _id embedding, decision locked
              action: update plan, re-invoke Evaluator [task_eval_002]

decision_007  observation: Evaluator clean — no critical issues
              action: surface plan to user for review

decision_008  observation: user approved plan
              action: invoke Connect Agent [task_connect_001]

decision_009  observation: Connect Agent output complete
              action: invoke ksqlDB Agent [task_ksqldb_001]

decision_010  observation: both service agent outputs complete
              action: invoke Evaluator on artifacts [task_eval_003]

decision_011  observation: Evaluator clean on artifacts
              action: surface complete artifacts to user for final approval

decision_012  observation: user approved artifacts
              action: invoke Executor [task_exec_001]

decision_013  observation: Executor reported Connect TASK_FAILED
              action: invoke Debug Agent on connect.log [task_debug_001]

decision_014  observation: Debug Agent found missing table.whitelist config
              action: invoke Connect Agent with correction task [task_connect_002]

decision_015  observation: corrected config deployed, connector RUNNING
              action: invoke Executor to resume remaining deployment [task_exec_002]

decision_016  observation: all services RUNNING, no errors in logs
              action: none — pipeline stable, monitoring mode
```

This trace — every decision, every reasoning step — is exactly what the Whiteboard UI renders live as the system runs.

---

## Agent Base Classes

Two base classes — service agents and thinking agents have fundamentally different contracts.

### ThinkingAgent

```python
class ThinkingAgent:
    """
    Has full whiteboard access. Participates in the reasoning loop.
    Can surface to user. Can invoke other agents.
    """
    def run(self, context: WhiteboardSlice) -> ThinkingResult:
        raise NotImplementedError

    def write_whiteboard(self, section: str, content: dict): ...
    def read_whiteboard(self, section: str = None) -> dict: ...
    def ask_user(self, question: str) -> str: ...
```

### ServiceAgent

```python
class ServiceAgent:
    """
    Receives a finalized instruction slice only.
    No whiteboard write access outside own output section.
    No user interaction.
    Produces structured output deterministically.
    """
    def run(self, instruction_slice: dict) -> ServiceResult:
        raise NotImplementedError

    def write_output(self, content: dict): ...  # own section only
    def validate_output(self, output: dict) -> bool: ...
```

---

## LLM Backend Configuration

Each agent can be configured independently:

```yaml
agents:
  planner:
    backend: anthropic          # or ollama
    model: claude-sonnet-4-6    # or qwen2.5:14b
    temperature: 0.3
    max_tokens: 4096

  evaluator:
    backend: anthropic
    model: claude-sonnet-4-6
    temperature: 0.2
    max_tokens: 4096

  edge_case:
    backend: ollama
    model: llama3.1:8b
    temperature: 0.5            # slightly higher — adversarial creativity
    max_tokens: 2048

  connect:
    backend: ollama
    model: qwen2.5:7b
    temperature: 0              # deterministic config generation
    max_tokens: 2048
    format: json

  ksqldb:
    backend: ollama
    model: qwen2.5:7b
    temperature: 0
    max_tokens: 2048
    format: json

  executor:
    backend: ollama
    model: llama3.1:8b
    temperature: 0
    max_tokens: 1024

  debug:
    backend: ollama
    model: llama3.1:8b
    temperature: 0.1
    max_tokens: 2048
```

**Ollama performance notes for CPU-only:**
- Use `Q4_K_M` quantization for 14b models
- Set `num_ctx` explicitly per agent (don't default to 4096 for service agents — 2048 is enough)
- Set `num_thread` to physical core count
- Service agents use `format: json` for constrained generation — faster on CPU
- Cache web search results per session to avoid repeated LLM calls on the same query

---

## Tool Catalogue

| Tool | Used By | What It Does |
|---|---|---|
| `read_whiteboard` | Planner, Evaluator, Edge Case | Read full or partial whiteboard state |
| `write_whiteboard` | All agents (own section only) | Write to whiteboard section |
| `ask_user` | Planner, Evaluator | Surface question or decision to user |
| `invoke_agent` | Planner | Dispatch to any agent with instruction slice |
| `invoke_edge_case_agent` | Evaluator | Trigger adversarial scenario generation |
| `flag_for_user` | Evaluator | Escalate issue that needs user decision |
| `web_search` | Edge Case, Connect, ksqlDB, Debug | Search for version-specific docs, errors |
| `kafka_version_lookup` | Edge Case | Check known issues for Kafka version |
| `validate_connector_config` | Connect | Structural validation of connector JSON |
| `validate_sql` | ksqlDB | SQL syntax check before output |
| `kafka_rest_call` | Executor | Kafka Admin API (topics) |
| `connect_rest_call` | Executor | Kafka Connect REST API |
| `ksqldb_rest_call` | Executor | ksqlDB REST API |
| `read_log_file` | Debug | Read full log file |
| `tail_log` | Debug | Read last N lines of log |
| `search_log` | Debug | Grep-style search in logs |
| `write_execution_log` | Executor, Debug | Update execution log on whiteboard |

---

## Whiteboard UI

The whiteboard is visualised as a live canvas in the UI:

- Each agent has a **card/node** on the canvas
- When an agent writes to the whiteboard, the relevant section panel updates in real time
- When the Planner dispatches to an agent, a **message line** appears between their nodes
- When the Thinking Layer is iterating, you see Planner ↔ Evaluator messages passing live
- Whiteboard sections (requirements, plan, evaluation, decisions, execution log) are **visible panels** alongside the agent nodes — not hidden state
- You can click into any section and read exactly what the agents are looking at
- Chat window sits alongside for user ↔ Planner conversation
- Execution log panel shows live deploy status with colour-coded success/failure

---

## Project Structure

```
kafka-agent/
├── agents/
│   ├── base.py               # ThinkingAgent + ServiceAgent base classes
│   ├── planner.py            # Planner agent
│   ├── evaluator.py          # Evaluator agent
│   ├── edge_case.py          # Edge Case agent
│   ├── connect.py            # Connect agent
│   ├── ksqldb.py             # ksqlDB agent
│   ├── executor.py           # Executor agent
│   └── debug.py              # Debug agent
├── whiteboard/
│   ├── whiteboard.py         # Whiteboard state object (Pydantic model)
│   ├── sections.py           # Section schema definitions
│   └── store.py              # Persistence (SQLite for sessions)
├── tools/
│   ├── kafka_rest.py         # Kafka Admin API wrapper
│   ├── connect_rest.py       # Connect REST API wrapper
│   ├── ksqldb_rest.py        # ksqlDB REST API wrapper
│   ├── log_reader.py         # Log file tools
│   └── web_search.py         # Web search + session cache
├── llm/
│   ├── client.py             # Unified LLM client (Anthropic + Ollama)
│   └── config.py             # Per-agent model config
├── ui/
│   ├── app.py                # Main UI (React frontend)
│   ├── whiteboard_view/      # Live whiteboard canvas
│   └── chat/                 # Chat interface
├── pipeline_form/
│   ├── form.py               # Pipeline creation form schema
│   └── yaml_parser.py        # YAML upload → form auto-fill
└── kafka-stack/
    ├── configs/              # Kafka, Connect, ksqlDB configs
    └── scripts/              # Install, start, stop, status
```
