# Kafka Pipeline Orchestrator — Shared State Architecture

## Overview

The system uses four files for all shared state. Each file has a single clear purpose and strict ownership rules.

```
whiteboard.json     — the pipeline spec. What we are building.
tasks.db            — SQLite database
  ├── tasks         — task queue: instructions out, results back
  ├── messages      — communication pool: agents ping Planner here
  └── context       — extra context messages agents exchange per task
thinking.log        — Planner's internal reasoning, append-only
```

---

## File 1: whiteboard.json

The single source of truth about what the pipeline is supposed to do. Kept deliberately small and clean — only the pipeline specification lives here, nothing operational.

**Owner:** Planner only. No other agent writes to this file.  
**Readers:** All agents (read-only via context slice passed in their task).  
**Format:** JSON, versioned — every write increments `version` and appends to `history[]`.

### Schema

```json
{
  "version": 4,
  "pipeline_name": "orders_to_mongo",
  "status": "evaluating",
  "updated_at": "2025-06-13T10:45:00Z",

  "source": {
    "type": "postgres",
    "host_ref": "src_postgres_01",
    "database": "kafka_source",
    "tables": ["orders", "customers"],
    "ingest_mode": "cdc",
    "primary_keys": {
      "orders": "id",
      "customers": "id"
    }
  },

  "sink": {
    "type": "mongodb",
    "host_ref": "sink_mongo_01",
    "database": "pipeline_out",
    "collection": "enriched_orders"
  },

  "target_schema": {
    "fields": [
      { "name": "order_id",      "type": "INT",     "source": "orders.id",             "nullable": false },
      { "name": "customer_name", "type": "VARCHAR",  "source": "customers.name",        "nullable": true  },
      { "name": "product",       "type": "VARCHAR",  "source": "orders.product",        "nullable": false },
      { "name": "amount",        "type": "DECIMAL",  "source": "orders.amount",         "nullable": false },
      { "name": "status",        "type": "VARCHAR",  "source": "orders.status",         "nullable": false },
      { "name": "ordered_at",    "type": "TIMESTAMP","source": "orders.created_at",     "nullable": false }
    ]
  },

  "transformations": [
    { "field": "product",  "op": "ucase_trim",  "description": "uppercase and trim whitespace" },
    { "field": "status",   "op": "lcase_trim",  "description": "lowercase and trim whitespace" },
    { "field": "amount",   "op": "filter_gt",   "value": 0,   "description": "drop zero/negative amounts" }
  ],

  "joins": [
    {
      "left":       "orders",
      "right":      "customers",
      "join_type":  "stream_table",
      "left_key":   "customer_id",
      "right_key":  "id",
      "windowing":  null
    }
  ],

  "topics": {
    "naming_style": "dot.notation",
    "entries": [
      { "name": "pg.kafka_source.orders",    "partitions": 6, "replication": 1, "retention_hours": 168, "purpose": "raw orders from JDBC source" },
      { "name": "pg.kafka_source.customers", "partitions": 3, "replication": 1, "retention_hours": 168, "purpose": "raw customers from JDBC source" },
      { "name": "orders.enriched",           "partitions": 6, "replication": 1, "retention_hours": 72,  "purpose": "joined + transformed output stream" }
    ]
  },

  "validation_rules": [
    { "field": "order_id", "rule": "not_null" },
    { "field": "amount",   "rule": "gt",       "value": 0 },
    { "field": "status",   "rule": "enum",     "values": ["pending", "confirmed", "shipped", "cancelled"] }
  ],

  "scale": {
    "expected_eps":       5000,
    "message_size_kb":    2,
    "retention_days":     7,
    "replication_factor": 1,
    "guarantee":          "at_least_once"
  },

  "error_handling": {
    "dlq_enabled":  true,
    "max_retries":  3,
    "backoff_ms":   1000
  },

  "history": [
    { "version": 1, "updated_at": "2025-06-13T10:30:00Z", "change": "initial requirements from form" },
    { "version": 2, "updated_at": "2025-06-13T10:38:00Z", "change": "added customers join after user clarification" },
    { "version": 3, "updated_at": "2025-06-13T10:41:00Z", "change": "added validation rules" },
    { "version": 4, "updated_at": "2025-06-13T10:45:00Z", "change": "scale profile updated to 5k eps" }
  ]
}
```

