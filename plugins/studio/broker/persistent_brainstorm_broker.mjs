import { createHash } from 'node:crypto'

export const PERSISTENT_BRAINSTORM_SCHEMA = 'studio-persistent-brainstorm/v2'
export const ACTION_SCHEMA = 'studio-crew-action/v2'
export const CAPABILITY_SCHEMA = 'studio-native-persistent-capability/v1'
export const BARRIER_RESULT_SCHEMA = 'studio-crew-barrier-result/v2'
export const TASK_NAME_MAX = 64
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
  constructor(code, message, details = {}) {
    super(message)
    this.name = 'PersistentBrokerError'
    this.code = code
    this.details = details
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

function clone(value) {
  return structuredClone(value)
}

function withoutStateDigests(value) {
  if (Array.isArray(value)) return value.map(withoutStateDigests)
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value)
      .filter(([key]) => key !== 'state_digest')
      .map(([key, child]) => [key, withoutStateDigests(child)]))
  }
  return value
}

export function persistentStateDigest(state) {
  return digest(withoutStateDigests(state))
}

function safeSegment(value, fallback = 'crew') {
  const segment = String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return segment || fallback
}

export function collaborationTaskName({ runId, namespace, crew, workflowName, role }) {
  const suffix = digest({
    run_id: String(runId),
    namespace: String(namespace),
    crew: String(crew).normalize('NFKC'),
    workflow_name: String(workflowName).normalize('NFKC'),
    role: String(role).normalize('NFKC'),
  }).slice(7, 19)
  const rawPrefix = [
    'studio',
    safeSegment(namespace, 'crew'),
    safeSegment(crew, 'crew'),
    safeSegment(workflowName, 'workflow'),
    safeSegment(role, 'role'),
  ].join('_')
  const prefixLimit = TASK_NAME_MAX - suffix.length - 1
  const prefix = rawPrefix.slice(0, prefixLimit).replace(/_+$/g, '') || 'studio'
  const taskName = `${prefix}_${suffix}`
  if (!/^[a-z0-9_]+$/.test(taskName) || taskName.length > TASK_NAME_MAX || !taskName.endsWith(suffix)) {
    throw new PersistentBrokerError('task_name_invalid', 'generated task_name violates host contract')
  }
  return taskName
}

function positiveInteger(value, fallback, label) {
  const resolved = value ?? fallback
  if (!Number.isInteger(resolved) || resolved < 1) {
    throw new PersistentBrokerError('invalid_config', `${label} must be a positive integer`)
  }
  return resolved
}

function validateCapability(capability) {
  const expected = new Set([
    'schema', 'verified', 'spawn', 'followup', 'wait_barrier',
    'interrupt_cancel', 'structured_result', 'card_title_projection',
  ])
  if (
    !capability
    || Object.keys(capability).length !== expected.size
    || Object.keys(capability).some(key => !expected.has(key))
    || capability.schema !== CAPABILITY_SCHEMA
    || capability.verified !== true
    || typeof capability.card_title_projection !== 'boolean'
    || REQUIRED_CAPABILITIES.some(key => capability[key] !== true)
  ) {
    throw new PersistentBrokerError(
      'native_capability_required',
      `native persistent brainstorm requires exact verified ${REQUIRED_CAPABILITIES.join(', ')}`,
    )
  }
  return clone(capability)
}

function makeActor(input, runId, workflowName, namespace) {
  const crew = String(input.crew || input.name || '').trim()
  const role = String(input.role || '').trim()
  if (!crew || !role) throw new PersistentBrokerError('invalid_actor', 'crew and role are required')
  const suffix = digest({ runId, namespace, crew, role }).slice(7, 19)
  return {
    actor_id: `${namespace}:${crew}`,
    kind: namespace,
    crew,
    role,
    prior: String(input.prior || ''),
    body: String(input.body || ''),
    logical_handle: `${safeSegment(namespace)}_${safeSegment(crew)}_${suffix}`,
    task_name: collaborationTaskName({ runId, namespace, crew, workflowName, role }),
    canonical_label: `[studio:${crew}] ${workflowName} - ${role}`,
    host_handle: null,
    spawn_count: 0,
    generation: 0,
  }
}

