import { CANVAS_HEIGHT, CANVAS_WIDTH, EDGE_DEFS, edgePath } from '../../lib/agentGraph'

export function EdgeLayer({ nodesById, activeEdgeKeys }) {
  return (
    <svg width={CANVAS_WIDTH} height={CANVAS_HEIGHT} className="edge-layer">
      <defs>
        <marker id="agent-arrow-base" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" className="edge-arrow-base" />
        </marker>
        <marker id="agent-arrow-active" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" className="edge-arrow-active" />
        </marker>
      </defs>
      {EDGE_DEFS.map((edge) => {
        const a = nodesById[edge.from]
        const b = nodesById[edge.to]
        if (!a || !b) return null
        const d = edgePath(a, b)
        const key = `${edge.from}->${edge.to}`
        const active = activeEdgeKeys.has(key)
        return (
          <g key={key}>
            <path
              d={d}
              fill="none"
              className="edge-base"
              strokeWidth={edge.hub ? 1.2 : edge.dashed ? 1.6 : 2}
              strokeDasharray={edge.hub ? '2 5' : edge.dashed ? '5 6' : 'none'}
              markerEnd={edge.hub ? undefined : 'url(#agent-arrow-base)'}
            />
            {active && (
              <path
                d={d}
                fill="none"
                className="edge-active"
                strokeWidth="2.4"
                strokeDasharray="7 9"
                markerEnd="url(#agent-arrow-active)"
              />
            )}
          </g>
        )
      })}
    </svg>
  )
}
