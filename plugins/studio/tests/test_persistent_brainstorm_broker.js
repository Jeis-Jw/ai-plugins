import assert from 'node:assert/strict'
import {
  lstat, mkdtemp, readFile, readdir, rm, symlink, writeFile,
} from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import {
  PersistentBrokerError,
  TASK_NAME_MAX,
  applyPersistentBarrier,
  collaborationTaskName,
  createPersistentBrainstorm,
  persistentBrainstormEnvelope,
} from '../broker/persistent_brainstorm_broker.mjs'
import { PersistentBrainstormStore } from '../broker/persistent_brainstorm_store.mjs'
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

function input(overrides = {}) {
  return {
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
  }
}

function receipt(state, outputs, options = {}) {
  return {
    schema: 'studio-crew-barrier-result/v2',
    run_id: state.run_id,
    state_revision: state.state_revision,
    state_digest: state.state_digest,
    barrier_id: state.pending.barrier_id,
    results: state.pending.actions.map((action, index) => ({
      action_id: action.action_id,
      status: options.statuses?.[index] || 'succeeded',
      host_handle: options.handles && Object.hasOwn(options.handles, index)
        ? options.handles[index]
        : (action.kind === 'spawn' ? `host-${action.actor_id}` : action.host_handle),
      output: outputs[index],
      tokens: options.tokens?.[index] ?? null,
      token_coverage: options.tokens?.[index] === undefined ? 'unavailable' : 'exact',
      error: options.errors?.[index] || null,
    })),
  }
}

function apply(state, outputs, options = {}) {
  return applyPersistentBarrier(state, receipt(state, outputs, options))
}

test('task_name matches the real host contract, preserves suffix, and resists slug collisions', () => {
  const common = {
    runId: 'RUN-long',
    namespace: 'participant',
    workflowName: 'w'.repeat(300),
    role: 'r'.repeat(300),
  }
  const names = [
    collaborationTaskName({ ...common, crew: 'foo bar' }),
    collaborationTaskName({ ...common, crew: 'foo-bar' }),
    collaborationTaskName({ ...common, crew: 'fóó bar' }),
    collaborationTaskName({ ...common, crew: '한글 크루' }),
  ]
  assert.equal(new Set(names).size, names.length)
  for (const name of names) {
    assert.match(name, /^[a-z0-9_]+$/)
    assert.ok(name.length <= TASK_NAME_MAX)
    assert.match(name, /_[0-9a-f]{12}$/)
  }
  const state = createPersistentBrainstorm(input())
  assert.equal(
    new Set([...state.participants, state.critic, state.summarizer].map(actor => actor.task_name)).size,
    state.participants.length + 2,
  )
})

test('canonical actions bind immutable turn, generation, state, transition, label and handle', () => {
  let state = createPersistentBrainstorm(input())
  const original = structuredClone(state)
  for (const action of state.pending.actions) {
    assert.match(action.task_name, /^[a-z0-9_]+$/)
    assert.equal(action.state_revision, state.state_revision)
    assert.equal(action.state_digest, state.state_digest)
    assert.equal(action.turn, action.ordinal)
    assert.equal(action.generation, 1)
    assert.deepEqual(action.transition.actor_from, 'unspawned')
    assert.equal(action.initial_summary.canonical_label, action.canonical_label)
    assert.equal(action.current_task_summary.canonical_label, action.canonical_label)
    assert.equal(action.card_title_projection.claimed, false)
  }
  state = apply(state, [
    { utterance: 'independent-a', deltas: [] },
    { utterance: 'independent-b', deltas: [] },
  ])
  assert.deepEqual(original.participants.map(actor => actor.spawn_count), [0, 0], 'input state was mutated')
  const followup = state.pending.actions[0]
  assert.equal(followup.kind, 'followup')
  assert.equal(followup.host_handle, 'host-participant:planner-a')
  assert.equal(followup.generation, 2)
  assert.equal(followup.transition.actor_from, 'idle')
  assert.equal(followup.state_revision, state.state_revision)
  assert.equal(state.fallback_allowed, false)
})

test('exact output validation repairs once on the original handle and then cancels', () => {
  let state = createPersistentBrainstorm(input())
  state = apply(state, [
    {},
    { utterance: 'valid-b', deltas: [] },
  ])
  assert.equal(state.pending.actions.length, 1)
  const repair = state.pending.actions[0]
  assert.equal(repair.kind, 'followup')
  assert.equal(repair.repair_attempt, 1)
  assert.equal(repair.host_handle, 'host-participant:planner-a')
  assert.match(repair.continuation_of, /:a0001$/)

  state = apply(state, [{ utterance: '', deltas: [], extra: true }])
  assert.equal(state.status, 'cancelling')
  assert.ok(state.pending.actions.every(action => action.kind === 'interrupt'))
  assert.ok(state.ledger.filter(entry => entry.event === 'dispatch' && entry.kind === 'spawn').length === 2)
  assert.ok(!state.ledger.some(entry => entry.event === 'dispatch' && entry.kind === 'spawn' && entry.repair_attempt > 0))

  state = apply(state, state.pending.actions.map(() => ({ cancelled: true })), {
    statuses: state.pending.actions.map(() => 'cancelled'),
  })
  assert.equal(state.status, 'aborted')
})

