# UI Chat Integration

This plan integrates assistant-ui into the ETL agent frontend while preserving the
backend-owned session, MongoDB persistence, whiteboard, events, and task runtime.

## Architecture Decision

Use `ExternalStoreRuntime`, not `LocalRuntime`.

The backend already owns sessions, messages, events, task execution, MongoDB
persistence, and whiteboard state. assistant-ui's `ExternalStoreRuntime` is the
better fit because the app will continue to own message state and persistence,
while assistant-ui renders the thread and composer.

`LocalRuntime` is better when assistant-ui owns local chat state and the backend
is only a simple model-call endpoint. That is not this app's architecture.

Relevant assistant-ui docs:

- https://www.assistant-ui.com/docs/runtimes/custom/external-store
- https://www.assistant-ui.com/docs/runtimes/custom/local-runtime
- https://www.assistant-ui.com/docs/runtimes/concepts/threads
- https://www.assistant-ui.com/docs/architecture

## Goals

- Show a real chat transcript, not only event rows.
- Let users continue existing MongoDB sessions.
- Keep the whiteboard, plan, deployment status, verification status, and events
  visible beside the chat.
- Keep events as operational audit/progress records.
- Store user and assistant chat messages as first-class persisted records.
- Preserve compatibility with the current API during migration.

## Backend Plan

### 1. Add Chat Models

Add first-class chat message models separate from raw events.

Proposed shape:

```json
{
  "message_id": "...",
  "session_id": "...",
  "role": "user | assistant | system",
  "content": "text",
  "agent": "planner",
  "metadata": {
    "task_id": "...",
    "event_id": "...",
    "status": "complete | failed"
  },
  "created_at": "..."
}
```

Add:

- `ChatMessage`
- `ChatMessageList`
- possibly `ChatRole`

### 2. Extend Repository Contract

Extend `StateRepository` with:

- `add_chat_message(message)`
- `list_chat_messages(session_id, limit)`

Implement both methods in:

- `MongoStateRepository`
- `InMemoryStateRepository`

Add MongoDB indexes:

- `chat_messages.session_id + created_at`
- optional `chat_messages.role`

### 3. Add Message APIs

Add:

- `GET /sessions/{session_id}/messages`
- `POST /sessions/{session_id}/messages`

`GET /sessions/{session_id}/messages` returns persisted chat messages in
chronological order.

`POST /sessions/{session_id}/messages` should:

1. Store the user message.
2. Submit the planner task.
3. Store the assistant reply if the planner succeeds.
4. Store an assistant error message if the planner fails.
5. Return the updated session, messages, task list, and recent events.

Keep the existing `POST /sessions/{session_id}/message` endpoint as a
compatibility wrapper until the frontend fully migrates.

### 4. Add Combined Session State API

Optional but recommended:

- `GET /sessions/{session_id}/state`

Return:

- `session`
- `messages`
- `events`
- `whiteboard`

This reduces frontend boot/reopen flows from three requests to one.

### 5. Backfill Existing Sessions

Existing MongoDB sessions may only have events, not chat messages.

Add a lazy fallback in `GET /sessions/{session_id}/messages`:

- Convert `USER_MESSAGE` events into user chat messages.
- Convert `AGENT_MESSAGE` events with `reply` into assistant chat messages.
- Do not duplicate messages if real chat messages already exist.

This lets old sessions become readable without a manual migration script.

### 6. Backend Tests

Add tests for:

- Creating a chat message stores the user message.
- Planner response stores an assistant message.
- Failed planner task stores an assistant error message.
- Listing messages returns chronological order.
- Existing event-only sessions produce fallback chat messages.
- Existing `POST /sessions/{id}/message` still works.
- `GET /sessions` still lists Mongo-backed sessions for continuation.

## Frontend Plan

### 1. Install assistant-ui

Install:

- `@assistant-ui/react`
- `@assistant-ui/react-markdown`
- likely `zustand`

Use assistant-ui's Vite-compatible React packages. Avoid assuming Next.js
conventions.

### 2. Add API Client Helpers

Create a small API module for:

