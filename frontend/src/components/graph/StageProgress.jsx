import { STAGE_LABELS } from '../../lib/agentGraph'
import { Popover } from '../common/Popover'

export function StageProgress({ stageIndex, failed }) {
  const percent = Math.round(((stageIndex + 1) / STAGE_LABELS.length) * 100)
  const currentLabel = STAGE_LABELS[stageIndex] ?? STAGE_LABELS[0]

  return (
    <div className="stage-progress">
      <div className="stage-progress-track pressed">
        <div className={`stage-progress-fill${failed ? ' error' : ''}`} style={{ width: `${percent}%` }} />
      </div>
      <span className={`stage-progress-label${failed ? ' error' : ''}`}>
        {currentLabel}
        {failed && ' — Failed'}
      </span>
      <Popover
        align="left"
        panelClassName="stage-info-panel"
        trigger={({ toggle }) => (
          <button type="button" className="stage-info-btn raised-sm" onClick={toggle} aria-label="Show all stages">
            i
          </button>
        )}
      >
        <div className="stage-info-title">Pipeline stages</div>
        {STAGE_LABELS.map((label, i) => {
          const done = i < stageIndex
          const isCurrent = i === stageIndex
          const isFailedHere = failed && isCurrent
          return (
            <div
              key={label}
              className={`stage-info-row${done ? ' done' : ''}${isCurrent ? ' current' : ''}${isFailedHere ? ' error' : ''}`}
            >
              {label}
              {isFailedHere && ' (failed)'}
            </div>
          )
        })}
      </Popover>
    </div>
  )
}
