const VIEWS = [
  { id: 'agent', label: 'Agent Graph' },
  { id: 'pipeline', label: 'Pipeline Graph' },
]

/** Pinned to the bottom of the graph pane — swaps between agent activity
 * (Agent Graph) and the actual pipeline topology being built (Pipeline
 * Graph). */
export function GraphViewSwitcher({ value, onChange }) {
  return (
    <div className="graph-view-switcher pressed">
      {VIEWS.map((view) => (
        <button
          key={view.id}
          type="button"
          className={`graph-view-btn${value === view.id ? ' active raised-sm' : ''}`}
          onClick={() => onChange(view.id)}
        >
          {view.label}
        </button>
      ))}
    </div>
  )
}
