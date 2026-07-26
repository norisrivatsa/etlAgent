import { PipelineActions } from './PipelineActions'
import { StageProgress } from './StageProgress'

/** Single bar combining stage progress (left ~45%) with pipeline actions (rest). */
export function PipelineBar({ stageIndex, failed, session, busy, onApprove, onDeploy, onVerify }) {
  return (
    <div className="pipeline-bar raised-sm">
      <StageProgress stageIndex={stageIndex} failed={failed} />
      <div className="pipeline-bar-divider" />
      <PipelineActions session={session} busy={busy} onApprove={onApprove} onDeploy={onDeploy} onVerify={onVerify} />
    </div>
  )
}
