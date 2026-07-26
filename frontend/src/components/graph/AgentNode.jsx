import { ICONS } from '../../lib/agentGraph'
import { AgentIcon } from './AgentIcon'

function StatusGlyph({ state }) {
  if (state === 'working') {
    return (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" className="agent-node-spinner">
        <path d="M12 3a9 9 0 1 1-6.36 2.64" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      </svg>
    )
  }
  if (state === 'error') {
    return (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
        <path d="M12 4L2 20h20L12 4Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
        <line x1="12" y1="10" x2="12" y2="14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    )
  }
  if (state === 'success') {
    return (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path d="M8 12l3 3 5-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  return <div className="agent-node-idle-dot" />
}

const SHADOW_CLASS = { idle: 'raised', working: 'ring-indigo', error: 'ring-error', success: 'ring-success' }

export function AgentNode({ def, nodeState, onClick }) {
  const state = nodeState?.state ?? 'idle'
  const isHub = def.id === 'whiteboard'

  return (
    <div
      className={`agent-node ${SHADOW_CLASS[state]} agent-node--${state}${isHub ? ' agent-node--hub' : ''}`}
      style={{ left: def.x, top: def.y, width: def.w, height: def.h }}
      onClick={onClick}
      role="button"
      tabIndex={0}
    >
      <div className="agent-node-top-row">
        <div className="agent-node-icon pressed">
          <AgentIcon shapes={ICONS[def.id]} />
        </div>
        <div className="agent-node-status-glyph">
          <StatusGlyph state={state} />
        </div>
      </div>
      <div className="agent-node-name">{def.name}</div>
      <div className="agent-node-role">{def.role}</div>
      <div className="agent-node-status-label">{nodeState?.statusLabel ?? 'Idle'}</div>
      {nodeState?.task && <div className="agent-node-task pressed">{nodeState.task}</div>}
    </div>
  )
}