### Status Values

| Status | Meaning |
|---|---|
| `requirements` | Planner still gathering requirements from user |
| `planning` | Planner producing the plan draft |
| `evaluating` | Evaluator + Edge Case Agent reviewing |
| `awaiting_user` | Surfaced to user, waiting for input |
| `generating` | Service agents producing artifacts |
| `validating` | Evaluator reviewing service agent outputs |
| `executing` | Executor deploying |
| `stable` | Pipeline running, Debug Agent monitoring |
| `failed` | Something critical broke, needs user attention |

### Write Rules

- Planner reads the full file before each decision loop iteration
- Planner writes the full file atomically (write to `.tmp`, rename to `whiteboard.json`)
- Every write must increment `version` and append to `history[]`
- All other agents receive a read-only slice — they never open this file directly

---

## File 2: tasks.db (SQLite)

Three tables. WAL mode enabled for concurrent reads during async agent execution.

```sql
PRAGMA journal_mode=WAL;
```

---

### Table: tasks

One row per task the Planner creates. Planner writes the row before dispatching. Agent updates `status`, `result`, `result_status`, `completed_at` when done, then pings the message pool.

```sql
CREATE TABLE tasks (
  task_id         TEXT PRIMARY KEY,
  agent           TEXT NOT NULL,
  instruction     TEXT NOT NULL,
  context_slice   TEXT NOT NULL,         -- JSON: whiteboard sections + prior outputs
  depends_on      TEXT DEFAULT '[]',     -- JSON array of task_ids
  status          TEXT DEFAULT 'pending',-- pending / in_progress / completed / failed
  priority        TEXT DEFAULT 'normal', -- normal / high / critical
  created_at      TEXT NOT NULL,         -- ISO timestamp
  dispatched_at   TEXT,
  completed_at    TEXT,
  result          TEXT,                  -- JSON: agent's full output
  result_status   TEXT,                  -- ok / needs_revision / critical_issue
  notes           TEXT                   -- agent flags, warnings, caveats
);
```

**Task lifecycle:**

```
Planner writes row    → status = pending
Planner dispatches    → status = in_progress, dispatched_at = now
Agent completes       → status = completed, result = output, completed_at = now
                         then writes a ping to messages pool
Agent fails           → status = failed, notes = error details
                         then writes a ping to messages pool
```

**Example task row:**

```json
{
  "task_id":       "task_connect_001",
  "agent":         "connect",
  "instruction":   "Generate a JDBC source connector config for PostgreSQL. Source table is 'orders', primary key 'id', timestamp column 'updated_at'. Mode: timestamp+incrementing. DLQ required. Topic prefix: 'pg.kafka_source.'.",
  "context_slice": {
    "source":          { "...": "from whiteboard" },
    "scale":           { "...": "from whiteboard" },
    "topics":          { "...": "from whiteboard" },
    "error_handling":  { "...": "from whiteboard" }
  },
  "depends_on":    "[]",
  "status":        "completed",
  "priority":      "normal",
  "created_at":    "2025-06-13T10:48:00Z",
  "dispatched_at": "2025-06-13T10:48:01Z",
  "completed_at":  "2025-06-13T10:48:45Z",
  "result":        { "name": "postgres-orders-source", "config": { "...": "..." } },
  "result_status": "ok",
  "notes":         "Used timestamp+incrementing mode. DLQ topic: pg.orders.dlq"
}
```

---

### Table: context

Extra context messages that agents exchange within a task. Agents can write here mid-task — for example, the Evaluator writing an interim finding that the Edge Case Agent should consider, or the Debug Agent leaving a note for the Connect Agent's correction task. Planner can also seed this with additional context after a task is created.

