import { Popover } from '../common/Popover'
import { ScrollArea } from '../common/ScrollArea'

export function SessionSwitcher({ sessions, currentSessionId, onSelect }) {
  const current = sessions.find((s) => s.session_id === currentSessionId)

  return (
    <Popover
      align="right"
      panelClassName="session-dropdown-popover"
      trigger={({ toggle }) => (
        <button type="button" className="session-pill raised-sm" onClick={toggle}>
          <span>{current ? current.pipeline_name : 'Select session'}</span>
          <span className="session-pill-chevron">⌄</span>
        </button>
      )}
    >
      {({ close }) => (
        <ScrollArea className="session-dropdown">
          {sessions.length === 0 && <div className="session-dropdown-empty">No sessions yet</div>}
          {sessions.map((session) => (
            <button
              type="button"
              key={session.session_id}
              className={`session-dropdown-item${session.session_id === currentSessionId ? ' active' : ''}`}
              onClick={() => {
                onSelect(session.session_id)
                close()
              }}
            >
              <span className="session-dropdown-name">{session.pipeline_name}</span>
              <span className="session-dropdown-status">{session.status}</span>
            </button>
          ))}
        </ScrollArea>
      )}
    </Popover>
  )
}
