/**
 * Data + derivation for the Agent Graph view.
 *
 * Node ids match the backend's agent registry (`build_agents()` in
 * backend/app/agents.py) exactly, plus a synthetic "whiteboard" node for the
 * shared state hub every agent reads from and writes to. Keeping the ids in
 * sync with the backend is what lets deriveNodeStates() below map raw
 * SessionEvent records onto the right node without any backend changes.
 */

// -- Static layout -----------------------------------------------------

export const CANVAS_WIDTH = 900
export const CANVAS_HEIGHT = 860

export const AGENT_DEFS = [
  { id: 'planner', name: 'Planner', role: 'Requirements & plan', x: 40, y: 300, w: 170, h: 140 },
  { id: 'connect', name: 'Connect', role: 'Kafka Connect specialist', x: 360, y: 40, w: 170, h: 140 },
  { id: 'ksqldb', name: 'KsqlDB', role: 'Streaming SQL specialist', x: 360, y: 300, w: 170, h: 140 },
  { id: 'edge_case', name: 'EdgeCase', role: 'Reliability reviewer', x: 360, y: 560, w: 170, h: 140 },
  { id: 'evaluator', name: 'Evaluator', role: 'Reviews & approves', x: 680, y: 300, w: 170, h: 140 },
  { id: 'executor', name: 'Executor', role: 'Deploys artifacts', x: 960, y: 300, w: 170, h: 140 },
  { id: 'verification', name: 'Verification', role: 'Health & correctness', x: 1220, y: 140, w: 170, h: 140 },
  { id: 'debug', name: 'Debug', role: 'Ad hoc diagnostics', x: 1220, y: 460, w: 170, h: 140 },
  { id: 'whiteboard', name: 'Whiteboard', role: 'Shared state hub', x: 610, y: 680, w: 260, h: 150 },
]

export const EDGE_DEFS = [
  { from: 'planner', to: 'connect' },
  { from: 'planner', to: 'ksqldb' },
  { from: 'planner', to: 'edge_case' },
  { from: 'connect', to: 'evaluator' },
  { from: 'ksqldb', to: 'evaluator' },
  { from: 'edge_case', to: 'evaluator' },
  { from: 'evaluator', to: 'executor' },
  { from: 'executor', to: 'verification' },
  { from: 'executor', to: 'debug', dashed: true },
  { from: 'verification', to: 'debug', dashed: true },
  { from: 'planner', to: 'whiteboard', hub: true },
  { from: 'connect', to: 'whiteboard', hub: true },
  { from: 'ksqldb', to: 'whiteboard', hub: true },
  { from: 'edge_case', to: 'whiteboard', hub: true },
  { from: 'evaluator', to: 'whiteboard', hub: true },
  { from: 'executor', to: 'whiteboard', hub: true },
  { from: 'verification', to: 'whiteboard', hub: true },
  { from: 'debug', to: 'whiteboard', hub: true },
]

// SVG shape descriptors per node, drawn inside an 18x18 icon slot.
export const ICONS = {
  planner: [
    { isCircle: true, cx: 12, cy: 12, r: 8 },
    { isLine: true, x1: 12, y1: 12, x2: 16, y2: 8 },
  ],
  connect: [
    { isRect: true, x: 7, y: 6, w: 10, h: 8, rx: 2 },
    { isLine: true, x1: 9, y1: 6, x2: 9, y2: 2 },
    { isLine: true, x1: 15, y1: 6, x2: 15, y2: 2 },
    { isLine: true, x1: 12, y1: 14, x2: 12, y2: 21 },
  ],
  ksqldb: [
    { isEllipse: true, cx: 12, cy: 7, rx: 7, ry: 3 },
    { isLine: true, x1: 5, y1: 7, x2: 5, y2: 17 },
    { isLine: true, x1: 19, y1: 7, x2: 19, y2: 17 },
    { isEllipse: true, cx: 12, cy: 17, rx: 7, ry: 3 },
  ],
  edge_case: [
    { isPath: true, d: 'M12 3 L19 6 V12 C19 17 15.8 20 12 21 C8.2 20 5 17 5 12 V6 Z', fill: 'none' },
    { isPath: true, d: 'M9 12 L11 14 L15 9', fill: 'none' },
  ],
  evaluator: [
    { isCircle: true, cx: 12, cy: 12, r: 8 },
    { isPath: true, d: 'M8 12 L11 15 L16 9', fill: 'none' },
  ],
  executor: [{ isPath: true, d: 'M8 5 L18 12 L8 19 Z', fill: 'currentColor' }],
  verification: [
    { isPath: true, d: 'M12 2 L19 5 V11 C19 16 15.8 19.5 12 21 C8.2 19.5 5 16 5 11 V5 Z', fill: 'none' },
    { isPath: true, d: 'M8.5 12 L11 14.5 L15.5 9', fill: 'none' },
  ],
  debug: [
    { isCircle: true, cx: 7, cy: 7, r: 3 },
    { isCircle: true, cx: 17, cy: 17, r: 3 },
    { isLine: true, x1: 9.2, y1: 9.2, x2: 14.8, y2: 14.8 },
  ],
  whiteboard: [
    { isRect: true, x: 4, y: 4, w: 16, h: 16, rx: 2 },
    { isLine: true, x1: 4, y1: 10, x2: 20, y2: 10 },
    { isLine: true, x1: 10, y1: 10, x2: 10, y2: 20 },
  ],
}

