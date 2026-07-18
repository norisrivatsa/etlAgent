from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ============================================================
# COMMON
# ============================================================

def utc_now() -> str:
    return datetime.utcnow().isoformat()


# ============================================================
# LLM CONFIG
# ============================================================

BackendType = Literal["openai", "ollama"]


class AgentModelConfig(BaseModel):
    backend: BackendType
    model: str
    temperature: float = 0.0
    max_tokens: int = 2048
    format: Optional[str] = None


class SessionConfig(BaseModel):
    planner: AgentModelConfig
    evaluator: AgentModelConfig
    edge_case: AgentModelConfig
    connect: AgentModelConfig
    ksqldb: AgentModelConfig
    executor: AgentModelConfig
    debug: AgentModelConfig


# ============================================================
# WHITEBOARD CORE
# ============================================================

class WhiteboardHistory(BaseModel):
    version: int
    updated_at: str = Field(default_factory=utc_now)
    change: str


class WhiteboardField(BaseModel):
    name: str
    type: str
    source: str
    nullable: bool = True


class TransformationRule(BaseModel):
    field: str
    op: str
    value: Optional[Any] = None
    description: Optional[str] = None


class ValidationRule(BaseModel):
    field: str
    rule: str
    value: Optional[Any] = None
    values: Optional[List[Any]] = None


class WhiteboardJoin(BaseModel):
    left: str
    right: str
    join_type: str
    left_key: str
    right_key: str
    windowing: Optional[str] = None


class TopicEntry(BaseModel):
    name: str
    partitions: int
    replication: int
    retention_hours: int
    purpose: Optional[str] = None


class TopicPlan(BaseModel):
    naming_style: str = "dot.notation"
    entries: List[TopicEntry] = Field(default_factory=list)


class SourceConfig(BaseModel):
    type: Optional[str] = None
    host_ref: Optional[str] = None
    database: Optional[str] = None
    tables: List[str] = Field(default_factory=list)
    ingest_mode: Optional[str] = None
    primary_keys: Dict[str, str] = Field(default_factory=dict)


class SinkConfig(BaseModel):
    type: Optional[str] = None
    host_ref: Optional[str] = None
    database: Optional[str] = None
    collection: Optional[str] = None


class ScaleConfig(BaseModel):
    expected_eps: Optional[int] = None
    message_size_kb: Optional[int] = None
    retention_days: Optional[int] = None
    replication_factor: Optional[int] = None
    guarantee: Optional[str] = None


class ErrorHandlingConfig(BaseModel):
    dlq_enabled: bool = False
    max_retries: int = 3
    backoff_ms: int = 1000


# ============================================================
# REQUIREMENTS
# ============================================================

class Requirements(BaseModel):
    source: Dict[str, Any] = Field(default_factory=dict)
    sink: Dict[str, Any] = Field(default_factory=dict)
    schema: Dict[str, Any] = Field(default_factory=dict)
    joins: List[Dict[str, Any]] = Field(default_factory=list)
    scale: Dict[str, Any] = Field(default_factory=dict)
    validation: List[Dict[str, Any]] = Field(default_factory=list)
    naming_style: Optional[str] = None
    open_questions: List[str] = Field(default_factory=list)


# ============================================================
# PLAN
# ============================================================

class ConnectorSpec(BaseModel):
    connector_type: str
    source_type: Optional[str] = None
    sink_type: Optional[str] = None
    description: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)


class KsqlObject(BaseModel):
    object_name: str
    object_type: str
    description: Optional[str] = None
    spec: Dict[str, Any] = Field(default_factory=dict)


class Dependency(BaseModel):
    source: str
    target: str


class PipelinePlan(BaseModel):
    topics: TopicPlan = Field(default_factory=TopicPlan)
    connectors_needed: List[ConnectorSpec] = Field(default_factory=list)
    ksqldb_objects: List[KsqlObject] = Field(default_factory=list)
    dependencies: List[Dependency] = Field(default_factory=list)


# ============================================================
# AGENT OUTPUTS
# ============================================================

class ConnectOutput(BaseModel):
    connector_configs: List[Dict[str, Any]] = Field(default_factory=list)
    dlq_configs: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class KsqlOutput(BaseModel):
    statements: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class AgentOutputs(BaseModel):
    connect: Optional[ConnectOutput] = None
    ksqldb: Optional[KsqlOutput] = None


# ============================================================
# EVALUATION
# ============================================================

SeverityType = Literal[
    "low",
    "medium",
    "high",
    "critical"
]


class EdgeCase(BaseModel):
    title: str
    severity: SeverityType
    description: str
    mitigation: Optional[str] = None


class EvaluationFinding(BaseModel):
    title: str
    severity: SeverityType
    description: str
    requires_user: bool = False


class EvaluationState(BaseModel):
    edge_cases: List[EdgeCase] = Field(default_factory=list)
    findings: List[EvaluationFinding] = Field(default_factory=list)
    resolved: List[str] = Field(default_factory=list)
    pending_user: List[str] = Field(default_factory=list)


# ============================================================
# USER DECISIONS
# ============================================================

class UserDecisions(BaseModel):
    approved: List[str] = Field(default_factory=list)
    rejected: List[str] = Field(default_factory=list)
    deferred: List[str] = Field(default_factory=list)