test('critic IDs and participant anchors are exact-schema checked', () => {
  let state = createPersistentBrainstorm(input())
  state = apply(state, [
    { utterance: 'a', deltas: [] },
    { utterance: 'b', deltas: [] },
  ])
  state = apply(state, [{
    utterance: 'delta-a',
    deltas: [{ changed_what: 'one', anchor: 'risk', evidence: 'e1' }],
  }])
  state = apply(state, [{ utterance: 'b', deltas: [] }])
  assert.equal(state.pending.actions[0].actor_id, 'critic:critic')
  state = apply(state, [{ verified: [] }])
  assert.equal(state.pending.actions[0].repair_attempt, 1)
  assert.equal(state.pending.actions[0].host_handle, 'host-critic:critic')

  let duplicateState = createPersistentBrainstorm(input({ run_id: 'RUN-critic-duplicate' }))
  duplicateState = apply(duplicateState, [
    { utterance: 'a', deltas: [] },
    { utterance: 'b', deltas: [] },
  ])
  duplicateState = apply(duplicateState, [{
    utterance: 'delta',
    deltas: [{ changed_what: 'one', anchor: 'risk', evidence: 'e1' }],
  }])
  duplicateState = apply(duplicateState, [{ utterance: 'b', deltas: [] }])
  duplicateState = apply(duplicateState, [{
    verified: [
      { id: 0, valid: true, reason: 'first' },
      { id: 0, valid: true, reason: 'duplicate' },
    ],
  }])
  assert.equal(duplicateState.pending.actions[0].repair_attempt, 1)

  let anchorState = createPersistentBrainstorm(input({ run_id: 'RUN-anchor' }))
  anchorState = apply(anchorState, [
    {
      utterance: 'bad anchor',
      deltas: [{ changed_what: 'x', anchor: 'vibe', evidence: 'e' }],
    },
    { utterance: 'valid', deltas: [] },
  ])
  assert.equal(anchorState.pending.actions[0].repair_attempt, 1)
})

test('summarizer and final verdict malformed output use one bounded same-handle repair', () => {
  let state = createPersistentBrainstorm(input({ run_id: 'RUN-terminal-repair' }))
  state = apply(state, [
    { utterance: 'a', deltas: [] },
    { utterance: 'b', deltas: [] },
  ])
  state = apply(state, [{ utterance: 'a dry', deltas: [] }])
  state = apply(state, [{ utterance: 'b dry', deltas: [] }])
  state = apply(state, [{ verified: [] }])
  assert.equal(state.phase, 'Converge')
  state = apply(state, [{}])
  assert.equal(state.pending.actions[0].repair_attempt, 1)
  assert.equal(state.pending.actions[0].host_handle, 'host-summarizer:summarizer')
  state = apply(state, [{
    synthesis: 'bounded',
    minority: 'none',
    proposals: [],
  }])
  assert.equal(state.phase, 'Verdict')
  state = apply(state, [{ alive: false }])
  assert.equal(state.pending.actions[0].repair_attempt, 1)
  assert.equal(state.pending.actions[0].host_handle, 'host-critic:critic')
})

test('barrier transition is atomic and partial host outcomes enter truthful cancellation', () => {
  const original = createPersistentBrainstorm(input())
  const bad = receipt(original, [
    { utterance: 'first', deltas: [] },
    { utterance: 'second', deltas: [] },
  ], { handles: ['host-a', null] })
  const next = applyPersistentBarrier(original, bad)
  assert.deepEqual(original.participants.map(actor => actor.spawn_count), [0, 0])
  assert.equal(original.status, 'running')
  assert.equal(next.status, 'cancelling')
  assert.deepEqual(next.pending.actions.map(action => action.host_handle), ['host-a'])

  const cancelFailed = receipt(next, [{ cancelled: false }], {
    statuses: ['failed'],
    handles: ['host-a'],
  })
  const recovery = applyPersistentBarrier(next, cancelFailed)
  assert.equal(recovery.status, 'recovery_required')
  assert.deepEqual(recovery.unresolved_handles, ['host-a'])
  assert.throws(
    () => applyPersistentBarrier(recovery, cancelFailed),
    error => error instanceof PersistentBrokerError && error.code === 'late_result',
  )
})