- `listSessions()`
- `createSession()`
- `getSessionState(sessionId)`
- `listMessages(sessionId)`
- `sendMessage(sessionId, content)`
- `approveSession(sessionId, approved)`
- `deploySession(sessionId, mode)`
- `verifySession(sessionId, request)`

The chat UI should call the new plural message endpoint:

```text
POST /sessions/{session_id}/messages
```

### 3. Create assistant-ui Runtime Adapter

Create:

```text
frontend/src/chat/KafkaAgentRuntimeProvider.jsx
```

Use `useExternalStoreRuntime`.

Frontend-owned state:

- `session`
- `messages`
- `events`
- `busy`
- `error`

Adapter responsibilities:

- Convert backend `ChatMessage` records into assistant-ui message objects.
- Send new user messages through `POST /sessions/{id}/messages`.
- Update session, messages, events, and whiteboard state after each response.
- Surface backend errors as assistant messages and UI alerts.

### 4. Thread List / Session Continuation

Use `GET /sessions?limit=50` to populate existing sessions.

Selecting a session should load:

- `GET /sessions/{id}/state`, or
- parallel calls to:
  - `GET /sessions/{id}`
  - `GET /sessions/{id}/messages`
  - `GET /sessions/{id}/events?limit=50`

New thread/session flow:

1. User clicks new session.
2. Frontend calls `POST /sessions`.
3. Frontend switches assistant-ui to that session/thread.

### 5. Layout

Recommended layout:

- Left sidebar: session/thread list.
- Center: assistant-ui chat thread and composer.
- Right panel: whiteboard, events, deployment, verification.

Do not hide operational state behind chat. Users should be able to chat while
watching the whiteboard and events update.

### 6. Preserve Operational Controls

Keep or relocate:

- Approve / reject.
- Deploy package/apply.
- Verify.
- Topic expected count inputs.

These controls should remain outside the chat composer so the workflow remains
explicit and auditable.

### 7. Event and Task Rendering

Use events for operational progress:

- task pending / in progress / completed
- approval
- deployment
- verification
- errors

Use chat messages for user and assistant conversation:

- user requirements
- planner replies
- assistant error summaries

Do not rely on event rows as the primary chat transcript.

### 8. Streaming Later

First integration should be non-streaming because the current backend waits for
the planner task to finish before returning.

Future streaming work:

- Add SSE or assistant-ui data-stream endpoint.
- Stream task progress as events.
- Stream assistant text only after the LLM client supports incremental output.
- Consider resumable streams after basic chat persistence works.

## Implementation Task Order

1. Add backend `ChatMessage`, `ChatMessageList`, and role models.
2. Add repository methods and Mongo indexes for chat messages.
3. Add `GET /sessions/{id}/messages`.
4. Add lazy event-to-message fallback for existing Mongo sessions.
5. Add `POST /sessions/{id}/messages`.
6. Keep `POST /sessions/{id}/message` as a compatibility wrapper.
7. Add backend tests for message creation, listing, fallback, and failures.
8. Add optional `GET /sessions/{id}/state` combined endpoint.
9. Install assistant-ui frontend dependencies.
10. Create frontend API client helpers.
11. Create `KafkaAgentRuntimeProvider` using `useExternalStoreRuntime`.
12. Replace the current requirement textarea/send controls with assistant-ui
    thread and composer.
13. Wire existing Mongo sessions into the thread/session list.
14. Rework layout into session list, chat thread, and operational side panel.
15. Preserve approve, deploy, and verify controls.
16. Add frontend error handling for failed planner/Ollama calls.
17. Run backend tests.
18. Run frontend build.
19. Manually verify:
    - create new session
    - send message
    - see assistant reply in chat
    - refresh browser and continue same session
    - reopen older MongoDB session
    - approve/deploy/verify still update whiteboard and events

## Acceptance Criteria

- Existing MongoDB sessions are visible and reopenable in the frontend.
- Reopened sessions show user and assistant chat history.
- New messages appear in the assistant-ui thread.
- Planner replies appear as assistant messages, not only event entries.
- Events remain visible as operational timeline entries.
- Whiteboard and plan panels update after chat responses.
- Approval, deployment, and verification workflows still work.
- Backend tests and frontend build pass.
