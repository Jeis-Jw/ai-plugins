import assert from 'node:assert/strict'
import test from 'node:test'
import {
  PersistentBrokerError,
  applyPersistentBarrier,
  createPersistentBrainstorm,
  persistentBrainstormEnvelope,
} from '../broker/persistent_brainstorm_broker.mjs'
import { executePersistentRequest } from '../scripts/persistent_brainstorm_driver.mjs'

function capability(overrides = {}) {
  return {
    schema: 'studio-native-persistent-capability/v1',
    verified: true,
    spawn: true,
    followup: true,
    wait_barrier: true,
    interrupt_cancel: true,
    structured_result: true,
    card_title_projection: false,
    ...overrides,
  }
}

function create(overrides = {}) {
  return createPersistentBrainstorm({
    run_id: 'RUN-persistent-canary',
    workflow_name: '비용 절감 브레인스토밍',
    agenda: '품질 하락을 제한하면서 반복 비용을 줄인다',
    admission: 'canary',
    maxRounds: 2,
    dryStop: 1,
    capability: capability(),
    personas: [
      { crew: 'planner-a', role: '비용 관점', prior: '물리 실행을 줄인다' },
      { crew: 'planner-b', role: '품질 관점', prior: 'hard floor를 지킨다' },
    ],
    ...overrides,
  })
}

function succeed(state, outputs, handles = {}) {
  const actions = state.pending.actions
  return {
    schema: 'studio-crew-barrier-result/v1',
    barrier_id: state.pending.barrier_id,
    results: actions.map((action, index) => ({
      action_id: action.action_id,
      status: 'succeeded',
      host_handle: action.kind === 'spawn'
        ? (handles[action.actor_id] || `host-${action.actor_id}`)
        : action.host_handle,
      output: outputs[index],
      tokens: null,
    })),
  }
}

test('canonical broker spawns each actor once and follows up on the same immutable handle', () => {
  const state = create()
  assert.equal(state.pending.actions.length, 2)
  assert.ok(state.pending.actions.every(action => action.kind === 'spawn'))
  assert.deepEqual(state.pending.actions.map(action => action.ordinal), [1, 2])
  assert.equal(state.config.max_rounds, 2)
  assert.equal(state.config.dry_stop, 1)
  assert.equal(state.fallback_allowed, false)

  for (const action of state.pending.actions) {
    const crew = action.actor_id.split(':')[1]
    const role = crew === 'planner-a' ? '비용 관점' : '품질 관점'
    assert.equal(action.canonical_label, `[studio:${crew}] 비용 절감 브레인스토밍 - ${role}`)
    assert.equal(action.initial_summary.canonical_label, action.canonical_label)
    assert.equal(action.current_task_summary.canonical_label, action.canonical_label)
    assert.match(action.task_name, /^[a-z0-9-]+$/)
    assert.equal(action.card_title_projection.supported, false)
    assert.equal(action.card_title_projection.claimed, false)
  }

  applyPersistentBarrier(state, succeed(state, [
    { utterance: 'independent-a', deltas: [] },
    { utterance: 'independent-b', deltas: [] },
  ]))
  const firstDebate = state.pending.actions[0]
  assert.equal(firstDebate.kind, 'followup')
  assert.equal(firstDebate.host_handle, 'host-participant:planner-a')
  assert.equal(firstDebate.round, 1)

  applyPersistentBarrier(state, succeed(state, [{
    utterance: 'delta-a',
    deltas: [{ changed_what: 'one', anchor: 'risk', evidence: 'e1' }],
  }]))
  const secondDebate = state.pending.actions[0]
  assert.equal(secondDebate.kind, 'followup')
  assert.equal(secondDebate.host_handle, 'host-participant:planner-b')

  applyPersistentBarrier(state, succeed(state, [{ utterance: 'dry-b', deltas: [] }]))
  const critic = state.pending.actions[0]
  assert.equal(critic.actor_id, 'critic:critic')
  assert.equal(critic.kind, 'spawn')
  assert.notEqual(critic.logical_handle, firstDebate.logical_handle)

  applyPersistentBarrier(state, succeed(state, [{ verified: [{ id: 0, valid: false, reason: 'dry' }] }]))
  const summarizer = state.pending.actions[0]
  assert.equal(summarizer.actor_id, 'summarizer:summarizer')
  assert.equal(summarizer.kind, 'spawn')
  assert.notEqual(summarizer.logical_handle, critic.logical_handle)

  applyPersistentBarrier(state, succeed(state, [{
    synthesis: 'bounded result',
    minority: 'none',
    proposals: [],
  }]))
  const finalCritic = state.pending.actions[0]
  assert.equal(finalCritic.actor_id, 'critic:critic')
  assert.equal(finalCritic.kind, 'followup')
  assert.equal(finalCritic.host_handle, 'host-critic:critic')
  applyPersistentBarrier(state, succeed(state, [{
    alive: false,
    reason: 'no verified delta',
  }]))
  const envelope = persistentBrainstormEnvelope(state)
  assert.equal(envelope.status, 'completed')
  assert.equal(envelope.output.cost.tokens, null)
  assert.equal(envelope.output.cost.token_coverage, 'unavailable')
  assert.ok(envelope.output.persistent_crew.actors.every(value => value.spawn_count === 1))
  assert.equal(envelope.output.persistent_crew.fallback_allowed, false)

  const participantResults = envelope.ledger.filter(
    item => item.event === 'result' && item.actor_id === 'participant:planner-a',
  )
  assert.equal(participantResults.length, 2)
  assert.ok(participantResults.every(item => item.host_handle === 'host-participant:planner-a'))
})