// The instruction string each agent is invoked with — read straight off
// backend/app/services.py's runtime.submit() call sites. The backend runs a
// fixed pipeline today (see SessionService), so each agent is always given
// the exact same instruction; this is not a guess. "debug" has no caller
// yet — DebugAgent exists in build_agents() but no service method submits
// to it, so it never leaves "Idle" in the current backend.
export const AGENT_INSTRUCTIONS = {
  planner: 'Gather requirements and update the pipeline plan',
  connect: 'Generate connector configurations',
  ksqldb: 'Generate ksqlDB statements',
  edge_case: 'Review pipeline failure modes',
  evaluator: 'Review generated pipeline artifacts',
  executor: 'Deploy connector and ksqlDB artifacts',
  verification: 'Verify deployed pipeline health and correctness',
  debug: 'Not yet wired to an API action',
}

// -- Stage stepper -------------------------------------------------------

// Mirrors backend/app/models.py SessionStatus, in pipeline order. FAILED is
// rendered as an overlay on whichever stage was in flight, not a step here.
export const STAGE_LABELS = [
  'Requirements',
  'Planning',
  'Awaiting Approval',
  'Generating',
  'Ready',
  'Deploying',
  'Deployed',
  'Verifying',
  'Healthy',
]

const STATUS_TO_STAGE_INDEX = {
  requirements: 0,
  planning: 1,
  awaiting_approval: 2,
  generating: 3,
  ready: 4,
  deploying: 5,
  deployed: 6,
  verifying: 7,
  healthy: 8,
}

/**
 * SessionState doesn't retain stage history, so when status is "failed" we
 * infer which stage was in flight from whatever whiteboard artifacts exist.
 */
export function deriveStageProgress(session) {
  if (!session) return { index: 0, failed: false }
  if (session.status !== 'failed') {
    return { index: STATUS_TO_STAGE_INDEX[session.status] ?? 0, failed: false }
  }
  const board = session.whiteboard || {}
  if (board.verification_status?.state && board.verification_status.state !== 'not_started') {
    return { index: STATUS_TO_STAGE_INDEX.verifying, failed: true }
  }
  if (board.deployment_status?.state && board.deployment_status.state !== 'not_started') {
    return { index: STATUS_TO_STAGE_INDEX.deploying, failed: true }
  }
  if ((board.connectors || []).length > 0 || (board.ksqldb_objects || []).length > 0) {
    return { index: STATUS_TO_STAGE_INDEX.generating, failed: true }
  }
  return { index: STATUS_TO_STAGE_INDEX.requirements, failed: true }
}

// -- Edge geometry ---------------------------------------------------------

export function edgePath(a, b) {
  const x1 = a.x + a.w / 2
  const y1 = a.y + a.h / 2
  const x2Center = b.x + b.w / 2
  const y2Center = b.y + b.h / 2
  // Pull the endpoint back from the target's center to just outside its
  // rectangular border (not a circular approximation — a fixed radius isn't
  // enough to clear a wide/short card on a diagonal approach, which left the
  // endpoint, and any arrowhead marker on it, rendered UNDER the node's
  // opaque background instead of next to it), so it's actually visible.
  const ddx = x1 - x2Center
  const ddy = y1 - y2Center
  const halfW = b.w / 2
  const halfH = b.h / 2
  const scaleX = ddx !== 0 ? halfW / Math.abs(ddx) : Infinity
  const scaleY = ddy !== 0 ? halfH / Math.abs(ddy) : Infinity
  const scale = Math.min(scaleX, scaleY)
  const boundaryX = x2Center + ddx * scale
  const boundaryY = y2Center + ddy * scale
  const dist = Math.hypot(ddx, ddy) || 1
  const gap = 6
  const x2 = boundaryX + (ddx / dist) * gap
  const y2 = boundaryY + (ddy / dist) * gap
  const midX = (x1 + x2) / 2
  return `M ${x1} ${y1} C ${midX} ${y1} ${midX} ${y2} ${x2} ${y2}`
}

// -- Node state derivation from SessionEvent[] ------------------------------

const AGENT_IDS = AGENT_DEFS.filter((a) => a.id !== 'whiteboard').map((a) => a.id)

/**
 * Reduces a session's raw event log into a live status per agent.
 *
 * The backend emits an EventType.TASK/"pending" event when a task is queued
 * (data.agent identifies the target), then either an EventType.TASK/
 * "completed" event or an EventType.ERROR event when it finishes (see
 * backend/app/runtime.py `_run_tasks`). There's no explicit "in_progress"
 * event, so an agent counts as "working" whenever its most recent task has a
 * "pending" event with no completed/error event for that same task_id yet.
 */