test('invalid telemetry fails closed while exact integers remain exact', () => {
  const state = createPersistentBrainstorm(input())
  const invalid = receipt(state, [
    { utterance: 'a', deltas: [] },
    { utterance: 'b', deltas: [] },
  ])
  invalid.results[0].tokens = '10'
  invalid.results[0].token_coverage = 'exact'
  const cancelling = applyPersistentBarrier(state, invalid)
  assert.equal(cancelling.status, 'cancelling')
  const result = cancelling.ledger.find(entry => entry.action_id === invalid.results[0].action_id && entry.event === 'result')
  assert.equal(result.tokens, null)
  assert.equal(result.token_coverage, 'unavailable')

  const measured = createPersistentBrainstorm(input({ run_id: 'RUN-measured' }))
  const advanced = apply(measured, [
    { utterance: 'a', deltas: [] },
    { utterance: 'b', deltas: [] },
  ], { tokens: [3, 5] })
  const entries = advanced.ledger.filter(entry => entry.event === 'result')
  assert.deepEqual(entries.map(entry => [entry.tokens, entry.token_coverage]), [[3, 'exact'], [5, 'exact']])
})

test('timeout enters cancellation without replacement spawn', () => {
  const state = createPersistentBrainstorm(input({ run_id: 'RUN-timeout' }))
  const timedOut = apply(state, [
    null,
    { utterance: 'b', deltas: [] },
  ], {
    statuses: ['timeout', 'succeeded'],
    errors: ['deadline', null],
  })
  assert.equal(timedOut.status, 'cancelling')
  assert.ok(timedOut.pending.actions.every(action => action.kind === 'interrupt'))
  assert.equal(
    timedOut.ledger.filter(entry => entry.event === 'dispatch' && entry.kind === 'spawn').length,
    2,
  )
})

