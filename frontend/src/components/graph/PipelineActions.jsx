import { useState } from 'react'

export function PipelineActions({ session, busy, onApprove, onDeploy, onVerify }) {
  const [mode, setMode] = useState('package')
  const [expectedTopic, setExpectedTopic] = useState('')
  const [expectedCount, setExpectedCount] = useState('')

  const canApprove = Boolean(session?.pending_approval)
  const canDeploy = ['ready', 'deployed', 'healthy'].includes(session?.status)
  const canVerify = ['deployed', 'healthy'].includes(session?.status)
  const disabled = Boolean(busy)

  return (
    <div className="pipeline-actions">
      <div className="pipeline-actions-group">
        <span className="pipeline-actions-label">Plan</span>
        <button type="button" className="btn-primary" disabled={!canApprove || disabled} onClick={() => onApprove(true)}>
          Approve
        </button>
        <button type="button" className="btn-ghost" disabled={!canApprove || disabled} onClick={() => onApprove(false)}>
          Reject
        </button>
      </div>

      <div className="pipeline-actions-group">
        <span className="pipeline-actions-label">Deploy</span>
        <select
          className="pipeline-actions-select pressed"
          value={mode}
          onChange={(event) => setMode(event.target.value)}
          disabled={disabled}
        >
          <option value="package">Package</option>
          <option value="apply">Apply</option>
        </select>
        <button type="button" className="btn-primary" disabled={!canDeploy || disabled} onClick={() => onDeploy(mode)}>
          Deploy
        </button>
      </div>

      <div className="pipeline-actions-group">
        <span className="pipeline-actions-label">Verify</span>
        <input
          className="pipeline-actions-input pressed"
          placeholder="Topic"
          value={expectedTopic}
          onChange={(event) => setExpectedTopic(event.target.value)}
          disabled={disabled}
        />
        <input
          className="pipeline-actions-input pressed"
          placeholder="Min count"
          type="number"
          min="0"
          value={expectedCount}
          onChange={(event) => setExpectedCount(event.target.value)}
          disabled={disabled}
        />
        <button
          type="button"
          className="btn-primary"
          disabled={!canVerify || disabled}
          onClick={() =>
            onVerify({
              expected_topic_counts:
                expectedTopic && expectedCount ? { [expectedTopic]: Number(expectedCount) } : {},
            })
          }
        >
          Verify
        </button>
      </div>

      {busy && <span className="pipeline-actions-busy">{busy}…</span>}
    </div>
  )
}
