import { useState } from 'react'
import { api } from '../../api/client'

export function NewSessionModal({ onClose, onCreated }) {
  const [pipelineName, setPipelineName] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!pipelineName.trim()) return

    setCreating(true)
    setError('')
    try {
      const session = await api.createSession(pipelineName)
      onCreated(session)
    } catch (err) {
      setError(err.message)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="modal-scrim" onClick={() => !creating && onClose()}>
      <div className="modal-card raised" onClick={(event) => event.stopPropagation()}>
        <h2 className="modal-title">New pipeline session</h2>
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            value={pipelineName}
            onChange={(event) => setPipelineName(event.target.value)}
            placeholder="Pipeline name (e.g., orders-pipeline)"
            className="field-input pressed"
            autoFocus
            disabled={creating}
          />
          {error && <p className="modal-error">{error}</p>}
          <div className="modal-actions">
            <button type="button" className="btn-ghost" onClick={onClose} disabled={creating}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={creating || !pipelineName.trim()}>
              {creating ? 'Creating…' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
