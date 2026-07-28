import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { edgePath } from '../../lib/agentGraph'
import { layoutPipelineGraph } from '../../lib/pipelineGraph'
import { ScrollArea } from '../common/ScrollArea'

// Live connector status (green/red/orange/grey) can change between polls even
// with no user action, so this refreshes on its own timer rather than only
// when the whiteboard changes — see backend/api_list.csv for the endpoint.
const POLL_MS = 30000

const TYPE_LABEL = {
  source_connector: 'Source connector',
  sink_connector: 'Sink connector',
  topic: 'Topic',
  ksql_stream: 'ksqlDB stream',
  ksql_table: 'ksqlDB table',
}

const STATUS_LABEL = {
  proposed: 'Pending approval',
  committed: 'Committed',
}

function typeClass(type) {
  return type.replace(/_/g, '-')
}

function PipelineNode({ node, onClick }) {
  const isConnector = node.type === 'source_connector' || node.type === 'sink_connector'
  const statusColor = isConnector ? node.connector_status?.color : null
  const title = [
    node.name,
    TYPE_LABEL[node.type] ?? node.type,
    isConnector ? (node.connector_status?.state ?? 'not deployed yet') : STATUS_LABEL[node.status],
  ]
    .filter(Boolean)
    .join(' — ')

  return (
    <div
      className={[
        'pipeline-node',
        `pipeline-node--${typeClass(node.type)}`,
        statusColor ? `pipeline-node--status-${statusColor}` : '',
        'raised-sm',
      ]
        .filter(Boolean)
        .join(' ')}
      style={{ left: node.x, top: node.y, width: node.w, height: node.h }}
      onClick={() => onClick(node)}
      role="button"
      tabIndex={0}
      title={title}
    >
      {!isConnector && <span className="pipeline-node-dot" data-status={node.status} />}
      <span className="pipeline-node-label">{node.name}</span>
    </div>
  )
}

export function PipelineGraphCanvas({ sessionId, refreshToken, onSelectNode }) {
  const [rawGraph, setRawGraph] = useState(null)
  const [error, setError] = useState('')

  // Re-runs on sessionId change (session switch) and on refreshToken bumps
  // (an approval/rejection just changed the pipeline shape — refetch right
  // away instead of waiting out the rest of the poll interval), in addition
  // to its own POLL_MS timer for live connector-status updates.
  useEffect(() => {
    let mounted = true

    async function loadGraph() {
      if (!sessionId) return
      try {
        const result = await api.getPipelineGraph(sessionId)
        if (mounted) {
          setRawGraph(result)
          setError('')
        }
      } catch (err) {
        console.error('Failed to load pipeline graph:', err)
        if (mounted) setError(err.message)
      }
    }

    loadGraph()
    const timer = window.setInterval(loadGraph, POLL_MS)
    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [sessionId, refreshToken])

  const graph = layoutPipelineGraph(rawGraph)

  if (graph.isEmpty) {
    return (
      <div className="graph-canvas-outer pressed pipeline-canvas-empty">
        <p>
          {error
            ? `Couldn't load the pipeline graph: ${error}`
            : 'Nothing generated yet — this fills in as Connect and ksqlDB produce artifacts.'}
        </p>
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
            <PipelineNode key={node.id} node={node} onClick={onSelectNode} />
          ))}
        </div>
      </ScrollArea>
    </div>
  )
}