```sql
CREATE TABLE context (
  context_id    TEXT PRIMARY KEY,
  task_id       TEXT NOT NULL,           -- which task this belongs to
  from_agent    TEXT NOT NULL,           -- who wrote it
  to_agent      TEXT,                    -- who it's for (null = all agents on this task)
  message       TEXT NOT NULL,           -- the context content (plain text or JSON)
  context_type  TEXT DEFAULT 'note',     -- note / finding / clarification / correction
  created_at    TEXT NOT NULL,
  FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);
```

**When context is used:**

- Planner seeds extra context after task creation: *"Note: user confirmed _id must be a scalar string, not an ObjectId"*
- Evaluator writes a finding mid-review that the ksqlDB Agent's correction task should be aware of
- Debug Agent leaves a note on the Executor's retry task: *"The NULL updated_at issue is in rows where status = 'legacy' — filter these out"*
- Edge Case Agent writes scenario details for the Evaluator to check against

**Example context row:**

```json
{
  "context_id":   "ctx_007",
  "task_id":      "task_connect_002",
  "from_agent":   "debug",
  "to_agent":     "connect",
  "message":      "Root cause identified: NULL updated_at values exist in 847 rows where status = 'legacy'. These predate the timestamp column addition. Recommend adding WHERE updated_at IS NOT NULL to the query or switching to incrementing-only mode for this connector.",
  "context_type": "finding",
  "created_at":   "2025-06-13T11:02:33Z"
}
```

---

### Table: messages

The communication pool. Agents write here when they have something to tell the Planner. Planner polls every 2 seconds, reads unread messages, acts, marks them read.

```sql
CREATE TABLE messages (
  message_id    TEXT PRIMARY KEY,
  from_agent    TEXT NOT NULL,
  task_id       TEXT,                    -- which task this relates to (if any)
  type          TEXT NOT NULL,           -- ping / result / finding / error / status_update / question
  payload       TEXT NOT NULL,           -- JSON content
  priority      TEXT DEFAULT 'normal',   -- normal / high / critical
  created_at    TEXT NOT NULL,
  read          INTEGER DEFAULT 0,       -- 0 = unread, 1 = read
  read_at       TEXT
);
```

### Message Types

| Type | Who Sends | When |
|---|---|---|
| `ping` | Any agent | Task completed or failed — the primary "I'm done" signal |
| `result` | Service agents | Task completed with output ready in tasks table |
| `finding` | Debug Agent | Something found in logs — may or may not relate to a task |
| `error` | Any agent | Hit something it couldn't handle |
| `status_update` | Executor | Deployment progress (connector deploying, RUNNING, etc.) |
| `question` | Any agent | Needs clarification to continue — Planner resolves or escalates to user |

### The Ping

When any agent completes or fails a task, it **always** sends a `ping` to the message pool. This is the signal the Planner uses to know something needs its attention. The ping is minimal — it just points to the task:

```json
{
  "message_id":  "msg_031",
  "from_agent":  "connect",
  "task_id":     "task_connect_001",
  "type":        "ping",
  "payload":     {
    "status":    "completed",
    "result_status": "ok",
    "summary":   "JDBC source connector config generated. DLQ configured."
  },
  "priority":    "normal",
  "created_at":  "2025-06-13T10:48:45Z",
  "read":        0
}
```

The Planner reads the ping, checks `result_status`, fetches the full result from the `tasks` table, and continues the decision loop.

### Critical / High Priority Pings

Errors and critical findings get elevated priority so the Planner processes them first:

```json
{
  "message_id":  "msg_044",
  "from_agent":  "executor",
  "task_id":     "task_exec_001",
  "type":        "error",
  "payload":     {
    "status":        "failed",
    "error":         "TASK_FAILED on connector postgres-orders-source",
    "error_detail":  "org.apache.kafka.connect.errors.ConnectException: java.sql.SQLSyntaxErrorException: column updated_at does not exist"
  },
  "priority":    "critical",
  "created_at":  "2025-06-13T10:52:11Z",
  "read":        0
}
```