function summary(actor, phase, round, currentTask) {
  return {
    canonical_label: actor.canonical_label,
    stage: round === null ? phase : `${phase} round ${round}`,
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
        utterance: { type: 'string', minLength: 1 },
        deltas: {
          type: 'array',
          items: {
            type: 'object',
            additionalProperties: false,
            required: ['changed_what', 'anchor', 'evidence'],
            properties: {
              changed_what: { type: 'string', minLength: 1 },
              anchor: { type: 'string', enum: DELTA_ANCHORS },
              evidence: { type: 'string', minLength: 1 },
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
              reason: { type: 'string', minLength: 1 },
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
      synthesis: { type: 'string', minLength: 1 },
      minority: { type: 'string', minLength: 1 },
      proposals: { type: 'array', items: { type: 'string' } },
    },
  }
}

function verdictSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    required: ['alive', 'reason'],
    properties: {
      alive: { type: 'boolean' },
      reason: { type: 'string', minLength: 1 },
    },
  }
}

function cancelSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    required: ['cancelled'],
    properties: { cancelled: { type: 'boolean', enum: [true] } },
  }
}

function typeMatches(value, type) {
  if (type === 'array') return Array.isArray(value)
  if (type === 'object') return value !== null && typeof value === 'object' && !Array.isArray(value)
  if (type === 'integer') return Number.isInteger(value)
  if (type === 'number') return typeof value === 'number' && Number.isFinite(value)
  return typeof value === type
}

function validateSchema(value, schema, at = '$') {
  if (!typeMatches(value, schema.type)) {
    throw new PersistentBrokerError('output_schema_mismatch', `${at} must be ${schema.type}`)
  }
  if (schema.enum && !schema.enum.includes(value)) {
    throw new PersistentBrokerError('output_schema_mismatch', `${at} is outside enum`)
  }
  if (typeof value === 'string' && schema.minLength && value.length < schema.minLength) {
    throw new PersistentBrokerError('output_schema_mismatch', `${at} is shorter than minLength`)
  }
  if (Array.isArray(value) && schema.items) {
    value.forEach((item, index) => validateSchema(item, schema.items, `${at}[${index}]`))
  }
  if (schema.type === 'object') {
    for (const key of schema.required || []) {
      if (!Object.hasOwn(value, key)) {
        throw new PersistentBrokerError('output_schema_mismatch', `${at}.${key} is required`)
      }
    }
    if (schema.additionalProperties === false) {
      for (const key of Object.keys(value)) {
        if (!Object.hasOwn(schema.properties, key)) {
          throw new PersistentBrokerError('output_schema_mismatch', `${at}.${key} is not allowed`)
        }
      }
    }
    for (const [key, child] of Object.entries(schema.properties || {})) {
      if (Object.hasOwn(value, key)) validateSchema(value[key], child, `${at}.${key}`)
    }
  }
}

function actorById(state, actorId) {
  return [...state.participants, state.critic, state.summarizer]
    .find(actor => actor.actor_id === actorId)
}

function promptFor(state, actor, phase, round) {
  if (actor.kind === 'participant') {
    return [
      `Agenda: ${state.agenda}`,
      `Canonical identity: ${actor.canonical_label}`,
      `Role prior: ${actor.prior}`,
      actor.body,
      `Transcript:\n${phase === 'Diverge' ? '(blind)' : state.transcript || '(empty)'}`,
      phase === 'Diverge'
        ? 'Give an independent take. Return only the required structured result.'
        : `Round ${round}: rebut, refine, or propose something new; do not summarize agreement.`,
    ].filter(Boolean).join('\n\n')
  }
  if (actor.kind === 'critic') {
    return [
      `Canonical identity: ${actor.canonical_label}`,
      'Verification only. Do not create, strengthen, reorder, or synthesize participant deltas.',
      `Submitted deltas:\n${JSON.stringify(state.round_submitted)}`,
    ].join('\n\n')
  }
  return [
    `Canonical identity: ${actor.canonical_label}`,
    'Summarize only the supplied transcript and verified deltas. Do not invent positions or deltas.',
    `Transcript:\n${state.transcript || '(empty)'}`,
    `Verified deltas:\n${JSON.stringify(state.delta_log)}`,
  ].join('\n\n')
}

function transitionFor(actor, kind, phase, round) {
  const from = actor.spawn_count === 0 ? 'unspawned' : 'idle'
  const to = kind === 'interrupt' ? 'terminal_pending' : 'awaiting_result'
  return {
    actor_from: from,
    actor_to: to,
    workflow_phase: phase,
    round,
  }
}

