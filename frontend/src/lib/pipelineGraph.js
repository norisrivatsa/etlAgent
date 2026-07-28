/**
 * Layout for the Pipeline Graph view — pure positioning over the node/edge
 * data the backend already computed (GET /sessions/{id}/pipeline-graph:
 * source/sink connectors, topics, ksqlDB streams/tables, with live connector
 * status). Names, types, and edges are backend-authoritative; this file only
 * decides where each node sits on screen. Separate from lib/agentGraph.js,
 * which shows agent *activity* rather than the pipeline shape itself.
 *
 * Each node's column is its topological depth (distance from the nearest
 * root, via real edges), not a fixed 3-bucket layer — so a pipeline with N
 * sequential steps reads as a literal left-to-right chain (source connector
 * -> topic -> ksql stream -> ksql table -> topic -> sink connector) of
 * however many columns it actually has. A wide pipeline naturally produces a
 * wide canvas — the view is meant to be scrolled horizontally, not squeezed
 * to fit.
 *
 * Rows within a column are plain sequential order (no clustering/relaxation
 * — that reads as noise, not signal, once each node already sits at its
 * correct depth).
 */

const SOURCE_PAD = 40
const COLUMN_GAP = 240
const NODE_W = 190
const NODE_H = 44
const ROW_GAP = 76
const TOP_PAD = 40

export function layoutPipelineGraph(graph) {
  const rawNodes = graph?.nodes || []
  const rawEdges = graph?.edges || []

  if (rawNodes.length === 0) {
    return { nodes: [], edges: [], width: 0, height: 0, isEmpty: true }
  }

  const records = rawNodes.map((node) => ({ ...node, depth: 0, incoming: [] }))
  const byId = new Map(records.map((record) => [record.id, record]))
  rawEdges.forEach(({ source, target }) => {
    const targetRecord = byId.get(target)
    if (targetRecord && byId.has(source)) targetRecord.incoming.push(source)
  })

  // Topological depth via iterative relaxation (no real topo sort needed —
  // node/edge order isn't guaranteed dependency-ordered). Bounded by
  // records.length passes, always enough to settle a DAG of that many nodes.
  for (let pass = 0; pass < records.length + 1; pass++) {
    let changed = false
    records.forEach((record) => {
      const depDepth = record.incoming.length
        ? Math.max(...record.incoming.map((id) => byId.get(id)?.depth ?? 0))
        : -1
      const nextDepth = depDepth + 1
      if (nextDepth !== record.depth) {
        record.depth = nextDepth
        changed = true
      }
    })
    if (!changed) break
  }

  const maxDepth = records.reduce((max, r) => Math.max(max, r.depth), 0)
  const columns = []
  for (let depth = 0; depth <= maxDepth; depth++) {
    columns.push(records.filter((r) => r.depth === depth))
  }

  const nodes = []
  const positioned = new Map()
  columns.forEach((column, columnIndex) => {
    column.forEach((record, rowIndex) => {
      const node = {
        ...record,
        x: SOURCE_PAD + columnIndex * COLUMN_GAP,
        y: TOP_PAD + rowIndex * ROW_GAP,
        w: NODE_W,
        h: NODE_H,
      }
      nodes.push(node)
      positioned.set(node.id, node)
    })
  })

  const edges = rawEdges
    .map(({ source, target }) => [positioned.get(source), positioned.get(target)])
    .filter(([a, b]) => a && b)

  const maxRows = Math.max(1, ...columns.map((c) => c.length))

  return {
    nodes,
    edges,
    width: SOURCE_PAD * 2 + (maxDepth + 1) * COLUMN_GAP + NODE_W,
    height: TOP_PAD * 2 + maxRows * ROW_GAP,
    isEmpty: false,
  }
}
