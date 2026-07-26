function formatTime(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

export function DrawerOverviewTab({ nodeState }) {
  const rows = [
    { label: 'Task', value: nodeState?.task || '—' },
    { label: 'Status', value: nodeState?.statusLabel || 'Idle' },
    { label: 'Last updated', value: formatTime(nodeState?.updatedAt) },
  ]
  return (
    <div className="drawer-overview">
      {rows.map((row) => (
        <div className="drawer-overview-row" key={row.label}>
          <span className="drawer-overview-label">{row.label}</span>
          <span className="drawer-overview-value">{row.value}</span>
        </div>
      ))}
    </div>
  )
}
