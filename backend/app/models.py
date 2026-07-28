from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class ModelProvider(StrEnum):
    OPENAI = "openai"
    OLLAMA = "ollama"


class AgentModelConfig(BaseModel):
    provider: ModelProvider = ModelProvider.OLLAMA
    model: str = "qwen2.5:7b"
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=128)


class SessionConfig(BaseModel):
    planner: AgentModelConfig = Field(default_factory=AgentModelConfig)
    connect: AgentModelConfig = Field(default_factory=AgentModelConfig)
    ksqldb: AgentModelConfig = Field(default_factory=AgentModelConfig)
    evaluator: AgentModelConfig = Field(default_factory=AgentModelConfig)
    edge_case: AgentModelConfig = Field(default_factory=AgentModelConfig)
    executor: AgentModelConfig = Field(default_factory=AgentModelConfig)
    debug: AgentModelConfig = Field(default_factory=AgentModelConfig)
    kafka_bootstrap_servers: str | None = None
    connect_url: str | None = None
    ksqldb_url: str | None = None


class SessionStatus(StrEnum):
    REQUIREMENTS = "requirements"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    GENERATING = "generating"
    READY = "ready"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    FAILED = "failed"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class EventType(StrEnum):
    SESSION = "session"
    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    TASK = "task"
    APPROVAL = "approval"
    DEPLOYMENT = "deployment"
    ERROR = "error"


class RequirementState(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: dict[str, Any] = Field(default_factory=dict)
    sink: dict[str, Any] = Field(default_factory=dict)
    schema_: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="schema",
        serialization_alias="schema",
    )
    joins: list[dict[str, Any]] = Field(default_factory=list)
    scale: dict[str, Any] = Field(default_factory=dict)
    validation: list[dict[str, Any]] = Field(default_factory=list)
    naming_style: str | None = None
    notes: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class PipelinePlan(BaseModel):
    summary: str = ""
    topics: list[dict[str, Any]] = Field(default_factory=list)
    connectors: list[dict[str, Any]] = Field(default_factory=list)
    ksqldb_objects: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: list[dict[str, Any]] = Field(default_factory=list)
    deployment_order: list[str] = Field(default_factory=list)


class EvaluationState(BaseModel):
    findings: list[dict[str, Any]] = Field(default_factory=list)
    edge_cases: list[dict[str, Any]] = Field(default_factory=list)
    approved: bool = False


