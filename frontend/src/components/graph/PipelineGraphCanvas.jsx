import { edgePath } from '../../lib/agentGraph'
import { derivePipelineGraph } from '../../lib/pipelineGraph'
import { ScrollArea } from '../common/ScrollArea'

const STATUS_LABEL = {
  stable: 'Connected',
  proposed: 'Pending approval',
  committed: 'Committed',
  rejected: 'Rejected',
}

function PipelineNode({ node, onClick }) {
  const clickable = node.kind !== 'source'
  return (
    <div
      className={`pipeline-node pipeline-node--${node.kind} pipeline-node--${node.status} raised-sm`}
      style={{ left: node.x, top: node.y, width: node.w, height: node.h }}
      onClick={clickable ? () => onClick(node.artifact) : undefined}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      title={`${node.label} — ${node.sublabel} — ${STATUS_LABEL[node.status] ?? node.status}`}
    >
      <span className="pipeline-node-dot" />
      <span className="pipeline-node-label">{node.label}</span>
    </div>
  )
}

export function PipelineGraphCanvas({ whiteboard, onSelectArtifact }) {
  const graph = derivePipelineGraph(whiteboard)

  if (graph.isEmpty) {
    return (
      <div className="graph-canvas-outer pressed pipeline-canvas-empty">
        <p>Nothing generated yet — this fills in as Connect and ksqlDB produce artifacts.</p>
      </div>
    )
  }

  return (
    <div className="graph-canvas-outer pressed">
      <ScrollArea className="graph-canvas-scroll">
        <div className="graph-canvas-inner" style={{ width: graph.width, height: graph.height }}>
          <svg width={graph.width} height={graph.height} className="edge-layer">
            <defs>
              <marker id="pipeline-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" className="edge-arrow-base" />
              </marker>
            </defs>
            {graph.edges.map(([a, b]) => (
              <path
                key={`${a.id}->${b.id}`}
                d={edgePath(a, b)}
                fill="none"
                className="edge-base"
                strokeWidth="1.6"
                markerEnd="url(#pipeline-arrow)"
              />
            ))}
          </svg>
          {graph.nodes.map((node) => (
            <PipelineNode key={node.id} node={node} onClick={onSelectArtifact} />
          ))}
        </div>
      </ScrollArea>
    </div>
  )
}
