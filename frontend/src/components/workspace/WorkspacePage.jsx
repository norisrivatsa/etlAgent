import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { api } from '../../api/client'
import {
  AGENT_DEFS,
  deriveActiveEdges,
  deriveAgentJson,
  deriveNodeStates,
  deriveStageProgress,
  deriveTaskHistory,
} from '../../lib/agentGraph'
import { ChatThread } from '../chat/ChatThread'
import '../chat/chat.css'
import { GraphCanvas } from '../graph/GraphCanvas'
import '../graph/graph.css'
import { GraphViewSwitcher } from '../graph/GraphViewSwitcher'
import { NodeDrawer } from '../graph/NodeDrawer'
import { PipelineArtifactDrawer } from '../graph/PipelineArtifactDrawer'
import { PipelineBar } from '../graph/PipelineBar'
import { PipelineGraphCanvas } from '../graph/PipelineGraphCanvas'
import './workspace.css'

const EVENTS_POLL_MS = 2500

const NODES_BY_ID = Object.fromEntries(AGENT_DEFS.map((d) => [d.id, d]))

export function WorkspacePage() {
  const navigate = useNavigate()
  const { sessionId, sessions, currentSession, refreshCurrentSession, openNewSession } = useOutletContext()

  const [events, setEvents] = useState([])
  const [graphView, setGraphView] = useState('agent')
  const [selectedNodeId, setSelectedNodeId] = useState(null)
  const [selectedPipelineNode, setSelectedPipelineNode] = useState(null)
  const [pipelineRefreshToken, setPipelineRefreshToken] = useState(0)
  const [focusedArtifact, setFocusedArtifact] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const refreshEvents = useCallback(async () => {
    if (!sessionId) return
    try {
      const result = await api.getEvents(sessionId, null, 200)
      setEvents(result.events || [])
    } catch (err) {
      console.error('Failed to load events:', err)
    }
  }, [sessionId])

  useEffect(() => {
    async function loadInitialEvents() {
      if (!sessionId) {
        setEvents([])
        return
      }
      try {
        const result = await api.getEvents(sessionId, null, 200)
        setEvents(result.events || [])
      } catch (err) {
        console.error('Failed to load events:', err)
      }
    }
    loadInitialEvents()
    const timer = window.setInterval(refreshEvents, EVENTS_POLL_MS)
    return () => window.clearInterval(timer)
  }, [sessionId, refreshEvents])

  const nodeStates = useMemo(() => deriveNodeStates(events), [events])
  const activeEdgeKeys = useMemo(
    () => new Set(deriveActiveEdges(nodeStates).map(([from, to]) => `${from}->${to}`)),
    [nodeStates],
  )
  const stageProgress = useMemo(() => deriveStageProgress(currentSession), [currentSession])

  const selectedDef = selectedNodeId ? NODES_BY_ID[selectedNodeId] : null
  const selectedState = selectedNodeId ? nodeStates[selectedNodeId] : null
  const selectedHistory = selectedNodeId ? deriveTaskHistory(events, selectedNodeId) : []
  const selectedJson = selectedNodeId
    ? deriveAgentJson(selectedNodeId, { nodeState: selectedState, whiteboard: currentSession?.whiteboard })
    : null

  const selectedArtifact = selectedPipelineNode?.artifact_id
    ? (currentSession?.whiteboard?.artifacts || []).find(
        (a) => a.artifact_id === selectedPipelineNode.artifact_id,
      )
    : null

  async function runAction(label, action) {
    setBusy(label)
    setError('')
    try {
      await action()
      await Promise.all([refreshCurrentSession(), refreshEvents()])
      setPipelineRefreshToken((token) => token + 1)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  const handleApprove = (approved) =>
    runAction(approved ? 'Generating artifacts' : 'Rejecting plan', () => api.approveSession(sessionId, approved))
  const handleDeploy = (mode) => runAction('Deploying', () => api.deploySession(sessionId, mode))
  const handleVerify = (payload) => runAction('Verifying', () => api.verifySession(sessionId, payload))
  const handleArtifactApprove = (artifactId, approved) =>
    runAction(approved ? 'Committing artifact' : 'Rejecting artifact', () =>
      api.approveArtifact(sessionId, artifactId, approved),
    ).then(() => setSelectedPipelineNode(null))
  const handleFocusChat = (artifact) => {
    setFocusedArtifact(artifact)
    setSelectedPipelineNode(null)
  }

  if (!sessionId) {
    return (
      <div className="chat-empty">
        <h2>No session selected</h2>
        <p>Create a new session or select an existing one to start chatting.</p>
        <button type="button" className="btn-primary" onClick={openNewSession}>
          Create New Session
        </button>
        {sessions.length > 0 && (
          <div className="chat-empty-sessions raised">
            <h3>Existing sessions</h3>
            {sessions.map((session) => (
              <button
                type="button"
                key={session.session_id}
                className="chat-empty-session-row"
                onClick={() => navigate(`/session/${session.session_id}`)}
              >
                <span className="chat-empty-session-name">{session.pipeline_name}</span>
                <span className="chat-empty-session-status">{session.status}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="workspace-wrap">
      <div className="workspace-chat-pane">
        <div className="chat-wrap">
          <ChatThread
            sessionId={sessionId}
            focusedArtifact={focusedArtifact}
            onClearFocus={() => setFocusedArtifact(null)}
          />
        </div>
      </div>

      <div className="graph-wrap workspace-graph-pane">
        <PipelineBar
          stageIndex={stageProgress.index}
          failed={stageProgress.failed}
          session={currentSession}
          busy={busy}
          onApprove={handleApprove}
          onDeploy={handleDeploy}
          onVerify={handleVerify}
        />
        {error && <div className="graph-error">{error}</div>}

        {graphView === 'agent' ? (
          <GraphCanvas
            nodesById={NODES_BY_ID}
            nodeStates={nodeStates}
            activeEdgeKeys={activeEdgeKeys}
            onSelectNode={setSelectedNodeId}
          />
        ) : (
          <PipelineGraphCanvas
            sessionId={sessionId}
            refreshToken={pipelineRefreshToken}
            onSelectNode={setSelectedPipelineNode}
          />
        )}

        <GraphViewSwitcher value={graphView} onChange={setGraphView} />
      </div>

      {selectedDef && (
        <NodeDrawer
          def={selectedDef}
          nodeState={selectedState}
          history={selectedHistory}
          jsonData={selectedJson}
          onClose={() => setSelectedNodeId(null)}
        />
      )}

      {selectedPipelineNode && (
        <PipelineArtifactDrawer
          node={selectedPipelineNode}
          artifact={selectedArtifact}
          busy={Boolean(busy)}
          onApproveArtifact={handleArtifactApprove}
          onFocusChat={handleFocusChat}
          onClose={() => setSelectedPipelineNode(null)}
        />
      )}
    </div>
  )
}