function makeAction(
  state,
  actor,
  kind,
  phase,
  round,
  prompt,
  outputSchema = turnSchema(actor.kind),
  repair = null,
) {
  const ordinal = state.next_ordinal++
  const currentTask = repair
    ? `Repair malformed output for ${repair.continuation_of}`
    : kind === 'spawn' ? `Initial ${phase} assignment` : `${phase} continuation`
  return {
    schema: ACTION_SCHEMA,
    run_id: state.run_id,
    action_id: `${state.run_id}:a${String(ordinal).padStart(4, '0')}`,
    ordinal,
    turn: ordinal,
    generation: actor.generation + 1,
    state_revision: state.state_revision,
    state_digest: null,
    transition: transitionFor(actor, kind, phase, round),
    kind,
    actor_id: actor.actor_id,
    logical_handle: actor.logical_handle,
    host_handle: kind === 'spawn' ? null : actor.host_handle,
    task_name: actor.task_name,
    canonical_label: actor.canonical_label,
    phase,
    round,
    barrier_id: `${state.run_id}:b${String(state.next_barrier).padStart(4, '0')}`,
    initial_summary: kind === 'spawn' ? summary(actor, phase, round, currentTask) : null,
    current_task_summary: summary(actor, phase, round, currentTask),
    card_title_projection: {
      supported: state.capability.card_title_projection,
      claimed: state.capability.card_title_projection,
    },
    repair_attempt: repair ? repair.attempt : 0,
    continuation_of: repair ? repair.continuation_of : null,
    prompt,
    output_schema: outputSchema,
    prompt_schema_digest: digest({ prompt, output_schema: outputSchema }),
  }
}

function sealState(state) {
  const bindRevision = action => {
    action.state_revision = state.state_revision
  }
  const bindDigest = action => {
    action.state_digest = state.state_digest
  }
  for (const action of state.pending?.actions || []) bindRevision(action)
  for (const entry of state.ledger) {
    if (entry.event === 'dispatch' && state.pending?.action_ids.includes(entry.action_id)) bindRevision(entry)
  }
  state.state_digest = persistentStateDigest(state)
  for (const action of state.pending?.actions || []) bindDigest(action)
  for (const entry of state.ledger) {
    if (entry.event === 'dispatch' && state.pending?.action_ids.includes(entry.action_id)) bindDigest(entry)
  }
  return state
}

function setPending(state, actions) {
  const barrierId = `${state.run_id}:b${String(state.next_barrier).padStart(4, '0')}`
  state.next_barrier += 1
  for (const action of actions) action.barrier_id = barrierId
  state.pending = {
    barrier_id: barrierId,
    generation: state.state_revision,
    action_ids: actions.map(action => action.action_id),
    actions,
  }
  state.ledger.push(...actions.map(action => ({ ...clone(action), event: 'dispatch' })))
}

function actionFor(state, actor, phase, round) {
  const kind = actor.spawn_count === 0 ? 'spawn' : 'followup'
  return makeAction(state, actor, kind, phase, round, promptFor(state, actor, phase, round))
}

function scheduleDiverge(state) {
  state.phase = 'Diverge'
  state.round = 0
  setPending(state, state.participants.map(actor => actionFor(state, actor, 'Diverge', 0)))
}

function scheduleDebateParticipant(state) {
  state.phase = 'Debate'
  setPending(state, [actionFor(state, state.participants[state.participant_cursor], 'Debate', state.round)])
}

function scheduleCritic(state) {
  setPending(state, [actionFor(state, state.critic, 'Debate', state.round)])
}

function scheduleConverge(state) {
  state.phase = 'Converge'
  state.round = null
  setPending(state, [actionFor(state, state.summarizer, 'Converge', null)])
}

function scheduleFinalCritic(state) {
  state.phase = 'Verdict'
  state.round = null
  const actor = state.critic
  const kind = actor.spawn_count === 0 ? 'spawn' : 'followup'
  const prompt = [
    `Canonical identity: ${actor.canonical_label}`,
    'Final verification only. Do not add, strengthen, reorder, or synthesize deltas.',
    `Verified deltas:\n${JSON.stringify(state.delta_log)}`,
    `Broker synthesis:\n${JSON.stringify(state.converge_synthesis)}`,
  ].join('\n\n')
  setPending(state, [makeAction(state, actor, kind, 'Verdict', null, prompt, verdictSchema())])
}