### Planner Poll Query

```sql
SELECT * FROM messages
WHERE read = 0
ORDER BY
  CASE priority
    WHEN 'critical' THEN 1
    WHEN 'high'     THEN 2
    WHEN 'normal'   THEN 3
  END,
  created_at ASC;
```

Critical messages always processed first regardless of arrival order.

---

## File 3: thinking.log

The Planner's internal reasoning stream. Append-only plain text. Every time the Planner reasons about what to do next, it writes its thinking here before acting.

**Owner:** Planner only. No other agent reads or writes this file.  
**Format:** Append-only, timestamped entries.  
**Purpose:** Debuggability. If the system makes a wrong decision, you open this file and see exactly why.

### Format

```
[2025-06-13T10:48:00Z] OBSERVE
  whiteboard.status = "evaluating"
  evaluation task task_eval_001 → completed, result_status = ok
  no pending tasks
  user_decisions: plan approved at 10:47:33Z

[2025-06-13T10:48:00Z] THINK
  Evaluation passed clean. User approved the plan.
  Next step is to generate artifacts — connector configs and ksqlDB SQL.
  The pipeline has one source (Postgres JDBC), one join (orders + customers),
  one sink (MongoDB). I need to invoke the Connect Agent for both source
  and sink connectors, and the ksqlDB Agent for the join stream.
  Connect Agent does not depend on ksqlDB Agent and vice versa — I can
  dispatch them independently. I will dispatch Connect Agent first since
  connector topics need to exist before ksqlDB can reference them.
  Actually — topics are created by the Executor separately. Both agents
  just generate configs/SQL. I will dispatch both in the same loop pass.
  Dispatching: task_connect_001, task_ksqldb_001.

[2025-06-13T10:48:01Z] ACT
  dispatched task_connect_001 → connect agent
  dispatched task_ksqldb_001  → ksqldb agent
  awaiting pings from both

---

[2025-06-13T10:52:11Z] OBSERVE
  new message: msg_044 from executor, type=error, priority=critical
  task_exec_001 failed — TASK_FAILED on postgres-orders-source connector
  error: column updated_at does not exist

[2025-06-13T10:52:11Z] THINK
  This is a schema mismatch. The JDBC connector config references updated_at
  as the timestamp column but it does not exist in the orders table.
  I need to check the whiteboard — the source table definition says
  timestamp column is updated_at. But the error says it doesn't exist.
  Two possibilities:
  1. The column name is wrong — user may have given wrong name
  2. The column exists but under a different name
  I should invoke the Debug Agent to check the actual table schema
  from the connector logs before asking the user. If the logs show
  the real column name I can correct without bothering the user.
  Dispatching task_debug_001.

[2025-06-13T10:52:12Z] ACT
  dispatched task_debug_001 → debug agent
  awaiting ping from debug agent
```

### Why Plain Text Not JSON

The thinking file is for humans to read when debugging. JSON would make it harder to skim. The Planner writes in natural language — this is its actual reasoning, not a structured data record. The tasks and messages tables handle structured data. The thinking file handles the why.

---

## Ownership Summary

| File / Table | Writer | Readers |
|---|---|---|
| `whiteboard.json` | Planner only | All agents (via context slice in task) |
| `tasks.tasks` | Planner creates rows | Agent updates own row result |
| `tasks.context` | Any agent, Planner | Agent reading its task |
| `tasks.messages` | Any agent | Planner only |
| `thinking.log` | Planner only | Humans (debugging) |

---

## Communication Flow

