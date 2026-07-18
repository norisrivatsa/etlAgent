import { useState, useEffect, useRef } from 'react'
import { api } from '../api/client'
import { useNavigate, useParams } from 'react-router-dom'

function SessionSelector({ currentSessionId, onSelectSession }) {
  const [sessions, setSessions] = useState([])
  const [showDropdown, setShowDropdown] = useState(false)

  useEffect(() => {
    async function loadSessions() {
      try {
        const result = await api.listSessions(50)
        setSessions(result.sessions || [])
      } catch (error) {
        console.error('Failed to load sessions:', error)
      }
    }
    loadSessions()
  }, [])

  const currentSession = sessions.find((s) => s.session_id === currentSessionId)

  return (
    <div className="session-selector">
      <button onClick={() => setShowDropdown(!showDropdown)} className="session-selector-button">
        {currentSession ? currentSession.pipeline_name : 'Select Session'}
        <span className="dropdown-arrow">{showDropdown ? '▲' : '▼'}</span>
      </button>
      {showDropdown && (
        <div className="session-dropdown">
          {sessions.map((session) => (
            <div
              key={session.session_id}
              className={`session-item ${session.session_id === currentSessionId ? 'active' : ''}`}
              onClick={() => {
                onSelectSession(session.session_id)
                setShowDropdown(false)
              }}
            >
              <div className="session-name">{session.pipeline_name}</div>
              <div className="session-status">{session.status}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SimpleChatThread({ sessionId }) {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef(null)

  // Load messages from backend
  useEffect(() => {
    if (!sessionId) {
      setMessages([])
      return
    }

    let mounted = true

    async function loadMessages() {
      try {
        const result = await api.getChatMessages(sessionId)
        if (mounted) {
          setMessages(result.messages || [])
        }
      } catch (error) {
        console.error('Failed to load chat messages:', error)
      }
    }

    loadMessages()

    // Poll for new messages every 3 seconds
    const interval = setInterval(loadMessages, 3000)

    return () => {
      mounted = false
      clearInterval(interval)
    }
  }, [sessionId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    setIsLoading(true)
    const userMessageText = input
    setInput('')

    try {
      // Optimistically add user message
      const tempMessage = {
        message_id: `temp-${Date.now()}`,
        role: 'user',
        content: userMessageText,
        created_at: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, tempMessage])

      // Send to backend
      await api.sendChatMessage(sessionId, userMessageText)

      // Wait a bit then reload to get the actual response
      setTimeout(async () => {
        try {
          const result = await api.getChatMessages(sessionId)
          setMessages(result.messages || [])
        } catch (error) {
          console.error('Failed to reload messages:', error)
        }
        setIsLoading(false)
      }, 1000)
    } catch (error) {
      console.error('Error sending message:', error)
      alert(`Failed to send message: ${error.message}`)
      // Remove temp message on error
      setMessages((prev) => prev.filter((msg) => !msg.message_id.startsWith('temp-')))
      setIsLoading(false)
    }
  }

  return (
    <div className="simple-chat">
      <div className="chat-messages">
        {messages.length === 0 && !isLoading && (
          <div className="chat-welcome">
            <h3>Hello! I can help you design and deploy Kafka pipelines.</h3>
            <p>What would you like to build?</p>
          </div>
        )}
        {messages.map((msg) => (
          <div key={msg.message_id} className={`chat-message chat-message-${msg.role}`}>
            <div className="chat-message-role">{msg.role === 'user' ? 'You' : 'Assistant'}</div>
            <div className="chat-message-content">{msg.content}</div>
          </div>
        ))}
        {isLoading && (
          <div className="chat-message chat-message-assistant">
            <div className="chat-message-role">Assistant</div>
            <div className="chat-message-content">Thinking...</div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <form onSubmit={handleSubmit} className="chat-composer">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your message..."
          className="chat-input"
          disabled={isLoading}
        />
        <button type="submit" disabled={!input.trim() || isLoading}>
          {isLoading ? 'Sending...' : 'Send'}
        </button>
      </form>
    </div>
  )
}

export function ChatPage() {
  const navigate = useNavigate()
  const { sessionId } = useParams()
  const [pipelineName, setPipelineName] = useState('')
  const [showNewSession, setShowNewSession] = useState(false)
  const [creating, setCreating] = useState(false)

  const handleNewSession = async (e) => {
    e.preventDefault()
    if (!pipelineName.trim()) return

    setCreating(true)
    try {
      const session = await api.createSession(pipelineName)
      navigate(`/chat/${session.session_id}`)
      setShowNewSession(false)
      setPipelineName('')
    } catch (error) {
      console.error('Failed to create session:', error)
      alert(`Failed to create session: ${error.message}`)
    } finally {
      setCreating(false)
    }
  }

  const handleSelectSession = (newSessionId) => {
    navigate(`/chat/${newSessionId}`)
  }

  const goToWhiteboard = () => {
    if (sessionId) {
      navigate(`/whiteboard/${sessionId}`)
    }
  }

  return (
    <div className="chat-page">
      <div className="chat-header">
        <h1>ETL Agent Chat</h1>
        <div className="chat-actions">
          <button onClick={() => setShowNewSession(true)} className="btn-new-session">
            New Session
          </button>
          {sessionId && (
            <>
              <SessionSelector currentSessionId={sessionId} onSelectSession={handleSelectSession} />
              <button onClick={goToWhiteboard} className="btn-whiteboard">
                View Whiteboard →
              </button>
            </>
          )}
        </div>
      </div>

      {showNewSession && (
        <div className="modal-overlay" onClick={() => !creating && setShowNewSession(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h2>Create New Session</h2>
            <form onSubmit={handleNewSession}>
              <input
                type="text"
                value={pipelineName}
                onChange={(e) => setPipelineName(e.target.value)}
                placeholder="Pipeline name (e.g., mysql-orders-pipeline)"
                className="pipeline-name-input"
                autoFocus
                disabled={creating}
              />
              <div className="modal-actions">
                <button type="button" onClick={() => setShowNewSession(false)} disabled={creating}>
                  Cancel
                </button>
                <button type="submit" disabled={creating || !pipelineName.trim()}>
                  {creating ? 'Creating...' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className="chat-container">
        {sessionId ? (
          <SimpleChatThread sessionId={sessionId} />
        ) : (
          <div className="no-session">
            <h2>No session selected</h2>
            <p>Create a new session or select an existing one to start chatting.</p>
            <button onClick={() => setShowNewSession(true)} className="btn-new-session-large">
              Create New Session
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
