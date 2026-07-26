import { createHash } from 'node:crypto'

export const PERSISTENT_BRAINSTORM_SCHEMA = 'studio-persistent-brainstorm/v1'
export const ACTION_SCHEMA = 'studio-crew-action/v1'
export const CAPABILITY_SCHEMA = 'studio-native-persistent-capability/v1'
export const REQUIRED_CAPABILITIES = Object.freeze([
  'spawn',
  'followup',
  'wait_barrier',
  'interrupt_cancel',
  'structured_result',
])
const DELTA_ANCHORS = Object.freeze([
  'artifact',
  'acceptance-criteria',
  'risk',
  'rejected-alternative',
  'repro-test',
])

export class PersistentBrokerError extends Error {
  constructor(code, message) {
    super(message)
    this.name = 'PersistentBrokerError'
    this.code = code
  }
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function digest(value) {
  return `sha256:${createHash('sha256').update(canonicalJson(value), 'utf8').digest('hex')}`
}

function safeSlug(value, fallback = 'crew') {
  const slug = String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32)
  return slug || fallback
}

function positiveInteger(value, fallback, label) {
  const resolved = value ?? fallback
  if (!Number.isInteger(resolved) || resolved < 1) {
    throw new PersistentBrokerError('invalid_config', `${label} must be a positive integer`)
  }
  return resolved
}

function validateCapability(capability) {
  if (
    !capability
    || capability.schema !== CAPABILITY_SCHEMA
    || capability.verified !== true
    || typeof capability.card_title_projection !== 'boolean'
    || REQUIRED_CAPABILITIES.some(key => capability[key] !== true)
  ) {
    throw new PersistentBrokerError(
      'native_capability_required',
      `native persistent brainstorm requires verified ${REQUIRED_CAPABILITIES.join(', ')}`,
    )
  }
  return {
    schema: CAPABILITY_SCHEMA,
    verified: true,
    spawn: true,
    followup: true,
    wait_barrier: true,
    interrupt_cancel: true,
    structured_result: true,
    card_title_projection: capability.card_title_projection,
  }
}

function actor(input, runId, workflowName, namespace) {
  const crew = String(input.crew || input.name || '').trim()
  const role = String(input.role || '').trim()
  if (!crew || !role) throw new PersistentBrokerError('invalid_actor', 'crew and role are required')
  const seed = `${runId}:${namespace}:${crew}:${role}`
  const suffix = digest(seed).slice(7, 17)
  const logicalHandle = `${namespace}-${safeSlug(crew, namespace)}-${suffix}`
  const taskName = `studio-${safeSlug(crew, namespace)}-${safeSlug(workflowName, 'workflow')}-${safeSlug(role, 'role')}-${suffix}`
    .slice(0, 80)
  return {
    actor_id: `${namespace}:${crew}`,
    kind: namespace,
    crew,
    role,
    prior: String(input.prior || ''),
    body: String(input.body || ''),
    logical_handle: logicalHandle,
    task_name: taskName,
    canonical_label: `[studio:${crew}] ${workflowName} - ${role}`,
    host_handle: null,
    spawn_count: 0,
  }
}

function summary(actorValue, phase, round, currentTask) {
  const stage = round === null ? phase : `${phase} round ${round}`
  return {
    canonical_label: actorValue.canonical_label,
    stage,
    current_task: currentTask,
  }
}

function turnSchema(kind) {
  if (kind === 'participant') {
    return {
      type: 'object',
      additionalProperties: false,
      required: ['utterance', 'deltas'],
      properties: {
        utterance: { type: 'string' },
        deltas: {
          type: 'array',
          items: {
            type: 'object',
            additionalProperties: false,
            required: ['changed_what', 'anchor', 'evidence'],
            properties: {
              changed_what: { type: 'string' },
              anchor: { type: 'string', enum: DELTA_ANCHORS },
              evidence: { type: 'string' },
              rejected_alternative: { type: 'string' },
            },
          },
        },
      },
    }
  }
  if (kind === 'critic') {
    return {
      type: 'object',
      additionalProperties: false,
      required: ['verified'],
      properties: {
        verified: {
          type: 'array',
          items: {
            type: 'object',
            additionalProperties: false,
            required: ['id', 'valid', 'reason'],
            properties: {
              id: { type: 'integer' },
              valid: { type: 'boolean' },
              reason: { type: 'string' },
            },
          },
        },
      },
    }
  }
  return {
    type: 'object',
    additionalProperties: false,
    required: ['synthesis', 'minority', 'proposals'],
    properties: {
      synthesis: { type: 'string' },
      minority: { type: 'string' },
      proposals: { type: 'array' },
    },
  }
}