class Decision(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    action: str
    reason: str
    created_at: datetime = Field(default_factory=utc_now)


class DeploymentStatus(BaseModel):
    state: str = "not_started"
    package_path: str | None = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class Artifact(BaseModel):
    """One proposed/committed file — a connector config or a ksqlDB statement."""

    artifact_id: str = Field(default_factory=lambda: str(uuid4()))
    agent: str  # "connect" | "ksqldb"
    kind: str  # "connector" | "ksql_statement"
    name: str
    content: dict[str, Any]
    status: str = "proposed"  # "proposed" | "rejected" | "committed" | "superseded"
    phase: str | None = None
    file_path: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    committed_at: datetime | None = None


class ChatMessage(BaseModel):
    """Chat message view of a human<->planner turn — never agent-to-agent traffic.
    Embedded directly in the session document (see SessionState.messages) so it's
    persisted the instant it's sent, with no separate collection round-trip."""

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    role: str  # "user" or "assistant"
    content: str
    starred: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class Whiteboard(BaseModel):
    requirements: RequirementState = Field(default_factory=RequirementState)
    plan: PipelinePlan = Field(default_factory=PipelinePlan)
    topics: list[dict[str, Any]] = Field(default_factory=list)
    connectors: list[dict[str, Any]] = Field(default_factory=list)
    ksqldb_objects: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    evaluation: EvaluationState = Field(default_factory=EvaluationState)
    decisions: list[Decision] = Field(default_factory=list)
    deployment_status: DeploymentStatus = Field(default_factory=DeploymentStatus)
    # Freeform running engineering log the Planner curates itself from what the
    # user says about the source/sink/schema — its own judgment of what matters,
    # not a structured field like `requirements`. See plannerAgentPrompt.md.
    pipeline_notes: str = ""
    revision: int = 0
    updated_at: datetime = Field(default_factory=utc_now)


class SessionState(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    pipeline_name: str
    config: SessionConfig = Field(default_factory=SessionConfig)
    whiteboard: Whiteboard = Field(default_factory=Whiteboard)
    # Every human<->planner chat turn, embedded directly in the session document —
    # the durable source of truth for chat. Only the last RECENT_MESSAGE_COUNT
    # (plus starred ones) are ever put in front of the Planner directly; anything
    # older is reachable only through its query_messages tool.
    messages: list[ChatMessage] = Field(default_factory=list)
    status: SessionStatus = SessionStatus.REQUIREMENTS
    pending_approval: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SessionList(BaseModel):
    sessions: list[SessionState]


class AgentTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    agent: str
    instruction: str
    context: dict[str, Any] = Field(default_factory=dict)
    phase: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    sender: str
    recipient: str
    content: dict[str, Any]
    read: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class SessionEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    type: EventType
    source: str
    data: dict[str, Any] = Field(default_factory=dict)
    starred: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class CreateSessionRequest(BaseModel):
    pipeline_name: str = Field(min_length=1, max_length=120)
    config: SessionConfig = Field(default_factory=SessionConfig)
    initial_requirements: dict[str, Any] = Field(default_factory=dict)


class UserMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    artifact_id: str | None = None


class ApprovalRequest(BaseModel):
    approved: bool
    comment: str | None = Field(default=None, max_length=5000)


class DeployMode(StrEnum):
    PACKAGE = "package"
    APPLY = "apply"


class DeployRequest(BaseModel):
    mode: DeployMode = DeployMode.PACKAGE


class SessionMessageResponse(BaseModel):
    """HTTP response envelope for /message, /approve, /chat-messages POST."""

    session: SessionState
    reply: str
    tasks: list[AgentTask] = Field(default_factory=list)


class EventList(BaseModel):
    events: list[SessionEvent]
    next_cursor: datetime | None = None


class NextStep(BaseModel):
    """One Planner-authored dispatch unit — design doc §3b."""

    agent: str
    instruction: str
    context_slice: dict[str, Any] = Field(default_factory=dict)
    phase: str


class TopicDeclaration(BaseModel):
    """One Kafka topic the Planner knows exists, for the Pipeline Graph view —
    see PlannerResponse.topics. Upserted by name, not replaced wholesale."""

    name: str
    # The component name that writes to this topic: a connector's Artifact.name
    # for a source-phase topic, or a ksqlDB object_name for a topic produced by
    # a ksqlDB statement (e.g. the final joined-table topic feeding the sink).
    produced_by: str


class PlannerResponse(BaseModel):
    """The Planner's own LLM output contract — design doc §3b."""

    reply_to_user: str
    requirements_patch: dict[str, Any] = Field(default_factory=dict)
    next_steps: list[NextStep] = Field(default_factory=list)
    awaiting: str = "user"  # "user" | "approval" | "done" | "agent:<name>"
    # Full replacement text for whiteboard.pipeline_notes, or None to leave it
    # unchanged this turn — the Planner rewrites/curates the whole note itself.
    pipeline_notes: str | None = None
    # New/updated topics only — upserted by name into whiteboard.topics, not a
    # full replacement. Powers the Pipeline Graph view's topic nodes.
    topics: list[TopicDeclaration] = Field(default_factory=list)


class WorkerResponse(BaseModel):
    """Every worker's output contract — design doc §3a."""

    status: str = "ok"  # "ok" | "needs_clarification" | "failed"
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    needs_approval: bool = False
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""


class ChatMessageList(BaseModel):
    messages: list[ChatMessage]


class StarMessageRequest(BaseModel):
    starred: bool = True


class ConnectorStatus(BaseModel):
    """Live Kafka Connect status for one connector, reduced to the traffic-light
    color the Pipeline Graph view actually needs."""

    color: str  # "green" | "red" | "orange" | "grey"
    state: str | None = None  # raw Connect state: RUNNING/FAILED/PAUSED/UNASSIGNED
    failed_tasks: int = 0
    total_tasks: int = 0
    detail: str | None = None  # set when the live lookup itself failed


class PipelineGraphNode(BaseModel):
    """One node in the Pipeline Graph view. `type` drives the frontend's color
    coding: "source_connector"/"sink_connector" (colored by `connector_status`,
    not `type`), "topic" (one shared color), "ksql_stream"/"ksql_table" (one
    color each)."""

    id: str
    name: str
    type: str
    artifact_id: str | None = None
    # Connector nodes: "source"/"sink" (Artifact.phase). ksqlDB nodes: "raw"/
    # "aggregate"/"join" (content.layer). Topic nodes: None.
    phase: str | None = None
    # Artifact.status ("proposed"/"committed") for connector/ksqlDB nodes; None
    # for topic nodes, which aren't independently approved.
    status: str | None = None
    # The CREATE STREAM/TABLE statement, ksqlDB nodes only.
    statement: str | None = None
    connector_status: ConnectorStatus | None = None


class PipelineGraphEdge(BaseModel):
    source: str
    target: str


class PipelineGraph(BaseModel):
    nodes: list[PipelineGraphNode] = Field(default_factory=list)
    edges: list[PipelineGraphEdge] = Field(default_factory=list)
