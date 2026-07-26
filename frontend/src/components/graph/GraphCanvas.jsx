import { useRef, useState } from 'react'
import { AGENT_DEFS, CANVAS_HEIGHT, CANVAS_WIDTH } from '../../lib/agentGraph'
import { ScrollArea } from '../common/ScrollArea'
import { AgentNode } from './AgentNode'
import { EdgeLayer } from './EdgeLayer'
import { GraphLegend } from './GraphLegend'

const ZOOM_MIN = 0.4
const ZOOM_MAX = 1.6
const ZOOM_STEP = 0.15

export function GraphCanvas({ nodesById, nodeStates, activeEdgeKeys, onSelectNode }) {
  const [zoom, setZoom] = useState(1)
  const scrollRef = useRef(null)

  const zoomIn = () => setZoom((z) => Math.min(ZOOM_MAX, +(z + ZOOM_STEP).toFixed(2)))
  const zoomOut = () => setZoom((z) => Math.max(ZOOM_MIN, +(z - ZOOM_STEP).toFixed(2)))
  const fit = () => {
    setZoom(1)
    scrollRef.current?.scrollTo({ top: 0, left: 0, behavior: 'smooth' })
  }

  return (
    <div className="graph-canvas-outer pressed">
      <div className="graph-canvas-controls">
        <button type="button" className="canvas-btn raised-sm" onClick={zoomIn} aria-label="Zoom in">
          +
        </button>
        <button type="button" className="canvas-btn raised-sm" onClick={zoomOut} aria-label="Zoom out">
          –
        </button>
        <button type="button" className="canvas-btn-fit raised-sm" onClick={fit}>
          Fit
        </button>
        <GraphLegend />
      </div>

      <ScrollArea className="graph-canvas-scroll" innerRef={scrollRef}>
        <div
          className="graph-canvas-scale-holder"
          style={{ width: CANVAS_WIDTH * zoom, height: CANVAS_HEIGHT * zoom }}
        >
          <div
            className="graph-canvas-inner"
            style={{ width: CANVAS_WIDTH, height: CANVAS_HEIGHT, transform: `scale(${zoom})` }}
          >
            <EdgeLayer nodesById={nodesById} activeEdgeKeys={activeEdgeKeys} />
            {AGENT_DEFS.map((def) => (
              <AgentNode
                key={def.id}
                def={def}
                nodeState={nodeStates[def.id]}
                onClick={() => onSelectNode(def.id)}
              />
            ))}
          </div>
        </div>
      </ScrollArea>
    </div>
  )
}