function promptFor(state, actorValue, stage, round) {
  const transcript = state.transcript || '(empty)'
  if (actorValue.kind === 'participant') {
    const instruction = stage === 'Diverge'
      ? 'Give an independent take. You cannot see other participants. Return only the required structured result.'
      : `Round ${round}: rebut, refine, or propose something new. Agreement summaries are not contributions.`
    return [
      `Agenda: ${state.agenda}`,
      `Canonical identity: ${actorValue.canonical_label}`,
      `Role prior: ${actorValue.prior}`,
      actorValue.body,
      `Transcript:\n${stage === 'Diverge' ? '(blind)' : transcript}`,
      instruction,
    ].filter(Boolean).join('\n\n')
  }
  if (actorValue.kind === 'critic') {
    return [
      `Canonical identity: ${actorValue.canonical_label}`,
      'Verification only. Do not create, strengthen, reorder, or synthesize participant deltas.',
      `Submitted deltas:\n${JSON.stringify(state.round_submitted)}`,
    ].join('\n\n')
  }
  return [
    `Canonical identity: ${actorValue.canonical_label}`,
    'Summarize only the supplied transcript and verified deltas. Do not invent positions or deltas.',
    `Transcript:\n${transcript}`,
    `Verified deltas:\n${JSON.stringify(state.delta_log)}`,
  ].join('\n\n')
}

function makeAction(state, actorValue, kind, phase, round, prompt, outputSchema = turnSchema(actorValue.kind)) {
  const ordinal = state.next_ordinal++
  const currentTask = kind === 'spawn'
    ? `Initial ${phase} assignment`
    : `${phase}${round === null ? '' : ` round ${round}`} continuation`
  return {
    schema: ACTION_SCHEMA,
    run_id: state.run_id,
    action_id: `${state.run_id}:a${String(ordinal).padStart(4, '0')}`,
    ordinal,
    kind,
    actor_id: actorValue.actor_id,
    logical_handle: actorValue.logical_handle,
    host_handle: kind === 'spawn' ? null : actorValue.host_handle,
    task_name: actorValue.task_name,
    canonical_label: actorValue.canonical_label,
    phase,
    round,
    barrier_id: `${state.run_id}:b${String(state.next_barrier).padStart(4, '0')}`,
    initial_summary: kind === 'spawn' ? summary(actorValue, phase, round, currentTask) : null,
    current_task_summary: summary(actorValue, phase, round, currentTask),
    card_title_projection: {
      supported: state.capability.card_title_projection,
      claimed: state.capability.card_title_projection,
    },
    prompt,
    output_schema: outputSchema,
    prompt_schema_digest: digest({ prompt, output_schema: outputSchema }),
  }
}

function setPending(state, actions) {
  const barrierId = `${state.run_id}:b${String(state.next_barrier).padStart(4, '0')}`
  state.next_barrier += 1
  state.pending = {
    barrier_id: barrierId,
    action_ids: actions.map(action => action.action_id),
    actions,
  }
  state.ledger.push(...actions.map(action => ({ ...action, event: 'dispatch' })))
}

function actionFor(state, actorValue, phase, round) {
  const kind = actorValue.spawn_count === 0 ? 'spawn' : 'followup'
  return makeAction(state, actorValue, kind, phase, round, promptFor(state, actorValue, phase, round))
}

function scheduleDiverge(state) {
  state.phase = 'Diverge'
  state.round = 0
  setPending(state, state.participants.map(value => actionFor(state, value, 'Diverge', 0)))
}

function scheduleDebateParticipant(state) {
  state.phase = 'Debate'
  const participant = state.participants[state.participant_cursor]
  setPending(state, [actionFor(state, participant, 'Debate', state.round)])
}

