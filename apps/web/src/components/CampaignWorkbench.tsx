import {
  ArrowRight,
  Beaker,
  CheckCircle2,
  FlaskConical,
  Plus,
  RefreshCw,
  Target,
} from 'lucide-react'
import { useEffect, useState } from 'react'

import { api } from '../api'
import { useI18n } from '../i18n'
import type {
  CampaignCandidate,
  CampaignDecision,
  CampaignRecord,
  ProjectArtifact,
  WorkflowRevision,
} from '../types'

interface CampaignWorkbenchProps {
  projectId: string | null
  artifacts: ProjectArtifact[]
  revisions: WorkflowRevision[]
  onMessage: (tone: 'success' | 'error' | 'neutral', message: string) => void
}

export function CampaignWorkbench({
  projectId,
  artifacts,
  revisions,
  onMessage,
}: CampaignWorkbenchProps) {
  const { tr } = useI18n()
  const [campaigns, setCampaigns] = useState<CampaignRecord[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [candidates, setCandidates] = useState<CampaignCandidate[]>([])
  const [decisions, setDecisions] = useState<CampaignDecision[]>([])
  const [title, setTitle] = useState('')
  const [objective, setObjective] = useState('')
  const [revisionId, setRevisionId] = useState('')
  const [candidateLabel, setCandidateLabel] = useState('')
  const [candidateArtifactId, setCandidateArtifactId] = useState('')
  const [variablesText, setVariablesText] = useState('{\n  "dopant": "Ni"\n}')
  const [decisionAction, setDecisionAction] = useState('advance')
  const [decisionRationale, setDecisionRationale] = useState('')
  const [decisionCandidateId, setDecisionCandidateId] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = async (preferredId?: string) => {
    if (!projectId) {
      setCampaigns([])
      setSelectedId('')
      setCandidates([])
      setDecisions([])
      return
    }
    const records = await api.campaigns(projectId)
    setCampaigns(records)
    const nextId =
      preferredId ??
      (records.some((item) => item.campaign_id === selectedId)
        ? selectedId
        : records[0]?.campaign_id ?? '')
    setSelectedId(nextId)
    if (nextId) {
      const detail = await api.campaignDetail(projectId, nextId)
      setCandidates(detail.candidates)
      setDecisions(detail.decisions)
    } else {
      setCandidates([])
      setDecisions([])
    }
  }

  useEffect(() => {
    void refresh().catch((error: unknown) => {
      onMessage(
        'error',
        error instanceof Error
          ? error.message
          : tr('Campaign 加载失败。', 'Failed to load campaigns.'),
      )
    })
    // The selected campaign belongs to the previous project and must not drive reloads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const createCampaign = async () => {
    if (!projectId) return
    setBusy(true)
    try {
      const campaign = await api.createCampaign(projectId, {
        title,
        objective,
        ...(revisionId ? { workflow_revision_id: revisionId } : {}),
      })
      setTitle('')
      setObjective('')
      await refresh(campaign.campaign_id)
      onMessage(
        'success',
        tr(
          `Campaign“${campaign.title}”已创建。`,
          `Campaign “${campaign.title}” was created.`,
        ),
      )
    } catch (error) {
      onMessage(
        'error',
        error instanceof Error
          ? error.message
          : tr('Campaign 创建失败。', 'Failed to create the campaign.'),
      )
    } finally {
      setBusy(false)
    }
  }

  const selectCampaign = async (campaignId: string) => {
    if (!projectId) return
    setSelectedId(campaignId)
    setBusy(true)
    try {
      const detail = await api.campaignDetail(projectId, campaignId)
      setCandidates(detail.candidates)
      setDecisions(detail.decisions)
    } catch (error) {
      onMessage(
        'error',
        error instanceof Error ? error.message : tr('加载失败。', 'Failed to load.'),
      )
    } finally {
      setBusy(false)
    }
  }

  const addCandidate = async () => {
    if (!projectId || !selectedId) return
    setBusy(true)
    try {
      const variables = JSON.parse(variablesText) as Record<string, unknown>
      const candidate = await api.addCampaignCandidate(projectId, selectedId, {
        label: candidateLabel,
        ...(candidateArtifactId
          ? { structure_artifact_id: candidateArtifactId }
          : {}),
        variables,
      })
      setCandidateLabel('')
      setDecisionCandidateId(candidate.candidate_id)
      await refresh(selectedId)
      onMessage('success', tr('候选已加入 Campaign。', 'Candidate added to campaign.'))
    } catch (error) {
      onMessage(
        'error',
        error instanceof Error
          ? error.message
          : tr('候选添加失败。', 'Failed to add the candidate.'),
      )
    } finally {
      setBusy(false)
    }
  }

  const recordDecision = async () => {
    if (!projectId || !selectedId) return
    setBusy(true)
    try {
      await api.recordCampaignDecision(projectId, selectedId, {
        action: decisionAction,
        rationale: decisionRationale,
        ...(decisionCandidateId ? { candidate_id: decisionCandidateId } : {}),
      })
      setDecisionRationale('')
      await refresh(selectedId)
      onMessage('success', tr('科研决策已追加记录。', 'Research decision appended.'))
    } catch (error) {
      onMessage(
        'error',
        error instanceof Error
          ? error.message
          : tr('决策记录失败。', 'Failed to record the decision.'),
      )
    } finally {
      setBusy(false)
    }
  }

  if (!projectId) {
    return (
      <section className="campaign-empty">
        <Target size={30} />
        <strong>{tr('请先创建或打开项目', 'Create or open a project first')}</strong>
        <span>
          {tr(
            'Campaign 是项目中的长期候选与决策记录。',
            'A campaign is a long-running candidate and decision record inside a project.',
          )}
        </span>
      </section>
    )
  }

  return (
    <section className="campaign-workbench">
      <header className="section-heading">
        <div>
          <span className="eyebrow">RESEARCH CAMPAIGN</span>
          <h2>{tr('长期筛选与设计', 'Long-running screening and design')}</h2>
          <p>
            {tr(
              'Campaign 组织候选、工作流版本和科研决策，不替代可编辑节点图。',
              'Campaigns organize candidates, workflow revisions, and research decisions without replacing the editable graph.',
            )}
          </p>
        </div>
        <button
          className="ghost-button"
          disabled={busy}
          onClick={() => void refresh()}
          type="button"
        >
          <RefreshCw size={15} /> {tr('刷新', 'Refresh')}
        </button>
      </header>

      <div className="campaign-layout">
        <aside className="campaign-list-panel">
          <div className="panel-title">
            <span>Campaigns</span>
            <small>{campaigns.length}</small>
          </div>
          <div className="campaign-list">
            {campaigns.map((campaign) => (
              <button
                className={selectedId === campaign.campaign_id ? 'active' : ''}
                key={campaign.campaign_id}
                onClick={() => void selectCampaign(campaign.campaign_id)}
                type="button"
              >
                <Target size={15} />
                <span>
                  <strong>{campaign.title}</strong>
                  <small>
                    {campaign.candidate_count} {tr('个候选', 'candidates')} ·{' '}
                    {campaign.status}
                  </small>
                </span>
                <ArrowRight size={13} />
              </button>
            ))}
          </div>
          <div className="campaign-create-form">
            <h3>{tr('新建 Campaign', 'New campaign')}</h3>
            <label>
              {tr('名称', 'Title')}
              <input onChange={(event) => setTitle(event.target.value)} value={title} />
            </label>
            <label>
              {tr('研究目标', 'Objective')}
              <textarea
                onChange={(event) => setObjective(event.target.value)}
                rows={3}
                value={objective}
              />
            </label>
            <label>
              {tr('固定工作流版本（可选）', 'Workflow revision (optional)')}
              <select
                onChange={(event) => setRevisionId(event.target.value)}
                value={revisionId}
              >
                <option value="">{tr('暂不绑定', 'Not bound')}</option>
                {revisions.map((revision) => (
                  <option key={revision.revision_id} value={revision.revision_id}>
                    {revision.title || revision.revision_id}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="primary-button"
              disabled={busy || !title.trim()}
              onClick={() => void createCampaign()}
              type="button"
            >
              <Plus size={15} /> {tr('创建', 'Create')}
            </button>
          </div>
        </aside>

        <div className="campaign-detail">
          {!selectedId ? (
            <div className="campaign-empty">
              <FlaskConical size={28} />
              <strong>{tr('创建第一个 Campaign', 'Create the first campaign')}</strong>
            </div>
          ) : (
            <>
              <section className="campaign-form-card">
                <div className="card-heading">
                  <div>
                    <span className="eyebrow">CANDIDATE</span>
                    <h3>{tr('加入候选', 'Add candidate')}</h3>
                  </div>
                  <Beaker size={19} />
                </div>
                <div className="campaign-form-grid">
                  <label>
                    {tr('候选名称', 'Candidate label')}
                    <input
                      onChange={(event) => setCandidateLabel(event.target.value)}
                      value={candidateLabel}
                    />
                  </label>
                  <label>
                    {tr('结构 Artifact（可选）', 'Structure artifact (optional)')}
                    <select
                      onChange={(event) => setCandidateArtifactId(event.target.value)}
                      value={candidateArtifactId}
                    >
                      <option value="">{tr('暂不绑定', 'Not bound')}</option>
                      {artifacts.map((artifact) => (
                        <option key={artifact.artifact_id} value={artifact.artifact_id}>
                          {artifact.inspection.record?.reduced_formula ??
                            artifact.original_filename}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="wide">
                    {tr('设计变量 JSON', 'Design variables JSON')}
                    <textarea
                      className="mono-input"
                      onChange={(event) => setVariablesText(event.target.value)}
                      rows={4}
                      value={variablesText}
                    />
                  </label>
                </div>
                <button
                  className="secondary-button accent"
                  disabled={busy || !candidateLabel.trim()}
                  onClick={() => void addCandidate()}
                  type="button"
                >
                  <Plus size={15} /> {tr('加入候选', 'Add candidate')}
                </button>
              </section>

              <section className="campaign-candidate-table">
                <div className="panel-title">
                  <span>{tr('候选队列', 'Candidate queue')}</span>
                  <small>{candidates.length}</small>
                </div>
                {candidates.map((candidate) => (
                  <article key={candidate.candidate_id}>
                    <span className={`candidate-state state-${candidate.status}`} />
                    <div>
                      <strong>{candidate.label}</strong>
                      <code>{JSON.stringify(candidate.variables)}</code>
                    </div>
                    <span>{candidate.status}</span>
                    <button
                      onClick={() => setDecisionCandidateId(candidate.candidate_id)}
                      type="button"
                    >
                      {tr('选择', 'Select')}
                    </button>
                  </article>
                ))}
                {candidates.length === 0 && (
                  <p className="panel-empty">
                    {tr('尚无候选。', 'No candidates yet.')}
                  </p>
                )}
              </section>

              <section className="campaign-form-card">
                <div className="card-heading">
                  <div>
                    <span className="eyebrow">DECISION LOG</span>
                    <h3>{tr('追加科研决策', 'Append research decision')}</h3>
                  </div>
                  <CheckCircle2 size={19} />
                </div>
                <div className="campaign-form-grid">
                  <label>
                    {tr('候选（可选）', 'Candidate (optional)')}
                    <select
                      onChange={(event) => setDecisionCandidateId(event.target.value)}
                      value={decisionCandidateId}
                    >
                      <option value="">{tr('Campaign 整体', 'Whole campaign')}</option>
                      {candidates.map((candidate) => (
                        <option key={candidate.candidate_id} value={candidate.candidate_id}>
                          {candidate.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {tr('动作', 'Action')}
                    <select
                      onChange={(event) => setDecisionAction(event.target.value)}
                      value={decisionAction}
                    >
                      <option value="advance">{tr('推进', 'Advance')}</option>
                      <option value="hold">{tr('暂缓', 'Hold')}</option>
                      <option value="exclude">{tr('排除', 'Exclude')}</option>
                      <option value="repeat">{tr('复算', 'Repeat')}</option>
                    </select>
                  </label>
                  <label className="wide">
                    {tr('依据', 'Rationale')}
                    <textarea
                      onChange={(event) => setDecisionRationale(event.target.value)}
                      rows={3}
                      value={decisionRationale}
                    />
                  </label>
                </div>
                <button
                  className="secondary-button"
                  disabled={busy || !decisionRationale.trim()}
                  onClick={() => void recordDecision()}
                  type="button"
                >
                  <CheckCircle2 size={15} /> {tr('记录决策', 'Record decision')}
                </button>
                <div className="decision-log">
                  {decisions.map((decision) => (
                    <article key={decision.decision_id}>
                      <strong>{decision.action}</strong>
                      <p>{decision.rationale}</p>
                      <small>{decision.recorded_at_utc}</small>
                    </article>
                  ))}
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </section>
  )
}
