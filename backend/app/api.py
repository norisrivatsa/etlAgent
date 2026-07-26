from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.models import (
    ApprovalRequest,
    ChatMessage,
    ChatMessageList,
    CreateSessionRequest,
    DeployRequest,
    EventList,
    SessionList,
    SessionMessageResponse,
    SessionState,
    StarMessageRequest,
    UserMessageRequest,
    Whiteboard,
)
from app.services import SessionService

router = APIRouter()


async def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


Service = Annotated[SessionService, Depends(get_session_service)]


@router.post(
    "/sessions", response_model=SessionState, status_code=status.HTTP_201_CREATED
)
async def create_session(
    request: CreateSessionRequest, service: Service
) -> SessionState:
    return await service.create_session(request)


@router.get("/sessions", response_model=SessionList)
async def list_sessions(
    service: Service,
    limit: int = Query(default=50, ge=1, le=200),
) -> SessionList:
    return await service.list_sessions(limit)


@router.post("/sessions/{session_id}/message", response_model=SessionMessageResponse)
async def send_message(
    session_id: str, request: UserMessageRequest, service: Service
) -> SessionMessageResponse:
    return await service.message(session_id, request)


@router.post("/sessions/{session_id}/approve", response_model=SessionMessageResponse)
async def approve(
    session_id: str, request: ApprovalRequest, service: Service
) -> SessionMessageResponse:
    return await service.approve(session_id, request)


@router.post("/sessions/{session_id}/deploy", response_model=SessionState)
async def deploy(
    session_id: str, request: DeployRequest, service: Service
) -> SessionState:
    return await service.deploy(session_id, request)


@router.get("/sessions/{session_id}", response_model=SessionState)
async def get_session(session_id: str, service: Service) -> SessionState:
    return await service.get_session(session_id)


@router.get("/sessions/{session_id}/whiteboard", response_model=Whiteboard)
async def get_whiteboard(session_id: str, service: Service) -> Whiteboard:
    return (await service.get_session(session_id)).whiteboard


@router.get("/sessions/{session_id}/events", response_model=EventList)
async def get_events(
    session_id: str,
    service: Service,
    after: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> EventList:
    return await service.events(session_id, after, limit)


@router.get("/sessions/{session_id}/chat-messages", response_model=ChatMessageList)
async def get_chat_messages(
    session_id: str,
    service: Service,
    limit: int = Query(default=100, ge=1, le=1000),
) -> ChatMessageList:
    """Get chat messages (USER_MESSAGE and AGENT_MESSAGE from planner) for a session."""
    return await service.chat_messages(session_id, limit)


@router.post("/sessions/{session_id}/chat-messages", response_model=SessionMessageResponse)
async def send_chat_message(
    session_id: str, request: UserMessageRequest, service: Service
) -> SessionMessageResponse:
    """Send a chat message via planner (same as /message endpoint, chat-friendly)."""
    return await service.message(session_id, request)


@router.post(
    "/sessions/{session_id}/chat-messages/{message_id}/star",
    response_model=ChatMessage,
)
async def star_chat_message(
    session_id: str, message_id: str, request: StarMessageRequest, service: Service
) -> ChatMessage:
    """Star (or unstar) a chat message so it always stays in the Planner's context."""
    return await service.star_message(session_id, message_id, request.starred)


@router.post(
    "/sessions/{session_id}/artifacts/{artifact_id}/approve",
    response_model=SessionMessageResponse,
)
async def approve_artifact(
    session_id: str, artifact_id: str, request: ApprovalRequest, service: Service
) -> SessionMessageResponse:
    """Approve or reject one proposed artifact, independent of the rest of its phase."""
    return await service.approve_artifact(session_id, artifact_id, request)