function scheduleCritic(state) {
  const critic = state.critic
  setPending(state, [actionFor(state, critic, 'Debate', state.round)])
}

function scheduleConverge(state) {
  state.phase = 'Converge'
  state.round = null
  setPending(state, [actionFor(state, state.summarizer, 'Converge', null)])
}

function scheduleFinalCritic(state) {
  state.phase = 'Verdict'
  state.round = null
  const critic = state.critic
  const kind = critic.spawn_count === 0 ? 'spawn' : 'followup'
  const schema = {
    type: 'object',
    required: ['alive', 'reason'],
    properties: {
      alive: { type: 'boolean' },
      reason: { type: 'string' },
    },
  }
  const prompt = [
    `Canonical identity: ${critic.canonical_label}`,
    'Final verification only. Do not add, strengthen, reorder, or synthesize deltas.',
    'alive=true only when the verified delta log proves a concrete state change.',
    `Verified deltas:\n${JSON.stringify(state.delta_log)}`,
    `Broker synthesis:\n${JSON.stringify(state.converge_synthesis)}`,
  ].join('\n\n')
  setPending(state, [makeAction(state, critic, kind, 'Verdict', null, prompt, schema)])
}

function validateReceipt(state, receipt) {
  if (!state.pending) throw new PersistentBrokerError('unexpected_result', 'no action barrier is pending')
  if (!receipt || receipt.schema !== 'studio-crew-barrier-result/v1') {
    throw new PersistentBrokerError('invalid_result', 'barrier result schema is invalid')
  }
  if (receipt.barrier_id !== state.pending.barrier_id) {
    throw new PersistentBrokerError('late_result', 'barrier result is stale or belongs to another run')
  }
  if (!Array.isArray(receipt.results) || receipt.results.length !== state.pending.action_ids.length) {
    throw new PersistentBrokerError('invalid_result', 'barrier result cardinality differs from dispatched actions')
  }
  receipt.results.forEach((result, index) => {
    if (result.action_id !== state.pending.action_ids[index]) {
      throw new PersistentBrokerError('result_reordered', 'Producer/main must preserve canonical action order')
    }
    if (!['succeeded', 'failed', 'cancelled'].includes(result.status)) {
      throw new PersistentBrokerError('invalid_result', 'action result status is invalid')
    }
  })
}

function applyActorResult(state, action, result) {
  const actorValue = [...state.participants, state.critic, state.summarizer]
    .find(value => value.actor_id === action.actor_id)
  if (!actorValue) throw new PersistentBrokerError('invalid_actor', 'action actor is not registered')
  if (action.kind === 'spawn') {
    if (actorValue.spawn_count !== 0) {
      throw new PersistentBrokerError('spawn_identity_invalid', 'an actor may be spawned only once')
    }
    if (result.status === 'succeeded' && !result.host_handle) {
      throw new PersistentBrokerError('spawn_identity_invalid', 'successful spawn requires a host handle')
    }
    if (result.host_handle) {
      actorValue.spawn_count = 1
      actorValue.host_handle = String(result.host_handle)
    }
  } else if (actorValue.spawn_count !== 1 || result.host_handle !== actorValue.host_handle) {
    throw new PersistentBrokerError('followup_identity_invalid', 'follow-up must target the original host handle')
  }
  state.ledger.push({
    event: 'result',
    action_id: action.action_id,
    ordinal: action.ordinal,
    actor_id: action.actor_id,
    logical_handle: action.logical_handle,
    host_handle: actorValue.host_handle,
    status: result.status,
    tokens: result.tokens ?? null,
    token_coverage: result.tokens === null || result.tokens === undefined ? 'unavailable' : 'exact',
  })
}

function finishAbort(state) {
  state.status = 'aborted'
  state.phase = 'Aborted'
  state.pending = null
  state.fallback_allowed = false
  state.finished_at = new Date().toISOString()
  return state
}