test('capability and result ordering fail closed without claiming UI card-title support', () => {
  assert.throws(
    () => create({ admission: 'default' }),
    error => error instanceof PersistentBrokerError && error.code === 'canary_admission_required',
  )
  assert.throws(
    () => create({ capability: capability({ followup: false }) }),
    error => error instanceof PersistentBrokerError && error.code === 'native_capability_required',
  )
  const state = create()
  const receipt = succeed(state, [
    { utterance: 'a', deltas: [] },
    { utterance: 'b', deltas: [] },
  ])
  receipt.results.reverse()
  assert.throws(
    () => applyPersistentBarrier(state, receipt),
    error => error instanceof PersistentBrokerError && error.code === 'result_reordered',
  )
  assert.equal(state.pending.actions[0].card_title_projection.claimed, false)
})

test('native failure aborts without replacement spawn or CLI fallback', () => {
  const state = create()
  const first = state.pending.actions[0]
  const second = state.pending.actions[1]
  applyPersistentBarrier(state, {
    schema: 'studio-crew-barrier-result/v1',
    barrier_id: state.pending.barrier_id,
    results: [
      {
        action_id: first.action_id,
        status: 'failed',
        host_handle: 'host-a',
        output: null,
        error: 'host failure',
        tokens: null,
      },
      {
        action_id: second.action_id,
        status: 'cancelled',
        host_handle: 'host-b',
        output: null,
        tokens: null,
      },
    ],
  })
  assert.equal(state.status, 'cancelling')
  assert.ok(state.pending.actions.every(action => action.kind === 'interrupt'))
  assert.deepEqual(
    state.pending.actions.map(action => action.host_handle),
    ['host-a', 'host-b'],
  )
  applyPersistentBarrier(state, {
    schema: 'studio-crew-barrier-result/v1',
    barrier_id: state.pending.barrier_id,
    results: state.pending.actions.map(action => ({
      action_id: action.action_id,
      status: 'cancelled',
      host_handle: action.host_handle,
      output: { cancelled: true },
      tokens: null,
    })),
  })
  assert.equal(state.status, 'aborted')
  assert.equal(state.fallback_allowed, false)
  assert.equal(state.participants[0].spawn_count, 1)
  assert.equal(state.participants[1].spawn_count, 1)
  assert.equal(state.ledger.filter(item => item.event === 'dispatch' && item.kind === 'spawn').length, 2)
  assert.throws(
    () => applyPersistentBarrier(state, {
      schema: 'studio-crew-barrier-result/v1',
      barrier_id: 'late',
      results: [],
    }),
    error => error instanceof PersistentBrokerError && error.code === 'late_result',
  )
})

test('driver projects broker state without becoming a second orchestration authority', () => {
  const result = executePersistentRequest({
    op: 'create',
    input: {
      run_id: 'RUN-driver-canary',
      workflow_name: 'driver canary',
      agenda: 'relay only',
      admission: 'canary',
      maxRounds: 1,
      dryStop: 1,
      capability: capability(),
      personas: [
        { crew: 'a', role: 'first' },
        { crew: 'b', role: 'second' },
      ],
    },
  })
  assert.equal(result.schema, 'studio-persistent-brainstorm-driver/v1')
  assert.equal(result.ok, true)
  assert.equal(result.envelope.pending.barrier_id, result.state.pending.barrier_id)
  assert.deepEqual(
    result.envelope.pending.action_ids,
    result.state.pending.actions.map(action => action.action_id),
  )
})