export function deriveNodeStates(events) {
  const byAgent = Object.fromEntries(AGENT_IDS.map((id) => [id, { state: 'idle', taskId: null, at: null, error: null }]))

  const sorted = [...(events || [])].sort((a, b) => new Date(a.created_at) - new Date(b.created_at))

  for (const event of sorted) {
    if (event.type === 'task') {
      const agentId = event.data?.agent
      if (!agentId || !(agentId in byAgent)) continue
      if (event.data.status === 'pending') {
        byAgent[agentId] = { state: 'working', taskId: event.data.task_id, at: event.created_at, error: null }
      } else if (event.data.status === 'completed') {
        byAgent[agentId] = { state: 'success', taskId: event.data.task_id, at: event.created_at, error: null }
      }
    } else if (event.type === 'error') {
      const agentId = event.data?.agent || event.source
      if (!agentId || !(agentId in byAgent)) continue
      byAgent[agentId] = { state: 'error', taskId: event.data?.task_id ?? null, at: event.created_at, error: event.data?.error }
    } else if (event.type === 'agent_message' && event.source === 'planner') {
      // The Planner never goes through run_phase, so it never gets "task" events —
      // an agent_message reply is the only signal that it's back to succeeding after
      // a prior error. The backend emits this reply strictly before the ERROR event
      // on a failed turn, so a real failure is never immediately masked by this.
      byAgent.planner = { state: 'success', taskId: null, at: event.created_at, error: null }
    }
  }

  const anyWorking = Object.values(byAgent).some((entry) => entry.state === 'working')

  const result = {}
  for (const id of AGENT_IDS) {
    const entry = byAgent[id]
    result[id] = {
      state: entry.state,
      statusLabel: statusLabelFor(entry.state),
      task: entry.state === 'working' ? AGENT_INSTRUCTIONS[id] : entry.state === 'error' ? entry.error || '' : '',
      updatedAt: entry.at,
    }
  }
  result.whiteboard = {
    state: anyWorking ? 'working' : 'idle',
    statusLabel: anyWorking ? 'Receiving updates' : 'Idle',
    task: '',
    updatedAt: null,
  }
  return result
}

function statusLabelFor(state) {
  switch (state) {
    case 'working':
      return 'Working'
    case 'success':
      return 'Completed'
    case 'error':
      return 'Failed'
    default:
      return 'Idle'
  }
}

/**
 * An edge lights up while a message/task is actually in flight along it:
 * either into a currently-working agent, or from a currently-working agent
 * into the shared whiteboard hub.
 */
export function deriveActiveEdges(nodeStates) {
  return EDGE_DEFS.filter((edge) => {
    if (edge.to === 'whiteboard') {
      return nodeStates[edge.from]?.state === 'working'
    }
    return nodeStates[edge.to]?.state === 'working'
  }).map((edge) => [edge.from, edge.to])
}

// -- Task history + raw JSON for the node drawer ----------------------------

/** Newest-first list of this agent's finished tasks, from the event log. */
export function deriveTaskHistory(events, agentId) {
  return (events || [])
    .filter((event) => {
      if (event.type === 'task' && event.data?.status === 'completed') return event.data.agent === agentId
      if (event.type === 'error') return (event.data?.agent || event.source) === agentId
      return false
    })
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    .slice(0, 20)
    .map((event) => ({
      id: event.event_id,
      label: AGENT_INSTRUCTIONS[agentId] || event.type,
      time: event.created_at,
      state: event.type === 'error' ? 'error' : 'success',
    }))
}

// Which slice of the shared whiteboard each agent is responsible for —
// mirrors how SessionService.approve()/message() write agent output back
// onto state.whiteboard.
function whiteboardSliceFor(agentId, whiteboard) {
  const board = whiteboard || {}
  switch (agentId) {
    case 'planner':
      return { requirements: board.requirements, plan: board.plan }
    case 'connect':
      return { connectors: board.connectors }
    case 'ksqldb':
      return { ksqldb_objects: board.ksqldb_objects }
    case 'edge_case':
      return { edge_cases: board.evaluation?.edge_cases }
    case 'evaluator':
      return { findings: board.evaluation?.findings, approved: board.evaluation?.approved }
    case 'executor':
      return { deployment_status: board.deployment_status }
    case 'verification':
      return { verification_status: board.verification_status }
    case 'whiteboard':
      return board
    default:
      return {}
  }
}

/**
 * Best-effort "raw JSON" for the drawer's Raw JSON tab. There's no
 * per-task-detail endpoint on the backend yet, so this is assembled from
 * what IS persisted: the fixed instruction the agent was invoked with, its
 * live status from the event log, and whichever slice of the whiteboard
 * that agent is responsible for.
 */
export function deriveAgentJson(agentId, { nodeState, whiteboard }) {
  return {
    agent: agentId,
    instruction: AGENT_INSTRUCTIONS[agentId] ?? null,
    status: nodeState?.state ?? 'idle',
    error: nodeState?.state === 'error' ? nodeState.task : null,
    updated_at: nodeState?.updatedAt ?? null,
    output: whiteboardSliceFor(agentId, whiteboard),
  }
}