# ============================================================
# PLANNER DECISIONS
# ============================================================

class PlannerDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str = Field(default_factory=utc_now)

    observation: str
    reasoning: str

    action: str

    dispatched_task: Optional[str] = None

    awaiting: Literal[
        "none",
        "user",
        "agent:planner",
        "agent:evaluator",
        "agent:edge_case",
        "agent:connect",
        "agent:ksqldb",
        "agent:executor",
        "agent:debug"
    ] = "none"


class DecisionLog(BaseModel):
    entries: List[PlannerDecision] = Field(default_factory=list)


# ============================================================
# EXECUTION LOG
# ============================================================

class DeploymentRecord(BaseModel):
    component: str
    status: str
    timestamp: str = Field(default_factory=utc_now)
    details: Optional[str] = None


class DebugFinding(BaseModel):
    source: str
    severity: SeverityType
    message: str
    timestamp: str = Field(default_factory=utc_now)


class ExecutionLog(BaseModel):
    deployed: List[DeploymentRecord] = Field(default_factory=list)
    failed: List[DeploymentRecord] = Field(default_factory=list)
    debug_findings: List[DebugFinding] = Field(default_factory=list)


# ============================================================
# TASKS
# ============================================================

TaskStatus = Literal[
    "pending",
    "in_progress",
    "completed",
    "failed"
]

TaskPriority = Literal[
    "normal",
    "high",
    "critical"
]


class AgentTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))

    agent: str
    instruction: str

    context_slice: Dict[str, Any]

    depends_on: List[str] = Field(default_factory=list)

    status: TaskStatus = "pending"
    priority: TaskPriority = "normal"

    created_at: str = Field(default_factory=utc_now)
    dispatched_at: Optional[str] = None
    completed_at: Optional[str] = None

    result: Optional[Dict[str, Any]] = None
    result_status: Optional[str] = None
    notes: Optional[str] = None


class TaskBucket(BaseModel):
    pending: List[AgentTask] = Field(default_factory=list)
    in_progress: List[AgentTask] = Field(default_factory=list)
    completed: List[AgentTask] = Field(default_factory=list)


# ============================================================
# CONTEXT TABLE
# ============================================================

class ContextMessage(BaseModel):
    context_id: str = Field(default_factory=lambda: str(uuid4()))

    task_id: str

    from_agent: str

    to_agent: Optional[str] = None

    message: str

    context_type: Literal[
        "note",
        "finding",
        "clarification",
        "correction"
    ] = "note"

    created_at: str = Field(default_factory=utc_now)


# ============================================================
# MESSAGE POOL
# ============================================================

MessageType = Literal[
    "ping",
    "result",
    "finding",
    "error",
    "status_update",
    "question"
]


class PoolMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))

    from_agent: str

    task_id: Optional[str] = None

    type: MessageType

    payload: Dict[str, Any]

    priority: TaskPriority = "normal"

    created_at: str = Field(default_factory=utc_now)

    read: bool = False

    read_at: Optional[str] = None


# ============================================================
# WHITEBOARD ROOT
# ============================================================

WhiteboardStatus = Literal[
    "requirements",
    "planning",
    "evaluating",
    "awaiting_user",
    "generating",
    "validating",
    "executing",
    "stable",
    "failed"
]


class Whiteboard(BaseModel):
    version: int = 0

    pipeline_name: str

    status: WhiteboardStatus = "requirements"

    updated_at: str = Field(default_factory=utc_now)

    source: SourceConfig = Field(default_factory=SourceConfig)

    sink: SinkConfig = Field(default_factory=SinkConfig)

    target_schema: List[WhiteboardField] = Field(default_factory=list)

    transformations: List[TransformationRule] = Field(default_factory=list)

    joins: List[WhiteboardJoin] = Field(default_factory=list)

    topics: TopicPlan = Field(default_factory=TopicPlan)

    validation_rules: List[ValidationRule] = Field(default_factory=list)

    scale: ScaleConfig = Field(default_factory=ScaleConfig)

    error_handling: ErrorHandlingConfig = Field(
        default_factory=ErrorHandlingConfig
    )

    history: List[WhiteboardHistory] = Field(default_factory=list)

    requirements: Requirements = Field(default_factory=Requirements)

    plan: PipelinePlan = Field(default_factory=PipelinePlan)

    agent_outputs: AgentOutputs = Field(
        default_factory=AgentOutputs
    )

    evaluation: EvaluationState = Field(
        default_factory=EvaluationState
    )

    user_decisions: UserDecisions = Field(
        default_factory=UserDecisions
    )

    decisions_log: DecisionLog = Field(
        default_factory=DecisionLog
    )

    tasks: TaskBucket = Field(default_factory=TaskBucket)

    execution_log: ExecutionLog = Field(
        default_factory=ExecutionLog
    )


# ============================================================
# SESSION
# ============================================================

class SessionMetadata(BaseModel):
    session_id: str
    pipeline_name: str
    created_at: str = Field(default_factory=utc_now)


class SessionState(BaseModel):
    metadata: SessionMetadata
    config: SessionConfig
    whiteboard: Whiteboard
