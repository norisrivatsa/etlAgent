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
    verification: AgentModelConfig = Field(default_factory=AgentModelConfig)
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
    VERIFYING = "verifying"
    HEALTHY = "healthy"
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
    VERIFICATION = "verification"
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


class VerificationCheck(BaseModel):
    name: str
    passed: bool | None = None
    status: str = "unknown"
    details: dict[str, Any] = Field(default_factory=dict)


class VerificationStatus(BaseModel):
    state: str = "not_started"
    checks: list[VerificationCheck] = Field(default_factory=list)
    summary: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class Whiteboard(BaseModel):
    requirements: RequirementState = Field(default_factory=RequirementState)
    plan: PipelinePlan = Field(default_factory=PipelinePlan)
    topics: list[dict[str, Any]] = Field(default_factory=list)
    connectors: list[dict[str, Any]] = Field(default_factory=list)
    ksqldb_objects: list[dict[str, Any]] = Field(default_factory=list)
    evaluation: EvaluationState = Field(default_factory=EvaluationState)
    decisions: list[Decision] = Field(default_factory=list)
    deployment_status: DeploymentStatus = Field(default_factory=DeploymentStatus)
    verification_status: VerificationStatus = Field(default_factory=VerificationStatus)
    revision: int = 0
    updated_at: datetime = Field(default_factory=utc_now)


class SessionState(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    pipeline_name: str
    config: SessionConfig = Field(default_factory=SessionConfig)
    whiteboard: Whiteboard = Field(default_factory=Whiteboard)
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
    created_at: datetime = Field(default_factory=utc_now)


class CreateSessionRequest(BaseModel):
    pipeline_name: str = Field(min_length=1, max_length=120)
    config: SessionConfig = Field(default_factory=SessionConfig)
    initial_requirements: dict[str, Any] = Field(default_factory=dict)


class UserMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)


class ApprovalRequest(BaseModel):
    approved: bool
    comment: str | None = Field(default=None, max_length=5000)


class DeployMode(StrEnum):
    PACKAGE = "package"
    APPLY = "apply"


class DeployRequest(BaseModel):
    mode: DeployMode = DeployMode.PACKAGE


class VerificationRequest(BaseModel):
    expected_topic_counts: dict[str, int] = Field(default_factory=dict)
    sink_count_url: str | None = None
    expected_sink_count: int | None = None
    duplicate_check_query: str | None = None
    join_check_query: str | None = None
    offset_sample_seconds: float = Field(default=2.0, ge=0.1, le=60)


class PlannerResponse(BaseModel):
    session: SessionState
    reply: str
    tasks: list[AgentTask] = Field(default_factory=list)


class EventList(BaseModel):
    events: list[SessionEvent]
    next_cursor: datetime | None = None


class PlannerLLMOutput(BaseModel):
    reply: str
    requirements_patch: dict[str, Any] = Field(default_factory=dict)
    plan: PipelinePlan | None = None
    open_questions: list[str] = Field(default_factory=list)
    ready_for_approval: bool = False


class ChatMessage(BaseModel):
    """Chat message view of USER_MESSAGE and AGENT_MESSAGE events."""
    message_id: str
    session_id: str
    role: str  # "user" or "assistant"
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ChatMessageList(BaseModel):
    messages: list[ChatMessage]
