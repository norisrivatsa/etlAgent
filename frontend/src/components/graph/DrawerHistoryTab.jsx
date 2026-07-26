function relativeTime(value) {
  const diffMs = Date.now() - new Date(value).getTime()
  const minutes = Math.round(diffMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hr ago`
  return new Date(value).toLocaleDateString()
}

export function DrawerHistoryTab({ history }) {
  if (!history.length) {
    return <p className="drawer-history-empty">No completed tasks yet for this agent.</p>
  }
  return (
    <div className="drawer-history">
      {history.map((item) => (
        <div className="drawer-history-row" key={item.id}>
          <div className={`drawer-history-dot ${item.state}`} />
          <div className="drawer-history-body">
            <div className="drawer-history-task">{item.label}</div>
            <div className="drawer-history-time">{relativeTime(item.time)}</div>
          </div>
        </div>
      ))}
    </div>
  )
}