function validateState(state) {
  if (!state || state.schema !== PERSISTENT_BRAINSTORM_SCHEMA) {
    throw new PersistentBrokerError('state_invalid', 'canonical state schema is invalid')
  }
  if (state.state_digest !== persistentStateDigest(state)) {
    throw new PersistentBrokerError('state_tampered', 'canonical state digest mismatch')
  }
  if (!Number.isInteger(state.state_revision) || state.state_revision < 1) {
    throw new PersistentBrokerError('state_invalid', 'state revision is invalid')
  }
  if (new Set([...state.participants, state.critic, state.summarizer].map(actor => actor.task_name)).size
      !== state.participants.length + 2) {
    throw new PersistentBrokerError('state_invalid', 'actor task_name values must be unique')
  }
}

function validateReceiptFence(state, receipt) {
  if (!state.pending) throw new PersistentBrokerError('unexpected_result', 'no barrier is pending')
  if (!receipt || receipt.schema !== BARRIER_RESULT_SCHEMA) {
    throw new PersistentBrokerError('invalid_result', 'barrier result schema is invalid')
  }
  if (
    receipt.run_id !== state.run_id
    || receipt.state_revision !== state.state_revision
    || receipt.state_digest !== state.state_digest
    || receipt.barrier_id !== state.pending.barrier_id
  ) {
    throw new PersistentBrokerError('stale_result', 'run/state/barrier fence mismatch')
  }
  if (!Array.isArray(receipt.results) || receipt.results.length !== state.pending.action_ids.length) {
    throw new PersistentBrokerError('invalid_result', 'barrier result cardinality differs from dispatched actions')
  }
  receipt.results.forEach((result, index) => {
    if (result.action_id !== state.pending.action_ids[index]) {
      throw new PersistentBrokerError('result_reordered', 'caller must preserve canonical action order')
    }
    if (!['succeeded', 'failed', 'cancelled', 'timeout'].includes(result.status)) {
      throw new PersistentBrokerError('invalid_result', 'action result status is invalid')
    }
  })
}

function validateTelemetry(result) {
  if (result.tokens === null || result.tokens === undefined) {
    if (result.token_coverage !== undefined && result.token_coverage !== 'unavailable') {
      throw new PersistentBrokerError('invalid_telemetry', 'tokens:null requires unavailable coverage')
    }
    return { tokens: null, token_coverage: 'unavailable' }
  }
  if (!Number.isInteger(result.tokens) || result.tokens < 0 || result.token_coverage !== 'exact') {
    throw new PersistentBrokerError('invalid_telemetry', 'known tokens require nonnegative integer and exact coverage')
  }
  return { tokens: result.tokens, token_coverage: 'exact' }
}

function validateContextualOutput(state, action, output) {
  validateSchema(output, action.output_schema)
  if (action.actor_id === 'critic:critic' && action.phase === 'Debate') {
    const expected = state.round_submitted.map(item => item.id)
    const actual = output.verified.map(item => item.id)
    if (new Set(actual).size !== actual.length || canonicalJson(actual) !== canonicalJson(expected)) {
      throw new PersistentBrokerError(
        'output_schema_mismatch',
        'critic verdict IDs must be unique, complete, and in submitted order',
      )
    }
  }
}

function applyIdentity(state, action, result) {
  const actor = actorById(state, action.actor_id)
  if (!actor) throw new PersistentBrokerError('invalid_actor', 'action actor is not registered')
  if (action.kind === 'spawn') {
    if (actor.spawn_count !== 0) {
      throw new PersistentBrokerError('spawn_identity_invalid', 'actor may be spawned only once')
    }
    if (result.status === 'succeeded' && !result.host_handle) {
      throw new PersistentBrokerError('spawn_identity_invalid', 'successful spawn requires host_handle')
    }
    if (result.host_handle) {
      actor.host_handle = String(result.host_handle)
      actor.spawn_count = 1
    }
  } else if (actor.spawn_count !== 1 || result.host_handle !== actor.host_handle) {
    throw new PersistentBrokerError('followup_identity_invalid', 'action must target the original host_handle')
  }
  if (result.status === 'succeeded') actor.generation = action.generation
  return actor
}

