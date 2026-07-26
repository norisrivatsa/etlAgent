import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api } from '../../api/client'
import { ScrollArea } from '../common/ScrollArea'
import { DrawerJsonTab } from '../graph/DrawerJsonTab'
import '../graph/graph.css'
import './whiteboard.css'

const POLL_MS = 4000

const ARTIFACT_STATUS_LABEL = {
  proposed: 'Pending approval',
  committed: 'Committed',
  rejected: 'Rejected',
  superseded: 'Superseded',
}

function Section({ title, children }) {
  return (
    <section className="whiteboard-section raised">
      <h3 className="whiteboard-section-title">{title}</h3>
      {children}
    </section>
  )
}

function EmptyNote({ children }) {
  return <p className="whiteboard-empty">{children}</p>
}

export function WhiteboardPage() {
  const { sessionId, currentSession } = useOutletContext()
  const [whiteboard, setWhiteboard] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    async function loadWhiteboard() {
      if (!sessionId) {
        setWhiteboard(null)
        return
      }
      try {
        setWhiteboard(await api.getWhiteboard(sessionId))
        setError('')
      } catch (err) {
        setError(err.message)
      }
    }
    loadWhiteboard()
    const timer = window.setInterval(loadWhiteboard, POLL_MS)
    return () => window.clearInterval(timer)
  }, [sessionId])

  if (!sessionId) {
    return (
      <div className="whiteboard-page">
        <EmptyNote>No session selected — pick or create a session first.</EmptyNote>
      </div>
    )
  }

  if (!whiteboard) {
    return (
      <div className="whiteboard-page">
        {error ? <div className="graph-error">{error}</div> : <EmptyNote>Loading whiteboard…</EmptyNote>}
      </div>
    )
  }

  const { requirements, plan, artifacts, evaluation, decisions, deployment_status: deployment } = whiteboard
  const decisionsNewestFirst = [...decisions].reverse()

  return (
    <ScrollArea className="whiteboard-page">
      <div className="whiteboard-inner">
        <Section title="Session">
          <div className="whiteboard-header-grid">
            <div>
              <div className="whiteboard-header-label">Pipeline</div>
              <div className="whiteboard-header-value">{currentSession?.pipeline_name ?? '—'}</div>
            </div>
            <div>
              <div className="whiteboard-header-label">Status</div>
              <div className="whiteboard-header-value">{currentSession?.status ?? '—'}</div>
            </div>
            <div>
              <div className="whiteboard-header-label">Pending approval</div>
              <div className="whiteboard-header-value">{currentSession?.pending_approval ?? 'none'}</div>
            </div>
            <div>
              <div className="whiteboard-header-label">Revision</div>
              <div className="whiteboard-header-value">{whiteboard.revision}</div>
            </div>
            <div>
              <div className="whiteboard-header-label">Updated</div>
              <div className="whiteboard-header-value">{new Date(whiteboard.updated_at).toLocaleString()}</div>
            </div>
          </div>
        </Section>

        <Section title="Requirements">
          <DrawerJsonTab data={requirements} />
        </Section>

        <Section title="Plan">
          <DrawerJsonTab data={plan} />
        </Section>

        <Section title={`Artifacts (${artifacts.length})`}>
          {artifacts.length === 0 ? (
            <EmptyNote>No artifacts generated yet.</EmptyNote>
          ) : (
            <div className="whiteboard-artifact-list">
              {artifacts.map((artifact) => (
                <div key={artifact.artifact_id} className="whiteboard-artifact pressed">
                  <div className="whiteboard-artifact-header">
                    <span className="whiteboard-artifact-name">{artifact.name}</span>
                    <span className="whiteboard-artifact-meta">
                      {artifact.kind}
                      {artifact.phase ? ` · ${artifact.phase}` : ''}
                    </span>
                    <span className={`whiteboard-artifact-status whiteboard-artifact-status--${artifact.status}`}>
                      {ARTIFACT_STATUS_LABEL[artifact.status] ?? artifact.status}
                    </span>
                  </div>
                  <DrawerJsonTab data={artifact.content} />
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section title="Evaluation">
          <div className="whiteboard-eval-approved">
            Approved:{' '}
            <span className={evaluation.approved ? 'whiteboard-approved-yes' : 'whiteboard-approved-no'}>
              {evaluation.approved ? 'Yes' : 'No'}
            </span>
          </div>
          <div className="whiteboard-eval-columns">
            <div>
              <h4 className="whiteboard-subtitle">Findings ({evaluation.findings.length})</h4>
              {evaluation.findings.length === 0 ? (
                <EmptyNote>None yet.</EmptyNote>
              ) : (
                <ul className="whiteboard-list">
                  {evaluation.findings.map((finding, index) => (
                    <li key={index}>{finding.detail ?? JSON.stringify(finding)}</li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h4 className="whiteboard-subtitle">Edge cases ({evaluation.edge_cases.length})</h4>
              {evaluation.edge_cases.length === 0 ? (
                <EmptyNote>None yet.</EmptyNote>
              ) : (
                <ul className="whiteboard-list">
                  {evaluation.edge_cases.map((item, index) => (
                    <li key={index}>{item.detail ?? JSON.stringify(item)}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Section>

        <Section title={`Decisions (${decisions.length})`}>
          {decisions.length === 0 ? (
            <EmptyNote>No decisions logged yet.</EmptyNote>
          ) : (
            <ul className="whiteboard-decision-list">
              {decisionsNewestFirst.map((decision) => (
                <li key={decision.decision_id} className="whiteboard-decision">
                  <span className="whiteboard-decision-action">{decision.action}</span>
                  <span className="whiteboard-decision-reason">{decision.reason}</span>
                  <span className="whiteboard-decision-time">
                    {new Date(decision.created_at).toLocaleTimeString()}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Deployment">
          <div className="whiteboard-header-grid">
            <div>
              <div className="whiteboard-header-label">State</div>
              <div className="whiteboard-header-value">{deployment.state}</div>
            </div>
            <div>
              <div className="whiteboard-header-label">Package path</div>
              <div className="whiteboard-header-value whiteboard-header-value--mono">
                {deployment.package_path ?? '—'}
              </div>
            </div>
            <div>
              <div className="whiteboard-header-label">Error</div>
              <div className="whiteboard-header-value">{deployment.error ?? 'none'}</div>
            </div>
          </div>
          {deployment.records.length > 0 && <DrawerJsonTab data={deployment.records} />}
        </Section>
      </div>
    </ScrollArea>
  )
}
