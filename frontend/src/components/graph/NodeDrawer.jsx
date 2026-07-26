import { useState } from 'react'
import { ICONS } from '../../lib/agentGraph'
import { ScrollArea } from '../common/ScrollArea'
import { AgentIcon } from './AgentIcon'
import { DrawerHistoryTab } from './DrawerHistoryTab'
import { DrawerJsonTab } from './DrawerJsonTab'
import { DrawerOverviewTab } from './DrawerOverviewTab'

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'history', label: 'Task History' },
  { id: 'json', label: 'Raw JSON' },
]

export function NodeDrawer({ def, nodeState, history, jsonData, onClose }) {
  const [tab, setTab] = useState('overview')

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <div className="node-drawer">
        <div className="drawer-header">
          <div className={`drawer-icon-wrap pressed drawer-icon--${nodeState?.state ?? 'idle'}`}>
            <AgentIcon shapes={ICONS[def.id]} />
          </div>
          <div>
            <div className="drawer-title">{def.name}</div>
            <div className={`drawer-subtitle drawer-icon--${nodeState?.state ?? 'idle'}`}>
              {nodeState?.statusLabel ?? 'Idle'}
            </div>
          </div>
          <button type="button" className="drawer-close raised-sm" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="drawer-tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`drawer-tab${tab === t.id ? ' active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <ScrollArea className="drawer-body">
          {tab === 'overview' && <DrawerOverviewTab nodeState={nodeState} />}
          {tab === 'history' && <DrawerHistoryTab history={history} />}
          {tab === 'json' && <DrawerJsonTab data={jsonData} />}
        </ScrollArea>
      </div>
    </>
  )
}
