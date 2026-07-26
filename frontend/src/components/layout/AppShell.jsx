import { useCallback, useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import { useTheme } from '../../theme/useTheme'
import { NewSessionModal } from './NewSessionModal'
import { SessionSwitcher } from './SessionSwitcher'
import { ThemeToggle } from './ThemeToggle'
import './AppShell.css'

const SESSION_POLL_MS = 4000

export function AppShell() {
  const navigate = useNavigate()
  const { sessionId } = useParams()
  const { isDark, toggleTheme } = useTheme()

  const [sessions, setSessions] = useState([])
  const [currentSession, setCurrentSession] = useState(null)
  const [showNewSession, setShowNewSession] = useState(false)

  const refreshSessions = useCallback(async () => {
    try {
      const result = await api.listSessions(50)
      setSessions(result.sessions || [])
    } catch (error) {
      console.error('Failed to load sessions:', error)
    }
  }, [])

  const refreshCurrentSession = useCallback(async () => {
    if (!sessionId) {
      setCurrentSession(null)
      return
    }
    try {
      setCurrentSession(await api.getSession(sessionId))
    } catch (error) {
      console.error('Failed to load session:', error)
    }
  }, [sessionId])

  useEffect(() => {
    async function loadInitialSessions() {
      try {
        const result = await api.listSessions(50)
        setSessions(result.sessions || [])
      } catch (error) {
        console.error('Failed to load sessions:', error)
      }
    }
    loadInitialSessions()
  }, [])

  useEffect(() => {
    async function loadInitialSession() {
      if (!sessionId) {
        setCurrentSession(null)
        return
      }
      try {
        setCurrentSession(await api.getSession(sessionId))
      } catch (error) {
        console.error('Failed to load session:', error)
      }
    }
    loadInitialSession()
    const timer = window.setInterval(refreshCurrentSession, SESSION_POLL_MS)
    return () => window.clearInterval(timer)
  }, [sessionId, refreshCurrentSession])

  const handleSelectSession = (nextSessionId) => {
    navigate(`/session/${nextSessionId}`)
  }

  const handleSessionCreated = (session) => {
    setShowNewSession(false)
    refreshSessions()
    navigate(`/session/${session.session_id}`)
  }

  return (
    <div className="app-root">
      <header className="app-header raised-sm">
        <div className="app-brand">
          <div className="app-logo-dot" />
          <span className="app-brand-text">Kafka Pipeline Architect</span>
        </div>

        {sessionId && (
          <nav className="app-nav">
            <NavLink to={`/session/${sessionId}`} end className="app-nav-link">
              Workspace
            </NavLink>
            <NavLink to={`/session/${sessionId}/whiteboard`} className="app-nav-link">
              Whiteboard
            </NavLink>
          </nav>
        )}

        <div className="app-header-right">
          <button type="button" className="btn-ghost raised-sm" onClick={() => setShowNewSession(true)}>
            + New
          </button>
          <SessionSwitcher sessions={sessions} currentSessionId={sessionId} onSelect={handleSelectSession} />
          <ThemeToggle isDark={isDark} onToggle={toggleTheme} />
        </div>
      </header>

      <div className="app-body">
        <Outlet
          context={{
            sessionId,
            sessions,
            currentSession,
            refreshSessions,
            refreshCurrentSession,
            openNewSession: () => setShowNewSession(true),
          }}
        />
      </div>

      {showNewSession && (
        <NewSessionModal onClose={() => setShowNewSession(false)} onCreated={handleSessionCreated} />
      )}
    </div>
  )
}
