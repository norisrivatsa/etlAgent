/**
 * Data + layout for the Pipeline Graph view — the actual data-pipeline
 * topology being built (source -> connectors -> ksqlDB objects), driven
 * entirely by `Whiteboard.artifacts` as they're proposed/committed.
 * Separate from lib/agentGraph.js, which shows agent *activity* rather than
 * the pipeline shape itself.
 *
 * Each object's column is its topological depth (distance from the source),
 * computed from real `depends_on` edges — NOT the LLM-reported "layer"
 * (raw/aggregate/join), which is occasionally wrong (a "raw" statement has
 * been observed depending on a "join" one) and, more importantly, groups
 * unrelated objects into the same 3 buckets regardless of how many actual
 * processing steps separate them. Depth-based columns instead put each
 * object exactly one step to the right of whatever it reads from, so the
 * graph reads as a literal left-to-right chain (source -> connector ->
 * orders_raw -> orders_deduped -> orders_aggregate -> ...) instead of 3
 * wide buckets. A pipeline with many sequential steps naturally produces a
 * wide canvas — the view is meant to be scrolled horizontally to see the
 * rest, not squeezed to fit.
 *
 * Rows within a column are plain sequential order (no clustering/relaxation
 * — that reads as noise, not signal, once each object already sits at its
 * correct depth).
 */

const SOURCE_X = 40
const COLUMN_GAP = 240
const NODE_W = 190
const NODE_H = 44
const ROW_GAP = 76
const TOP_PAD = 40

function buildRecord(artifact, kind) {
  const isConnector = kind === 'connector'
  const objectName = isConnector ? artifact.name : artifact.content?.object_name || artifact.name
  const dependsOn = isConnector ? [] : artifact.content?.depends_on
  const layer = artifact.content?.layer
  return {
    id: artifact.artifact_id,
    objectName,
    dependsOnNames: Array.isArray(dependsOn) ? dependsOn : [],
    kind: isConnector ? 'connector' : 'ksql',
    label: objectName,
    sublabel: isConnector ? 'Connector' : layer ? layer[0].toUpperCase() + layer.slice(1) : 'Statement',
    status: artifact.status,
    artifact,
    deps: [], // resolved to record references below, once every record exists
    depth: 1,
  }
}

export function derivePipelineGraph(whiteboard) {
  const board = whiteboard || {}
  const artifacts = board.artifacts || []
  const connectorArtifacts = artifacts.filter((a) => a.kind === 'connector')
  const ksqlArtifacts = artifacts.filter((a) => a.kind === 'ksql_statement')

  const connectorRecords = connectorArtifacts.map((a) => buildRecord(a, 'connector'))
  const ksqlRecords = ksqlArtifacts.map((a) => buildRecord(a, 'ksql'))
  const allRecords = [...connectorRecords, ...ksqlRecords]

  const byObjectName = new Map(allRecords.map((r) => [r.objectName, r]))

  // Resolve dependsOn names to actual records. A ksql record with nothing
  // resolvable (missing depends_on, or an older session) falls back to the
  // immediately preceding artifact in whiteboard order — better than no
  // edge at all, and keeps the chain connected end to end.
  ksqlRecords.forEach((record) => {
    const resolved = record.dependsOnNames.map((name) => byObjectName.get(name)).filter(Boolean)
    if (resolved.length) {
      record.deps = resolved
      return
    }
    const ownIndex = allRecords.indexOf(record)
    record.deps = ownIndex > 0 ? [allRecords[ownIndex - 1]] : []
  })

  // Topological depth via iterative relaxation (no real topo sort needed —
  // `artifacts` isn't guaranteed to already be dependency-ordered). Bounded
  // by allRecords.length passes, which is always enough to settle a DAG of
  // that many nodes.
  for (let pass = 0; pass < allRecords.length + 1; pass++) {
    let changed = false
    ksqlRecords.forEach((record) => {
      const depDepth = record.deps.length ? Math.max(...record.deps.map((d) => d.depth)) : 0
      const nextDepth = depDepth + 1
      if (nextDepth !== record.depth) {
        record.depth = nextDepth
        changed = true
      }
    })
    if (!changed) break
  }

  const maxDepth = allRecords.reduce((max, r) => Math.max(max, r.depth), 1)
  const columns = []
  for (let depth = 1; depth <= maxDepth; depth++) {
    columns.push(allRecords.filter((r) => r.depth === depth))
  }

  const nodes = []
  const edges = []
  const nodeById = new Map()

  columns.forEach((column, columnIndex) => {
    column.forEach((record, rowIndex) => {
      const node = {
        id: record.id,
        kind: record.kind,
        label: record.label,
        sublabel: record.sublabel,
        status: record.status,
        artifact: record.artifact,
        x: SOURCE_X + (columnIndex + 1) * COLUMN_GAP,
        y: TOP_PAD + rowIndex * ROW_GAP,
        w: NODE_W,
        h: NODE_H,
      }
      nodes.push(node)
      nodeById.set(record.id, node)
    })
  })

  const sourceType = board.requirements?.source?.type
  let sourceNode = null
  if (connectorRecords.length > 0 || sourceType) {
    sourceNode = {
      id: 'source',
      kind: 'source',
      label: sourceType ? sourceType[0].toUpperCase() + sourceType.slice(1) : 'Source',
      sublabel: board.requirements?.source?.database || board.requirements?.source?.table || 'Source system',
      status: 'stable',
      x: SOURCE_X,
      y: TOP_PAD + (Math.max(1, columns[0]?.length ?? 1) - 1) * ROW_GAP * 0.5,
      w: NODE_W,
      h: NODE_H,
    }
    nodes.unshift(sourceNode)
    connectorRecords.forEach((record) => edges.push([sourceNode, nodeById.get(record.id)]))
  }

  ksqlRecords.forEach((record) => {
    record.deps.forEach((dep) => edges.push([nodeById.get(dep.id), nodeById.get(record.id)]))
  })

  const maxRows = Math.max(1, ...columns.map((c) => c.length))

  return {
    nodes,
    edges,
    width: SOURCE_X + (maxDepth + 1) * COLUMN_GAP + NODE_W + 60,
    height: TOP_PAD * 2 + maxRows * ROW_GAP,
    isEmpty: nodes.length === 0,
  }
}
