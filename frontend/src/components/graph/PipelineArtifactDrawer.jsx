import { ScrollArea } from '../common/ScrollArea'
import { DrawerJsonTab } from './DrawerJsonTab'

const STATUS_LABEL = {
  proposed: 'Pending approval',
  committed: 'Committed',
  rejected: 'Rejected',
}

/**
 * Click-through drawer for one Pipeline Graph node (a connector or ksqlDB
 * artifact). Approve/Reject act on just this artifact; the phase only
 * clears once every artifact in it has been resolved (see
 * Orchestrator.handle_artifact_approval). "Message Planner about this"
 * scopes the next chat message to this artifact, so a request like "change
 * the poll interval" revises only it instead of the whole plan.
 */
export function PipelineArtifactDrawer({ artifact, busy, onApproveArtifact, onFocusChat, onClose }) {
  const pending = artifact.status === 'proposed'
  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <div className="node-drawer">
        <div className="drawer-header">
          <div>
            <div className="drawer-title">{artifact.name}</div>
            <div className="drawer-subtitle">{STATUS_LABEL[artifact.status] ?? artifact.status}</div>
          </div>
          <button type="button" className="drawer-close raised-sm" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <ScrollArea className="drawer-body">
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
          <DrawerJsonTab data={artifact.content} />
        </ScrollArea>
      </div>
    </>
  )
}