```
┌─────────────────────────────────────────────────────────────┐
│                      PLANNER                                 │
│                                                              │
│  every 2 seconds:                                            │
│  1. read messages WHERE read = 0  (poll messages pool)       │
│  2. write thinking.log            (OBSERVE → THINK → ACT)    │
│  3. update whiteboard.json        (if spec changed)          │
│  4. write new task rows           (if dispatching)           │
│  5. mark messages as read                                    │
└──────────┬───────────────────────────────────┬──────────────┘
           │ writes tasks                      │ reads messages
           ▼                                   │
┌──────────────────────┐             ┌─────────┴──────────────┐
│      tasks.tasks     │             │    tasks.messages       │
│  (task queue)        │             │  (communication pool)   │
└──────────┬───────────┘             └─────────▲──────────────┘
           │ agent reads task                  │ agent writes ping
           ▼                                   │
┌─────────────────────────────────────────────┐│
│                  AGENTS                      ││
│                                              ││
│  1. receive task (task_id passed by Planner) ││
│  2. read own task row from tasks table       ││
│  3. read context rows for this task_id       ││
│  4. execute task                             ││
│  5. write result back to own task row        ││
│  6. ping messages pool ──────────────────────┘│
│                                               │
│  (Debug Agent also pings on async findings) ──┘
└──────────────────────────────────────────────┘
```

---

## Session Management

Each pipeline session gets its own set of files in a session directory:

```
sessions/
  pipeline_20250613_143022_orders_to_mongo/
    whiteboard.json
    tasks.db
    thinking.log
  pipeline_20250614_091500_clickstream_to_s3/
    whiteboard.json
    tasks.db
    thinking.log
```

Session ID format: `pipeline_<YYYYMMDD>_<HHMMSS>_<pipeline_name>`

The UI lists sessions by reading the sessions directory. Any session can be reopened — the Planner re-reads `whiteboard.json` and the tasks/messages tables to reconstruct full state and resume from where it left off.

---

## Python Models

```python
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

# ── Whiteboard ──────────────────────────────────────────────

@dataclass
class WhiteboardField:
    name:     str
    type:     str
    source:   str
    nullable: bool = True

@dataclass
class WhiteboardJoin:
    left:      str
    right:     str
    join_type: str           # stream_table / stream_stream / table_table
    left_key:  str
    right_key: str
    windowing: Optional[str] = None

@dataclass
class Whiteboard:
    version:       int
    pipeline_name: str
    status:        str
    source:        dict
    sink:          dict
    target_schema: list[WhiteboardField]
    transformations: list[dict]
    joins:         list[WhiteboardJoin]
    topics:        dict
    validation_rules: list[dict]
    scale:         dict
    error_handling: dict
    history:       list[dict]
    updated_at:    str


# ── Tasks ────────────────────────────────────────────────────

@dataclass
class AgentTask:
    task_id:       str
    agent:         str
    instruction:   str
    context_slice: dict
    depends_on:    list[str]    = field(default_factory=list)
    status:        str          = "pending"
    priority:      str          = "normal"
    created_at:    str          = ""
    dispatched_at: Optional[str] = None
    completed_at:  Optional[str] = None
    result:        Optional[dict] = None
    result_status: Optional[str]  = None
    notes:         Optional[str]  = None

@dataclass
class ContextMessage:
    context_id:   str
    task_id:      str
    from_agent:   str
    message:      str
    context_type: str           # note / finding / clarification / correction
    to_agent:     Optional[str] = None
    created_at:   str          = ""


# ── Messages ─────────────────────────────────────────────────

@dataclass
class PoolMessage:
    message_id: str
    from_agent: str
    type:       str             # ping / result / finding / error / status_update / question
    payload:    dict
    task_id:    Optional[str]  = None
    priority:   str            = "normal"
    created_at: str            = ""
    read:       bool           = False
    read_at:    Optional[str]  = None
```

---

## Init Checklist

When a new session starts:

```python
def init_session(pipeline_name: str) -> str:
    session_id  = f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{pipeline_name}"
    session_dir = f"sessions/{session_id}"

    os.makedirs(session_dir)

    # whiteboard.json — empty shell
    write_whiteboard(session_dir, Whiteboard(version=0, status="requirements", ...))

    # tasks.db — create tables + WAL mode
    init_db(f"{session_dir}/tasks.db")

    # thinking.log — empty, append-only
    open(f"{session_dir}/thinking.log", "w").close()

    return session_id
```