function abort(state, failed) {
  state.status = 'cancelling'
  state.phase = 'Cancel'
  state.failure = {
    action_id: failed.action.action_id,
    status: failed.result.status,
    error: failed.result.error || 'native action failed',
  }
  state.fallback_allowed = false
  state.pending = null
  const live = [...state.participants, state.critic, state.summarizer]
    .filter(value => value.spawn_count === 1 && value.host_handle)
  if (live.length === 0) return finishAbort(state)
  const actions = live.map(value => makeAction(
    state,
    value,
    'interrupt',
    'Cancel',
    null,
    `Cancel run ${state.run_id}; discard late output and do not respawn.`,
    {
      type: 'object',
      required: ['cancelled'],
      properties: { cancelled: { type: 'boolean' } },
    },
  ))
  setPending(state, actions)
  return state
}

function processParticipantOutput(state, participant, output, stage) {
  const utterance = String((output || {}).utterance || '')
  state.transcript += `${state.transcript ? '\n\n' : ''}[${stage}] ${participant.crew}: ${utterance}`
  if (stage.startsWith('r')) {
    for (const delta of (output || {}).deltas || []) {
      state.round_submitted.push({
        id: state.round_submitted.length,
        round: state.round,
        by: participant.crew,
        ...delta,
      })
    }
  }
}

function finish(state, verdict) {
  const resultEntries = state.ledger.filter(item => item.event === 'result')
  const measured = resultEntries.map(item => item.tokens)
  const exactTokens = measured.length > 0 && measured.every(value => Number.isInteger(value) && value >= 0)
    ? measured.reduce((sum, value) => sum + value, 0)
    : null
  state.status = 'completed'
  state.phase = 'Complete'
  state.pending = null
  state.finished_at = new Date().toISOString()
  state.output = {
    run_id: state.run_id,
    ritual: 'brainstorm',
    participants: state.participants.map(value => value.crew),
    synthesis: state.converge_synthesis.synthesis,
    minority: state.converge_synthesis.minority,
    proposals: state.converge_synthesis.proposals || [],
    delta_log: [...state.delta_log, ...state.dry_log],
    verdict,
    persistent_crew: {
      capability: state.capability,
      actors: [...state.participants, state.critic, state.summarizer].map(value => ({
        actor_id: value.actor_id,
        logical_handle: value.logical_handle,
        host_handle: value.host_handle,
        task_name: value.task_name,
        canonical_label: value.canonical_label,
        spawn_count: value.spawn_count,
      })),
      action_ledger: state.ledger,
      fallback_allowed: false,
    },
    cost: {
      tokens: exactTokens,
      token_coverage: exactTokens === null ? 'unavailable' : 'exact',
      rounds: state.rounds_run,
    },
  }
  return state
}

export function createPersistentBrainstorm(input) {
  if (input.admission !== 'canary') {
    throw new PersistentBrokerError(
      'canary_admission_required',
      'persistent brainstorm is canary-only and is not a production default',
    )
  }
  const capability = validateCapability(input.capability)
  const workflowName = String(input.workflow_name || '').trim()
  const runId = String(input.run_id || '').trim()
  if (!workflowName || !runId) {
    throw new PersistentBrokerError('invalid_config', 'run_id and workflow_name are required')
  }
  if (!Array.isArray(input.personas) || input.personas.length < 2) {
    throw new PersistentBrokerError('invalid_config', 'brainstorm needs at least two personas')
  }
  const participants = input.personas.map(value => actor(value, runId, workflowName, 'participant'))
  if (new Set(participants.map(value => value.actor_id)).size !== participants.length) {
    throw new PersistentBrokerError('invalid_actor', 'crew names must be unique')
  }
  const state = {
    schema: PERSISTENT_BRAINSTORM_SCHEMA,
    run_id: runId,
    workflow_name: workflowName,
    agenda: String(input.agenda || '(no agenda provided)'),
    capability,
    admission: 'canary',
    config: {
      max_rounds: positiveInteger(input.maxRounds, 4, 'maxRounds'),
      dry_stop: positiveInteger(input.dryStop, 2, 'dryStop'),
    },
    participants,
    critic: actor({ crew: 'critic', role: '독립 검증' }, runId, workflowName, 'critic'),
    summarizer: actor({ crew: 'summarizer', role: '중립 수렴' }, runId, workflowName, 'summarizer'),
    status: 'running',
    phase: 'Diverge',
    round: 0,
    rounds_run: 0,
    dry_count: 0,
    participant_cursor: 0,
    transcript: '',
    round_submitted: [],
    delta_log: [],
    dry_log: [],
    ledger: [],
    next_ordinal: 1,
    next_barrier: 1,
    pending: null,
    native_started: true,
    fallback_allowed: false,
    failure: null,
    output: null,
    converge_synthesis: null,
  }
  scheduleDiverge(state)
  return state
}