test('runtime-owned store accepts no caller state, rejects duplicate/stale replay and detects tamper', async () => {
  const root = await mkdtemp(join(tmpdir(), 'studio-persistent-store-'))
  try {
    const store = new PersistentBrainstormStore(root)
    const created = await executePersistentRequest({ op: 'create', input: input({ run_id: 'RUN-store' }) }, store)
    assert.equal(created.schema, 'studio-persistent-brainstorm-driver/v2')
    assert.equal(Object.hasOwn(created, 'state'), false)
    assert.equal(created.envelope.evidence_status, 'deterministic-harness-only')
    await assert.rejects(
      executePersistentRequest({ op: 'create', input: input({ run_id: 'RUN-store' }) }, store),
      error => error instanceof PersistentBrokerError && error.code === 'duplicate_run',
    )
    await assert.rejects(
      executePersistentRequest({
        op: 'apply',
        run_id: 'RUN-store',
        expected_state_revision: created.state_ref.state_revision,
        expected_state_digest: created.state_ref.state_digest,
        receipt: receipt(created.envelope, [
          { utterance: 'a', deltas: [] },
          { utterance: 'b', deltas: [] },
        ]),
        state: { config: { max_rounds: 999 } },
      }, store),
      error => error instanceof PersistentBrokerError && error.code === 'invalid_request',
    )
    const request = {
      op: 'apply',
      run_id: 'RUN-store',
      expected_state_revision: created.state_ref.state_revision,
      expected_state_digest: created.state_ref.state_digest,
      receipt: receipt(created.envelope, [
        { utterance: 'a', deltas: [] },
        { utterance: 'b', deltas: [] },
      ]),
    }
    const advanced = await executePersistentRequest(request, store)
    assert.equal(advanced.state_ref.state_revision, created.state_ref.state_revision + 1)
    await assert.rejects(
      executePersistentRequest(request, store),
      error => error instanceof PersistentBrokerError
        && ['stale_state', 'stale_result'].includes(error.code),
    )

    const files = (await readdir(root)).filter(name => name.endsWith('.json'))
    assert.equal(files.length, 1)
    const path = join(root, files[0])
    const stored = JSON.parse(await readFile(path, 'utf8'))
    stored.config.max_rounds = 999
    await writeFile(path, JSON.stringify(stored), 'utf8')
    await assert.rejects(
      store.read('RUN-store'),
      error => error instanceof PersistentBrokerError && error.code === 'state_tampered',
    )
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('store hashes traversal-like run IDs and rejects symlink roots/state plus concurrent stale apply', async () => {
  const scratch = await mkdtemp(join(tmpdir(), 'studio-persistent-store-adversarial-'))
  try {
    const root = join(scratch, 'state')
    const store = new PersistentBrainstormStore(root)
    const traversal = await store.create(input({ run_id: '../../outside/../RUN-traversal' }))
    assert.equal(traversal.state_ref.run_id, '../../outside/../RUN-traversal')
    const entries = await readdir(root)
    assert.ok(entries.every(name => /^[0-9a-f]{64}\.(json|lock)$/.test(name)))
    assert.equal(await readdir(scratch).then(items => items.sort()).then(items => items.join(',')), 'state')

    const concurrent = await store.create(input({ run_id: 'RUN-concurrent' }))
    const request = {
      op: 'apply',
      run_id: 'RUN-concurrent',
      expected_state_revision: concurrent.state_ref.state_revision,
      expected_state_digest: concurrent.state_ref.state_digest,
      receipt: receipt(concurrent.envelope, [
        { utterance: 'a', deltas: [] },
        { utterance: 'b', deltas: [] },
      ]),
    }
    const settled = await Promise.allSettled([
      executePersistentRequest(request, store),
      executePersistentRequest(request, store),
    ])
    assert.equal(settled.filter(item => item.status === 'fulfilled').length, 1)
    assert.equal(settled.filter(item => item.status === 'rejected').length, 1)
    assert.ok(['state_busy', 'stale_state'].includes(settled.find(item => item.status === 'rejected').reason.code))

    const external = join(scratch, 'external.json')
    await writeFile(external, '{}', 'utf8')
    const statePath = store.paths('../../outside/../RUN-traversal').state
    await rm(statePath)
    await symlink(external, statePath)
    await assert.rejects(
      store.read('../../outside/../RUN-traversal'),
      error => error instanceof PersistentBrokerError && error.code === 'state_store_invalid',
    )

    const realRoot = join(scratch, 'real-root')
    const linkedRoot = join(scratch, 'linked-root')
    await new PersistentBrainstormStore(realRoot).initialize()
    await symlink(realRoot, linkedRoot)
    await assert.rejects(
      new PersistentBrainstormStore(linkedRoot).initialize(),
      error => error instanceof PersistentBrokerError && error.code === 'state_root_invalid',
    )
  } finally {
    await rm(scratch, { recursive: true, force: true })
  }
})

test('lock initialization failure removes only the newly opened orphan lock', async () => {
  const root = await mkdtemp(join(tmpdir(), 'studio-persistent-lock-cleanup-'))
  try {
    const normal = new PersistentBrainstormStore(root)
    await normal.create(input({ run_id: 'RUN-lock-cleanup' }))
    class FailingLockStore extends PersistentBrainstormStore {
      async initializeLock(handle) {
        await handle.writeFile('', 'utf8')
        throw new PersistentBrokerError('injected_lock_write_failure', 'simulated write/sync failure')
      }
    }
    const failing = new FailingLockStore(root)
    const lockPath = failing.paths('RUN-lock-cleanup').lock
    await assert.rejects(
      failing.acquire('RUN-lock-cleanup'),
      error => error instanceof PersistentBrokerError && error.code === 'injected_lock_write_failure',
    )
    assert.equal(await lstat(lockPath).catch(() => null), null)

    const acquired = await normal.acquire('RUN-lock-cleanup')
    assert.ok((await lstat(acquired.path)).isFile())
    await acquired.handle.close()
    await rm(acquired.path)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('admission, capability, ordering, stale and malformed terminal outputs fail closed', () => {
  assert.throws(
    () => createPersistentBrainstorm(input({ admission: 'default' })),
    error => error instanceof PersistentBrokerError && error.code === 'canary_admission_required',
  )
  assert.throws(
    () => createPersistentBrainstorm(input({ capability: capability({ followup: false }) })),
    error => error instanceof PersistentBrokerError && error.code === 'native_capability_required',
  )
  const state = createPersistentBrainstorm(input())
  const reordered = receipt(state, [
    { utterance: 'a', deltas: [] },
    { utterance: 'b', deltas: [] },
  ])
  reordered.results.reverse()
  assert.throws(
    () => applyPersistentBarrier(state, reordered),
    error => error instanceof PersistentBrokerError && error.code === 'result_reordered',
  )
  const stale = receipt(state, [
    { utterance: 'a', deltas: [] },
    { utterance: 'b', deltas: [] },
  ])
  stale.state_digest = 'sha256:' + '0'.repeat(64)
  assert.throws(
    () => applyPersistentBarrier(state, stale),
    error => error instanceof PersistentBrokerError && error.code === 'stale_result',
  )
  const envelope = persistentBrainstormEnvelope(state)
  assert.equal(envelope.live_host_canary_approved, false)
  assert.equal(envelope.evidence_status, 'deterministic-harness-only')
})
