import { Popover } from '../common/Popover'

const STATES = [
  { label: 'Idle', className: 'idle' },
  { label: 'Working', className: 'working' },
  { label: 'Success', className: 'success' },
  { label: 'Error', className: 'error' },
]

function InfoIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.6" />
      <line x1="12" y1="11" x2="12" y2="16.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="12" cy="7.7" r="1" fill="currentColor" />
    </svg>
  )
}

export function GraphLegend() {
  return (
    <Popover
      align="right"
      panelClassName="graph-legend-panel"
      trigger={({ toggle }) => (
        <button type="button" className="canvas-btn raised-sm" onClick={toggle} aria-label="Show legend">
          <InfoIcon />
        </button>
      )}
    >
      <div className="graph-legend-title">Legend</div>
      {STATES.map((s) => (
        <div className="graph-legend-row" key={s.label}>
          <div className={`graph-legend-swatch swatch-${s.className}`} />
          <span>{s.label}</span>
        </div>
      ))}
      <div className="graph-legend-divider" />
      <div className="graph-legend-row">
        <div className="graph-legend-edge idle" />
        <span>Idle connection</span>
      </div>
      <div className="graph-legend-row">
        <div className="graph-legend-edge active" />
        <span>Active handoff</span>
      </div>
    </Popover>
  )
}