function appendResult(state, action, result, telemetry, status = result.status) {
  state.ledger.push({
    event: 'result',
    action_id: action.action_id,
    ordinal: action.ordinal,
    turn: action.turn,
    generation: action.generation,
    state_revision: state.state_revision,
    state_digest: state.state_digest,
    transition: action.transition,
    actor_id: action.actor_id,
    logical_handle: action.logical_handle,
    host_handle: result.host_handle || null,
    status,
    tokens: telemetry.tokens,
    token_coverage: telemetry.token_coverage,
  })
}

function finishAbort(state) {
  state.status = 'aborted'
  state.phase = 'Aborted'
  state.pending = null
  state.unresolved_handles = []
  state.finished_at = new Date().toISOString()
}

function markRecoveryRequired(state, results) {
  state.status = 'recovery_required'
  state.phase = 'RecoveryRequired'
  state.pending = null
  state.unresolved_handles = results
    .filter(item => !(item.result.status === 'cancelled' || (
      item.result.status === 'succeeded' && item.result.output?.cancelled === true
    )))
    .map(item => item.action.host_handle)
    .filter(Boolean)
  state.finished_at = null
}

function scheduleCancel(state, failure) {
  state.status = 'cancelling'
  state.phase = 'Cancel'
  state.failure = failure
  state.fallback_allowed = false
  state.pending = null
  state.repair_context = null
  const live = [...state.participants, state.critic, state.summarizer]
    .filter(actor => actor.spawn_count === 1 && actor.host_handle)
  if (live.length === 0) {
    state.status = 'failed'
    state.phase = 'Failed'
    state.finished_at = new Date().toISOString()
    return
  }
  setPending(state, live.map(actor => makeAction(
    state,
    actor,
    'interrupt',
    'Cancel',
    null,
    `Cancel run ${state.run_id}; discard late output and do not respawn.`,
    cancelSchema(),
  )))
}

function processParticipantOutput(state, actor, output, stage) {
  state.transcript += `${state.transcript ? '\n\n' : ''}[${stage}] ${actor.crew}: ${output.utterance}`
  if (stage.startsWith('r')) {
    for (const delta of output.deltas) {
      state.round_submitted.push({
        id: state.round_submitted.length,
        round: state.round,
        by: actor.crew,
        ...delta,
      })
    }
  }
}

function scheduleRepair(state, pending, results, invalidIndexes) {
  const invalid = new Set(invalidIndexes)
  const accepted = results.map((result, index) => invalid.has(index) ? null : clone(result))
  state.repair_context = {
    phase: state.phase,
    round: state.round,
    original_actions: clone(pending.actions),
    accepted_results: accepted,
  }
  const actions = invalidIndexes.map(index => {
    const original = pending.actions[index]
    const actor = actorById(state, original.actor_id)
    if (original.repair_attempt >= 1 || !actor?.host_handle) {
      throw new PersistentBrokerError('repair_exhausted', 'same-handle repair bound is exhausted')
    }
    const prompt = [
      `Your previous output for ${original.action_id} failed the exact output schema.`,
      'Return a corrected structured result only. Do not change task, identity, phase, or round.',
      original.prompt,
    ].join('\n\n')
    return makeAction(
      state,
      actor,
      'followup',
      original.phase,
      original.round,
      prompt,
      original.output_schema,
      { attempt: 1, continuation_of: original.action_id },
    )
  })
  setPending(state, actions)
}

function finish(state, verdict) {
  const results = state.ledger.filter(entry => entry.event === 'result')
  const exact = results.length > 0 && results.every(entry => Number.isInteger(entry.tokens) && entry.tokens >= 0)
  state.status = 'completed'
  state.phase = 'Complete'
  state.pending = null
  state.finished_at = new Date().toISOString()
  state.output = {
    run_id: state.run_id,
    ritual: 'brainstorm',
    participants: state.participants.map(actor => actor.crew),
    synthesis: state.converge_synthesis.synthesis,
    minority: state.converge_synthesis.minority,
    proposals: state.converge_synthesis.proposals,
    delta_log: [...state.delta_log, ...state.dry_log],
    verdict,
    cost: {
      tokens: exact ? results.reduce((sum, entry) => sum + entry.tokens, 0) : null,
      token_coverage: exact ? 'exact' : 'unavailable',
      rounds: state.rounds_run,
    },
  }
}