export function applyPersistentBarrier(state, receipt) {
  if (!['running', 'cancelling'].includes(state.status)) {
    throw new PersistentBrokerError('late_result', `run is already ${state.status}`)
  }
  validateReceipt(state, receipt)
  const pending = state.pending
  if (state.status === 'cancelling') {
    pending.actions.forEach((action, index) => applyActorResult(state, action, receipt.results[index]))
    return finishAbort(state)
  }
  const failed = pending.actions
    .map((action, index) => ({ action, result: receipt.results[index] }))
    .find(value => value.result.status !== 'succeeded')
  pending.actions.forEach((action, index) => applyActorResult(state, action, receipt.results[index]))
  if (failed) return abort(state, failed)
  state.pending = null

  if (state.phase === 'Diverge') {
    state.participants.forEach((participant, index) => {
      processParticipantOutput(state, participant, receipt.results[index].output, 'diverge')
    })
    state.round = 1
    state.rounds_run = 1
    state.participant_cursor = 0
    state.round_submitted = []
    scheduleDebateParticipant(state)
    return state
  }

  if (state.phase === 'Debate' && pending.actions[0].actor_id.startsWith('participant:')) {
    const participant = state.participants[state.participant_cursor]
    processParticipantOutput(state, participant, receipt.results[0].output, `r${state.round}`)
    state.participant_cursor += 1
    if (state.participant_cursor < state.participants.length) scheduleDebateParticipant(state)
    else scheduleCritic(state)
    return state
  }

  if (state.phase === 'Debate') {
    const verified = new Map(((receipt.results[0].output || {}).verified || []).map(value => [value.id, value]))
    let valid = 0
    for (const submission of state.round_submitted) {
      const verdict = verified.get(submission.id)
      if (verdict && verdict.valid === true) {
        state.delta_log.push(submission)
        valid += 1
      } else {
        state.dry_log.push({ ...submission, dry: true })
      }
    }
    state.dry_count = valid === 0 ? state.dry_count + 1 : 0
    if (state.dry_count >= state.config.dry_stop || state.round >= state.config.max_rounds) {
      scheduleConverge(state)
    } else {
      state.round += 1
      state.rounds_run = state.round
      state.participant_cursor = 0
      state.round_submitted = []
      scheduleDebateParticipant(state)
    }
    return state
  }

  if (state.phase === 'Converge') {
    state.converge_synthesis = receipt.results[0].output || {
      synthesis: '(summarizer returned no output)',
      minority: 'none',
      proposals: [],
    }
    scheduleFinalCritic(state)
    return state
  }

  if (state.phase === 'Verdict') {
    return finish(state, receipt.results[0].output || {
      alive: state.delta_log.length > 0,
      reason: 'critic returned no output',
    })
  }
  throw new PersistentBrokerError('invalid_state', `unsupported phase ${state.phase}`)
}

export function persistentBrainstormEnvelope(state) {
  return {
    schema: 'studio-persistent-brainstorm-envelope/v1',
    run_id: state.run_id,
    status: state.status,
    phase: state.phase,
    round: state.round,
    max_rounds: state.config.max_rounds,
    dry_stop: state.config.dry_stop,
    native_started: state.native_started,
    fallback_allowed: state.fallback_allowed,
    capability: state.capability,
    admission: state.admission,
    pending: state.pending,
    actors: [...state.participants, state.critic, state.summarizer].map(value => ({
      actor_id: value.actor_id,
      logical_handle: value.logical_handle,
      host_handle: value.host_handle,
      task_name: value.task_name,
      canonical_label: value.canonical_label,
      spawn_count: value.spawn_count,
      initial_summary: summary(value, state.phase, state.round, 'Initial/current task identity'),
      current_task_summary: summary(value, state.phase, state.round, 'Await canonical broker action'),
    })),
    ledger: state.ledger,
    output: state.output,
    failure: state.failure,
  }
}
