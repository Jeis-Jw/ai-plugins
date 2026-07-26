export const meta = {
  name: 'studio-solo',
  description: 'One production crew call for an item with an upstream criterion source and mechanical pass/fail measures.',
  phases: [{ title: 'Produce', detail: 'one crew member produces and verifies the bounded artifact' }],
}

const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const PERSONA = A.persona || null
const CRITERIA = Array.isArray(A.criteria) ? A.criteria : []
const WT = A.worktreePath || null
const BRANCH = A.branch || null
const REQUESTED_RUNTIME = A.agentRuntime || null
const RUNTIME_CAPABILITY = A.runtimeCapability || null
const AGENT_RUNTIME = REQUESTED_RUNTIME && RUNTIME_CAPABILITY
  && RUNTIME_CAPABILITY.runtime === REQUESTED_RUNTIME
  && RUNTIME_CAPABILITY.verified === true
  && RUNTIME_CAPABILITY.dispatch_allowed === true
  ? REQUESTED_RUNTIME
  : null

const invalidCriterion = CRITERIA.some(c => !c || typeof c.id !== 'string'
  || typeof c.source_ref !== 'string' || !c.source_ref.trim()
  || typeof c.measure !== 'string' || !c.measure.trim()
  || c.mechanical !== true)
if (!PERSONA || typeof PERSONA.name !== 'string' || !WT || !CRITERIA.length || invalidCriterion) {
  return {
    ritual: 'solo',
    error: 'solo requires one persona, a producer-prepared worktreePath, and upstream criteria with source_ref, mechanical measure, and mechanical:true',
    participants: PERSONA ? [PERSONA.name] : [],
  }
}
if (REQUESTED_RUNTIME && !['claude', 'codex'].includes(REQUESTED_RUNTIME)) {
  return { ritual: 'solo', error: 'agentRuntime must be claude or codex', participants: [PERSONA.name] }
}
if (REQUESTED_RUNTIME && !AGENT_RUNTIME) {
  return { ritual: 'solo', error: 'agentRuntime requires a matching verified runtimeCapability', participants: [PERSONA.name] }
}

const POLICY = A.agentPolicy || {}
const OVERRIDE = A.overrides || {}
function policyFor() {
  const role = PERSONA.roleId || PERSONA.name
  const agentId = PERSONA.agentId || PERSONA.name
  const provider = AGENT_RUNTIME ? ((POLICY.providers || {})[AGENT_RUNTIME] || {}) : {}
  const layers = [
    OVERRIDE,
    (((provider.rituals || {}).solo || {}).produce) || {},
    (((POLICY.rituals || {}).solo || {}).produce) || {},
    (provider.agents || {})[agentId] || {},
    (POLICY.agents || {})[agentId] || {},
    (provider.roles || {})[role] || {},
    (POLICY.roles || {})[role] || {},
    provider.defaults || {},
    POLICY.defaults || {},
  ]
  const pick = key => layers.map(layer => layer[key]).find(value => value !== null && value !== undefined && value !== '') || null
  const options = { agentId }
  const model = pick('model'); if (model) options.model = model
  const effort = pick('effort'); if (effort) options.effort = effort
  if (AGENT_RUNTIME) options.agentRuntime = AGENT_RUNTIME
  return options
}

const RESULT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['synthesis', 'changedFiles', 'verification', 'blockedChecks', 'criterionResults'],
  properties: {
    synthesis: { type: 'string' },
    changedFiles: { type: 'array', items: { type: 'string' } },
    verification: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false, required: ['command', 'result'],
        properties: { command: { type: 'string' }, result: { type: 'string' } },
      },
    },
    blockedChecks: { type: 'array', items: { type: 'string' } },
    criterionResults: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false, required: ['id', 'pass', 'evidence'],
        properties: { id: { type: 'string' }, pass: { type: 'boolean' }, evidence: { type: 'string' } },
      },
    },
  },
}

const startedMs = Date.now()
const startedAt = new Date(startedMs).toISOString()
const runId = A.runId || `RUN-studio-solo-${startedMs}-${Math.random().toString(36).slice(2, 8)}`
const spentStart = budget.spent()
phase('Produce')
const result = await agent([
  'You are the sole production crew member for a mechanically bounded Studio item.',
  'Do not reinterpret criteria or make subjective domain decisions. Stop and report a blocked check if the upstream contract is insufficient.',
  `Objective: ${A.objective || '(no objective)'}`,
  `Worktree: ${WT}`,
  `Criteria: ${JSON.stringify(CRITERIA, null, 2)}`,
  PERSONA.body || '',
].join('\n'), { schema: RESULT_SCHEMA, label: `solo:${PERSONA.name}`, phase: 'Produce', ...policyFor() })
const finishedMs = Date.now()
const finishedAt = new Date(finishedMs).toISOString()
const spentEnd = budget.spent()
const tokenDelta = Number.isInteger(spentStart) && Number.isInteger(spentEnd) && spentEnd >= spentStart
  ? spentEnd - spentStart : null
const resultById = new Map(((result && result.criterionResults) || []).map(item => [item.id, item]))
const criteriaPass = CRITERIA.every(c => {
  const item = resultById.get(c.id)
  return item && item.pass === true && typeof item.evidence === 'string' && item.evidence.trim()
})
const verification = (result && result.verification) || []
const blockedChecks = (result && result.blockedChecks) || []
const changedFiles = (result && result.changedFiles) || []
const productionReady = criteriaPass && changedFiles.length > 0 && blockedChecks.length === 0
  && verification.some(item => item && /^pass(?:\b|:)/i.test(item.result || ''))
const receipt = {
  schema: 'workflow-receipt/v1', emitter: 'studio', workflow: 'studio-solo', run_id: runId,
  started_at: startedAt, finished_at: finishedAt, elapsed_ms: finishedMs - startedMs,
  tokens: tokenDelta, token_coverage: tokenDelta === null ? 'unavailable' : 'exact',
  counters: { model_calls: 1, rounds: 1, participants: 1, valid_deltas: 0, dry_deltas: 0 },
  quality: {
    criterion_pass: criteriaPass, production_ready: productionReady,
    interaction_applicable: false, theatre: false,
    model_call_coverage: 'exact', elapsed_coverage: 'exact',
    token_savings_claim_eligible: tokenDelta !== null,
  },
}
return {
  run_id: runId, ritual: 'solo', production_profile: 'solo-mechanical',
  participants: [PERSONA.name], synthesis: (result && result.synthesis) || '(producer failed)',
  minority: 'not-applicable', delta_log: [],
  verdict: { alive: productionReady, reason: productionReady ? 'mechanical criteria and verification passed' : 'mechanical production evidence incomplete' },
  proposals: [], worktreePath: WT, branch: BRANCH, changedFiles, verification, blockedChecks,
  criterionResults: (result && result.criterionResults) || [],
  developmentReady: productionReady, readyForIntegration: false,
  cost: { tokens: tokenDelta, token_coverage: receipt.token_coverage, elapsed_ms: receipt.elapsed_ms, rounds: 1 },
  receipt,
}
