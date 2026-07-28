import { ScrollArea } from '../common/ScrollArea'
import { DrawerJsonTab } from './DrawerJsonTab'

const TYPE_LABEL = {
  source_connector: 'Source connector',
  sink_connector: 'Sink connector',
  topic: 'Topic',
  ksql_stream: 'ksqlDB stream',
  ksql_table: 'ksqlDB table',
}

const STATUS_LABEL = {
  proposed: 'Pending approval',
  committed: 'Committed',
}

const CONNECTOR_STATUS_LABEL = {
  green: 'Running',
  red: 'Failed',
  orange: 'Running — some tasks failed',
  grey: 'Not deployed yet',
}

/**
 * Click-through drawer for one Pipeline Graph node — a source/sink connector,
 * a topic, or a ksqlDB stream/table. `node` is the graph node itself (name,
 * type, live connector_status, statement); `artifact` is the matching
 * Whiteboard.artifact for connector/ksqlDB nodes (null for topics, which
 * have no backing artifact — they're declared by the Planner, not proposed
 * for approval). Approve/Reject act on just this artifact; the phase only
 * clears once every artifact in it has been resolved (see
 * Orchestrator.handle_artifact_approval). "Message Planner about this"
 * scopes the next chat message to this artifact, so a request like "change
 * the poll interval" revises only it instead of the whole plan.
 */
export function PipelineArtifactDrawer({ node, artifact, busy, onApproveArtifact, onFocusChat, onClose }) {
  const pending = artifact?.status === 'proposed'
  const isConnector = node.type === 'source_connector' || node.type === 'sink_connector'
  const isKsql = node.type === 'ksql_stream' || node.type === 'ksql_table'

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <div className="node-drawer">
        <div className="drawer-header">
          <div>
            <div className="drawer-title">{node.name}</div>
            <div className="drawer-subtitle">
              {TYPE_LABEL[node.type] ?? node.type}
              {artifact && STATUS_LABEL[artifact.status] ? ` · ${STATUS_LABEL[artifact.status]}` : ''}
            </div>
          </div>
          <button type="button" className="drawer-close raised-sm" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <ScrollArea className="drawer-body">
          {isConnector && (
            <div className={`pipeline-drawer-status pipeline-drawer-status--${node.connector_status?.color ?? 'grey'}`}>
              <span className="pipeline-drawer-status-dot" />
              {/* `detail` carries the specific reason for grey (not deployed
                  yet vs. a live lookup failure, e.g. Connect unreachable) —
                  prefer it over the generic per-color label so those two
                  very different situations don't look identical. */}
              <span>
                {node.connector_status?.detail ?? CONNECTOR_STATUS_LABEL[node.connector_status?.color] ?? 'Unknown'}
              </span>
              {node.connector_status?.total_tasks > 0 && (
                <span className="pipeline-drawer-status-tasks">
                  {node.connector_status.total_tasks - node.connector_status.failed_tasks}/
                  {node.connector_status.total_tasks} tasks healthy
                </span>
              )}
            </div>
          )}

          {isKsql && node.statement && (
            <div className="pipeline-drawer-statement">
              <div className="pipeline-drawer-statement-label">ksqlDB statement</div>
              <pre className="pipeline-drawer-statement-code">{node.statement}</pre>
            </div>
          )}

          {pending && (
            <div className="pipeline-drawer-actions">
              <div className="pipeline-drawer-actions-row">
                <button
                  type="button"
                  className="btn-primary"
                  disabled={busy}
                  onClick={() => onApproveArtifact(artifact.artifact_id, true)}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="btn-ghost"
                  disabled={busy}
                  onClick={() => onApproveArtifact(artifact.artifact_id, false)}
                >
                  Reject
                </button>
              </div>
              <button
                type="button"
                className="btn-ghost pipeline-drawer-focus-chat"
                disabled={busy}
                onClick={() => onFocusChat(artifact)}
              >
                Message Planner about this
              </button>
            </div>
          )}

          {artifact && <DrawerJsonTab data={artifact.content} />}
        </ScrollArea>
      </div>
    </>
  )
}