function continueWorkflow(state, pending, results) {
  if (state.phase === 'Diverge') {
    state.participants.forEach((actor, index) => processParticipantOutput(state, actor, results[index].output, 'diverge'))
    state.round = 1
    state.rounds_run = 1
    state.participant_cursor = 0
    state.round_submitted = []
    scheduleDebateParticipant(state)
    return
  }
  if (state.phase === 'Debate' && pending.actions[0].actor_id.startsWith('participant:')) {
    processParticipantOutput(
      state,
      state.participants[state.participant_cursor],
      results[0].output,
      `r${state.round}`,
    )
    state.participant_cursor += 1
    if (state.participant_cursor < state.participants.length) scheduleDebateParticipant(state)
    else scheduleCritic(state)
    return
  }
  if (state.phase === 'Debate') {
    const verified = new Map(results[0].output.verified.map(item => [item.id, item]))
    let valid = 0
    for (const submission of state.round_submitted) {
      if (verified.get(submission.id).valid === true) {
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
    return
  }
  if (state.phase === 'Converge') {
    state.converge_synthesis = results[0].output
    scheduleFinalCritic(state)
    return
  }
  if (state.phase === 'Verdict') {
    finish(state, results[0].output)
    return
  }
  throw new PersistentBrokerError('invalid_state', `unsupported phase ${state.phase}`)
}

function mutatingApply(state, receipt) {
  const pending = state.pending
  if (state.status === 'cancelling') {
    const pairs = pending.actions.map((action, index) => ({ action, result: receipt.results[index] }))
    let incomplete = false
    for (const { action, result } of pairs) {
      let telemetry
      try {
        telemetry = validateTelemetry(result)
        applyIdentity(state, action, result)
        if (result.status === 'succeeded') validateContextualOutput(state, action, result.output)
        if (!(result.status === 'cancelled' || (
          result.status === 'succeeded' && result.output.cancelled === true
        ))) incomplete = true
      } catch {
        telemetry = { tokens: null, token_coverage: 'unavailable' }
        incomplete = true
      }
      appendResult(state, action, result, telemetry, incomplete ? 'cancel_unresolved' : result.status)
    }
    if (incomplete) markRecoveryRequired(state, pairs)
    else finishAbort(state)
    return
  }

  const repairContext = state.repair_context
  const telemetry = []
  const invalidOutput = []
  const failures = []
  const identityFailures = []
  for (let index = 0; index < pending.actions.length; index += 1) {
    const action = pending.actions[index]
    const result = receipt.results[index]
    try {
      telemetry[index] = validateTelemetry(result)
    } catch (error) {
      identityFailures.push({ index, error })
      telemetry[index] = { tokens: null, token_coverage: 'unavailable' }
    }
    try {
      applyIdentity(state, action, result)
    } catch (error) {
      identityFailures.push({ index, error })
    }
    if (result.status !== 'succeeded') {
      failures.push(index)
    } else if (!identityFailures.some(item => item.index === index)) {
      try {
        validateContextualOutput(state, action, result.output)
      } catch (error) {
        invalidOutput.push({ index, error })
      }
    }
  }
  pending.actions.forEach((action, index) => appendResult(
    state,
    action,
    receipt.results[index],
    telemetry[index],
    invalidOutput.some(item => item.index === index) ? 'invalid_output' : receipt.results[index].status,
  ))

  if (identityFailures.length || failures.length) {
    scheduleCancel(state, {
      code: identityFailures[0]?.error.code || 'native_action_failed',
      action_ids: [...new Set([...identityFailures.map(item => pending.action_ids[item.index]), ...failures.map(index => pending.action_ids[index])])],
    })
    return
  }
  if (invalidOutput.length) {
    try {
      scheduleRepair(state, pending, receipt.results, invalidOutput.map(item => item.index))
    } catch (error) {
      scheduleCancel(state, {
        code: error.code || 'repair_exhausted',
        action_ids: invalidOutput.map(item => pending.action_ids[item.index]),
      })
    }
    return
  }

  state.pending = null
  let effectivePending = pending
  let effectiveResults = receipt.results
  if (repairContext) {
    const repaired = new Map(pending.actions.map((action, index) => [action.continuation_of, receipt.results[index]]))
    effectivePending = { actions: repairContext.original_actions }
    effectiveResults = repairContext.accepted_results.map((result, index) => (
      result || repaired.get(repairContext.original_actions[index].action_id)
    ))
    state.phase = repairContext.phase
    state.round = repairContext.round
    state.repair_context = null
  }
  continueWorkflow(state, effectivePending, effectiveResults)
}

export function createPersistentBrainstorm(input) {
  if (input.admission !== 'canary') {
    throw new PersistentBrokerError(
      'canary_admission_required',
      'persistent brainstorm is deterministic-harness canary only, not production default',
    )
  }
  const capability = validateCapability(input.capability)
  const workflowName = String(input.workflow_name || '').trim()
  const runId = String(input.run_id || '').trim()
  if (!workflowName || !runId) throw new PersistentBrokerError('invalid_config', 'run_id and workflow_name are required')
  if (!Array.isArray(input.personas) || input.personas.length < 2) {
    throw new PersistentBrokerError('invalid_config', 'brainstorm needs at least two personas')
  }
  const participants = input.personas.map(value => makeActor(value, runId, workflowName, 'participant'))
  if (new Set(participants.map(actor => actor.actor_id)).size !== participants.length) {
    throw new PersistentBrokerError('invalid_actor', 'crew names must be unique')
  }
  const critic = makeActor({ crew: 'critic', role: '독립 검증' }, runId, workflowName, 'critic')
  const summarizer = makeActor({ crew: 'summarizer', role: '중립 수렴' }, runId, workflowName, 'summarizer')
  const taskNames = [...participants, critic, summarizer].map(actor => actor.task_name)
  if (new Set(taskNames).size !== taskNames.length) {
    throw new PersistentBrokerError('task_name_collision', 'task_name must be unique per run')
  }
  const state = {
    schema: PERSISTENT_BRAINSTORM_SCHEMA,
    run_id: runId,
    workflow_name: workflowName,
    agenda: String(input.agenda || '(no agenda provided)'),
    admission: 'canary',
    capability,
    config: {
      max_rounds: positiveInteger(input.maxRounds, 4, 'maxRounds'),
      dry_stop: positiveInteger(input.dryStop, 2, 'dryStop'),
    },
    participants,
    critic,
    summarizer,
    state_revision: 1,
    state_digest: null,
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
    repair_context: null,
    native_started: true,
    fallback_allowed: false,
    failure: null,
    unresolved_handles: [],
    output: null,
    converge_synthesis: null,
    finished_at: null,
  }
  scheduleDiverge(state)
  return sealState(state)
}

export function applyPersistentBarrier(state, receipt) {
  validateState(state)
  if (!['running', 'cancelling'].includes(state.status)) {
    throw new PersistentBrokerError('late_result', `run is already ${state.status}`)
  }
  validateReceiptFence(state, receipt)
  const next = clone(state)
  mutatingApply(next, clone(receipt))
  next.state_revision += 1
  return sealState(next)
}

export function persistentBrainstormEnvelope(state) {
  validateState(state)
  return {
    schema: 'studio-persistent-brainstorm-envelope/v2',
    run_id: state.run_id,
    state_revision: state.state_revision,
    state_digest: state.state_digest,
    status: state.status,
    phase: state.phase,
    round: state.round,
    max_rounds: state.config.max_rounds,
    dry_stop: state.config.dry_stop,
    admission: state.admission,
    evidence_status: 'deterministic-harness-only',
    live_host_canary_approved: false,
    native_started: state.native_started,
    fallback_allowed: state.fallback_allowed,
    capability: clone(state.capability),
    pending: clone(state.pending),
    actors: [...state.participants, state.critic, state.summarizer].map(actor => ({
      actor_id: actor.actor_id,
      logical_handle: actor.logical_handle,
      host_handle: actor.host_handle,
      task_name: actor.task_name,
      canonical_label: actor.canonical_label,
      spawn_count: actor.spawn_count,
      generation: actor.generation,
      initial_summary: summary(actor, state.phase, state.round, 'Initial/current task identity'),
      current_task_summary: summary(actor, state.phase, state.round, 'Await canonical broker action'),
    })),
    ledger: clone(state.ledger),
    output: clone(state.output),
    failure: clone(state.failure),
    unresolved_handles: clone(state.unresolved_handles),
  }
}
