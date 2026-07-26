/** Renders one of the shape-descriptor arrays from lib/agentGraph.js's ICONS map. */
export function AgentIcon({ shapes, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      {(shapes || []).map((s, i) => {
        if (s.isCircle) {
          return <circle key={i} cx={s.cx} cy={s.cy} r={s.r} fill="none" stroke="currentColor" strokeWidth="1.6" />
        }
        if (s.isEllipse) {
          return (
            <ellipse key={i} cx={s.cx} cy={s.cy} rx={s.rx} ry={s.ry} fill="none" stroke="currentColor" strokeWidth="1.6" />
          )
        }
        if (s.isRect) {
          return (
            <rect
              key={i}
              x={s.x}
              y={s.y}
              width={s.w}
              height={s.h}
              rx={s.rx}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
            />
          )
        }
        if (s.isLine) {
          return (
            <line
              key={i}
              x1={s.x1}
              y1={s.y1}
              x2={s.x2}
              y2={s.y2}
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
          )
        }
        if (s.isPath) {
          return (
            <path
              key={i}
              d={s.d}
              fill={s.fill || 'none'}
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )
        }
        return null
      })}
    </svg>
  )
}
