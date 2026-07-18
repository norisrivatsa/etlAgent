import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'

function StatusBadge({ status }) {
  return <span className={`status status-${status || 'empty'}`}>{status || 'none'}</span>
}

function formatSessionTime(value) {
  if (!value) return ''
  return new Date(value).toLocaleString()
}

function JsonPanel({ title, value }) {
  return (
    <section className="panel json-panel">
      <h2>{title}</h2>
      <pre>{JSON.stringify(value || {}, null, 2)}</pre>
    </section>
  )
}

export function WhiteboardPage() {
  const navigate = useNavigate()
  const { sessionId } = useParams()

  const [session, setSession] = useState(null)
  const [events, setEvents] = useState([])
  const [mode, setMode] = useState('package')
  const [expectedTopic, setExpectedTopic] = useState('')
  const [expectedCount, setExpectedCount] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const canApprove = session?.pending_approval
  const canDeploy = ['ready', 'deployed', 'healthy'].includes(session?.status)
  const canVerify = ['deployed', 'healthy'].includes(session?.status)

  const eventRows = useMemo(() => events.slice().reverse(), [events])

  async function run(label, action) {
    setBusy(label)
    setError('')
    try {
      await action()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  const refresh = useCallback(async (id = sessionId) => {
    if (!id) return
    try {
      const [nextSession, eventList] = await Promise.all([
        api.getSession(id),
        api.getEvents(id, null, 50),
      ])
      setSession(nextSession)
      setEvents(eventList.events || [])
    } catch (err) {
      setError(err.message)
    }
  }, [sessionId])

  async function approve(approved) {
    if (!sessionId) return
    await run(approved ? 'Generating artifacts' : 'Rejecting plan', async () => {
      const response = await api.approveSession(sessionId, approved)
      setSession(response.session)
      await refresh(response.session.session_id)
    })
  }

  async function deploy() {
    if (!sessionId) return
    await run('Deploying', async () => {
      const deployed = await api.deploySession(sessionId, mode)
      setSession(deployed)
      await refresh(deployed.session_id)
    })
  }

  async function verify() {
    if (!sessionId) return
    const expected_topic_counts =
      expectedTopic && expectedCount
        ? { [expectedTopic]: Number(expectedCount) }
        : {}

    await run('Verifying', async () => {
      const verified = await api.verifySession(sessionId, { expected_topic_counts })
      setSession(verified)
      await refresh(verified.session_id)
    })
  }

  const goToChat = () => {
    if (sessionId) {
      navigate(`/chat/${sessionId}`)
    }
  }

  // Load session on mount
  useEffect(() => {
    if (sessionId) {
      refresh(sessionId)
    }
  }, [sessionId, refresh])

  // Poll for updates
  useEffect(() => {
    if (!sessionId) return undefined
    const timer = window.setInterval(() => {
      refresh(sessionId).catch(() => {})
    }, 5000)
    return () => window.clearInterval(timer)
  }, [refresh, sessionId])

  if (!sessionId) {
    return (
      <div className="no-session">
        <h2>No session selected</h2>
        <p>Go to chat to create or select a session.</p>
        <button onClick={() => navigate('/chat')} className="btn-new-session-large">
          Go to Chat
        </button>
      </div>
    )
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Whiteboard & Events</h1>
          <p>Monitor pipeline generation, deployment, and verification.</p>
        </div>
        <div className="session-meta">
          <button onClick={goToChat} className="btn-chat">
            ← Back to Chat
          </button>
          <StatusBadge status={session?.status} />
          <code>{sessionId}</code>
        </div>
      </header>

      {error && <div className="alert">{error}</div>}
      {busy && <div className="busy">{busy}...</div>}

      <section className="workspace">
        <section className="panel control-panel">
          <h2>Pipeline: {session?.pipeline_name}</h2>

          <div className="button-row">
            <button type="button" onClick={() => approve(true)} disabled={!canApprove || Boolean(busy)}>
              Approve
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => approve(false)}
              disabled={!canApprove || Boolean(busy)}
            >
              Reject
            </button>
          </div>

          <div className="deploy-row">
            <select value={mode} onChange={(event) => setMode(event.target.value)} disabled={Boolean(busy)}>
              <option value="package">Package</option>
              <option value="apply">Apply</option>
            </select>
            <button type="button" onClick={deploy} disabled={!canDeploy || Boolean(busy)}>
              Deploy
            </button>
          </div>

          <div className="verify-grid">
            <input
              placeholder="Topic"
              value={expectedTopic}
              onChange={(event) => setExpectedTopic(event.target.value)}
              disabled={Boolean(busy)}
            />
            <input
              placeholder="Min count"
              type="number"
              min="0"
              value={expectedCount}
              onChange={(event) => setExpectedCount(event.target.value)}
              disabled={Boolean(busy)}
            />
            <button type="button" onClick={verify} disabled={!canVerify || Boolean(busy)}>
              Verify
            </button>
          </div>
        </section>

        <section className="panel summary-panel">
          <h2>Status Summary</h2>

          <div className="metrics">
            <div>
              <strong>{session?.whiteboard?.topics?.length || 0}</strong>
              <span>topics</span>
            </div>
            <div>
              <strong>{session?.whiteboard?.connectors?.length || 0}</strong>
              <span>connectors</span>
            </div>
            <div>
              <strong>{session?.whiteboard?.evaluation?.findings?.length || 0}</strong>
              <span>findings</span>
            </div>
          </div>

          <h3>Recent Events</h3>
          <div className="event-list">
            {eventRows.length === 0 && <p className="muted">No events yet.</p>}
            {eventRows.map((event) => (
              <div className="event-row" key={event.event_id}>
                <span>{event.type}</span>
                <strong>{event.source}</strong>
                <small>{new Date(event.created_at).toLocaleTimeString()}</small>
              </div>
            ))}
          </div>
        </section>
      </section>

      <section className="details-grid">
        <JsonPanel title="Plan" value={session?.whiteboard?.plan} />
        <JsonPanel title="Connectors" value={session?.whiteboard?.connectors} />
        <JsonPanel title="Deployment" value={session?.whiteboard?.deployment_status} />
        <JsonPanel title="Verification" value={session?.whiteboard?.verification_status} />
      </section>
    </main>
  )
}
