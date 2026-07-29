import assert from 'node:assert/strict'
import test from 'node:test'
import { NativeAdapterError } from '../scripts/persistent_native_app_server.mjs'
import {
  nativeResult,
  validateNativeTerminalReceipt,
} from '../broker/persistent_brainstorm_store.mjs'
import {
  executeProductionBrainstorm,
  isCompletedControllerOutput,
  isProductionBrainstormResult,
} from '../scripts/persistent_brainstorm_controller.mjs'
import {
  createPersistentBrainstormControllerForTest,
} from './fixtures/persistent_brainstorm_controller_test_adapter.mjs'

const REQUEST = Object.freeze({
  run_id: 'RUN-controller',
  workflow_name: 'controller test',
  agenda: 'prove routing',
  personas: [
    { crew: 'a', role: 'one' },
    { crew: 'b', role: 'two' },
  ],
})
const CONFIG = Object.freeze({
  stateRoot: '/tmp/studio-controller-state',
  runtimeRoot: '/tmp/studio-controller-runtime',
  cwd: '/tmp/studio-controller-cwd',
})

function project(state) {
  return {
    state_ref: {
      run_id: state.run_id,
      state_revision: state.state_revision,
      state_digest: state.state_digest,
    },
    envelope: {
      run_id: state.run_id,
      status: state.status,
      pending: state.pending,
    },
  }
}

function fakeAdapter(overrides = {}) {
  return {
    admit: async () => ({ schema: 'opaque-capability' }),
    startRole: async (_, { actorId }) => `role:${actorId}`,
    resumeRole: async () => {},
    beginTurn: async (_, { actionId }) => `turn:${actionId}`,
    inspectTurnBinding: (_, turn) => ({ schema: 'binding', turn }),
    waitTurn: async () => ({ schema: 'receipt' }),
    interruptTurn: async (_, turn) => ({
      schema: 'interrupt-receipt',
      turn,
      receipt_digest: `sha256:${Buffer.from(turn).toString('hex').padEnd(64, '0').slice(0, 64)}`,
    }),
    confirmRoleIdle: () => ({ schema: 'idle-receipt' }),
    cleanupRole: async (_, role) => ({
      schema: 'test-cleanup',
      role,
      host_thread_id: role,
      receipt_digest: `sha256:${Buffer.from(role).toString('hex').padEnd(64, '0').slice(0, 64)}`,
    }),
    verifyReceipt: () => true,
    close: async () => {},
    ...overrides,
  }
}

function oneBarrierStore(outputSchema = {
  type: 'object',
  additionalProperties: false,
  properties: {},
}, terminalStatus = 'completed') {
  let state = {
    run_id: REQUEST.run_id,
    state_revision: 1,
    state_digest: `sha256:${'1'.repeat(64)}`,
    status: 'running',
    pending: {
      barrier_id: `${REQUEST.run_id}:b0001`,
      actions: [{
        action_id: `${REQUEST.run_id}:a0001`,
        actor_id: 'participant:a',
        kind: 'spawn',
        prompt: 'return output',
        output_schema: outputSchema,
      }],
    },
  }
  const journal = {
    schema: 'studio-native-dispatch-journal/v1',
    run_id: REQUEST.run_id,
    journal_revision: 1,
    journal_digest: `sha256:${'4'.repeat(64)}`,
    state_ref: {
      run_id: REQUEST.run_id,
      state_revision: 1,
      state_digest: `sha256:${'1'.repeat(64)}`,
    },
    status: 'active',
    dispatch_started: false,
    native_response_received: false,
    tombstone: null,
    entries: [{
      action_id: `${REQUEST.run_id}:a0001`,
      ordinal: 1,
      actor_id: 'participant:a',
      kind: 'spawn',
      stage: 'scheduled',
      binding: null,
      receipt: null,
      result: null,
      applied_state_revision: null,
    }],
  }
  const calls = []
  const store = {
    create: async () => project(state),
    read: async () => structuredClone(state),
    recordRequestSent: async request => {
      calls.push(['request_sent', request.action_id])
      journal.dispatch_started = true
      journal.entries[0].stage = 'request_sent'
    },
    recordResponseReceived: async request => {
      calls.push(['response_received', request.action_id])
      journal.native_response_received = true
      journal.entries[0].stage = 'response_received'
      journal.entries[0].binding = {
        host_thread_id: 'thread:RUN-controller:a0001',
        host_turn_id: 'turn:RUN-controller:a0001',
      }
      state.state_revision = 2
      state.state_digest = `sha256:${'2'.repeat(64)}`
      return project(state)
    },
    recordTerminalEvent: async request => {
      calls.push(['terminal_event', request.action_id])
      journal.entries[0].stage = 'terminal_event'
      journal.entries[0].receipt = {
        schema: 'receipt',
        receipt_digest: `sha256:${'5'.repeat(64)}`,
      }
      journal.entries[0].result = { status: 'succeeded' }
    },
    applyProductionBarrier: async () => {
      calls.push(['apply'])
      state = {
        ...state,
        state_revision: 3,
        state_digest: `sha256:${'3'.repeat(64)}`,
        status: terminalStatus,
        pending: null,
      }
      journal.state_ref = {
        run_id: state.run_id,
        state_revision: state.state_revision,
        state_digest: state.state_digest,
      }
      journal.entries[0].applied_state_revision = state.state_revision
      return project(state)
    },
    markDispatchRecoveryRequired: async (_, details) => { calls.push(['recovery', details.code]) },
    tombstoneDispatch: async (_, { cleanupReceipts }) => {
      calls.push(['tombstone'])
      journal.status = 'tombstoned'
      journal.tombstone = {
        cleanup: 'complete',
        cleanup_receipts: cleanupReceipts.map(receipt => ({
          schema: receipt.schema,
          host_thread_id: receipt.host_thread_id,
          receipt_digest: receipt.receipt_digest,
        })),
      }
    },
    readDispatch: async () => structuredClone(journal),
    project,
  }
  return { store, calls }
}

function twoActionFenceStore() {
  let state = {
    run_id: REQUEST.run_id,
    state_revision: 1,
    state_digest: `sha256:${'1'.repeat(64)}`,
    status: 'running',
    pending: {
      barrier_id: `${REQUEST.run_id}:b0001`,
      actions: ['a', 'b'].map((crew, index) => ({
        action_id: `${REQUEST.run_id}:a000${index + 1}`,
        actor_id: `participant:${crew}`,
        kind: 'spawn',
        prompt: `return ${crew}`,
        output_schema: { type: 'object', additionalProperties: false, properties: {} },
      })),
    },
  }
  const calls = []
  const entries = state.pending.actions.map((action, index) => ({
    action_id: action.action_id,
    ordinal: index + 1,
    actor_id: action.actor_id,
    kind: action.kind,
    stage: 'scheduled',
    binding: null,
    receipt: null,
    result: null,
    applied_state_revision: null,
  }))
  const journal = {
    schema: 'studio-native-dispatch-journal/v1',
    run_id: REQUEST.run_id,
    journal_revision: 1,
    journal_digest: `sha256:${'4'.repeat(64)}`,
    state_ref: null,
    status: 'active',
    dispatch_started: false,
    native_response_received: false,
    tombstone: null,
    entries,
  }
  const store = {
    create: async () => project(state),
    read: async () => structuredClone(state),
    recordRequestSent: async request => {
      assert.equal(request.expected_state_revision, state.state_revision)
      assert.equal(request.expected_state_digest, state.state_digest)
      calls.push(['request_sent', request.action_id])
      entries.find(entry => entry.action_id === request.action_id).stage = 'request_sent'
      journal.dispatch_started = true
      if (calls.filter(call => call[0] === 'request_sent').length === 1) {
        state.state_revision = 2
        state.state_digest = `sha256:${'2'.repeat(64)}`
      }
    },
    recordResponseReceived: async request => {
      calls.push(['response_received', request.action_id])
      const entry = entries.find(candidate => candidate.action_id === request.action_id)
      entry.stage = 'response_received'
      entry.binding = {
        host_thread_id: `role:${entry.actor_id}`,
        host_turn_id: `turn:${entry.action_id}`,
      }
      journal.native_response_received = true
      return project(state)
    },
    recordTerminalEvent: async request => {
      calls.push(['terminal_event', request.action_id])
      const entry = entries.find(candidate => candidate.action_id === request.action_id)
      entry.stage = 'terminal_event'
      entry.receipt = {
        schema: 'receipt',
        action_ref: `sha256:${String(entry.ordinal).repeat(64)}`,
        receipt_digest: `sha256:${String(entry.ordinal + 2).repeat(64)}`,
      }
      entry.result = { status: 'succeeded' }
    },
    applyProductionBarrier: async () => {
      calls.push(['apply'])
      state = {
        ...state,
        state_revision: 3,
        state_digest: `sha256:${'3'.repeat(64)}`,
        status: 'completed',
        pending: null,
      }
      entries.forEach(entry => { entry.applied_state_revision = state.state_revision })
      return project(state)
    },
    markDispatchRecoveryRequired: async (_, details) => { calls.push(['recovery', details.code]) },
    tombstoneDispatch: async (_, { cleanupReceipts }) => {
      calls.push(['tombstone'])
      journal.status = 'tombstoned'
      journal.state_ref = {
        run_id: state.run_id,
        state_revision: state.state_revision,
        state_digest: state.state_digest,
      }
      journal.tombstone = {
        cleanup: 'complete',
        cleanup_receipts: cleanupReceipts.map(receipt => ({
          schema: receipt.schema,
          host_thread_id: receipt.host_thread_id,
          receipt_digest: receipt.receipt_digest,
        })),
      }
    },
    readDispatch: async () => structuredClone(journal),
    project,
  }
  return { store, calls }
}

function testController(store, adapter) {
  return createPersistentBrainstormControllerForTest({
    store,
    adapterFactory: () => adapter,
  })
}

test('controller completes the native journal sequence and never exposes raw state input', async () => {
  const { store, calls } = oneBarrierStore()
  const execute = testController(store, fakeAdapter())
  const result = await execute(REQUEST, CONFIG)
  assert.equal(result.ok, true)
  assert.equal(result.execution_path, 'persistent-native-app-server')
  assert.equal(result.fallback_allowed, false)
  assert.equal(isProductionBrainstormResult(result), false)
  assert.equal(result.cleanup_receipts.length, 1)
  assert.equal(result.workflow_receipt.evidence_class, 'deterministic-test-chain')
  assert.equal(result.workflow_receipt.raw_state_exposed, false)
  assert.equal(result.workflow_receipt.action_receipts.length, 1)
  assert.equal(result.workflow_receipt.action_receipts[0].stage, 'terminal_event')
  assert.match(result.workflow_receipt.receipt_digest, /^sha256:[0-9a-f]{64}$/)
  assert.deepEqual(calls.map(call => call[0]), [
    'request_sent',
    'response_received',
    'terminal_event',
    'apply',
    'tombstone',
  ])

  await assert.rejects(
    execute({ ...REQUEST, capability: {} }, CONFIG),
    error => error.code === 'invalid_request',
  )
})

test('controller preserves broker const semantics through the host enum subset', async () => {
  const { store } = oneBarrierStore({
    type: 'object',
    additionalProperties: false,
    required: ['alive'],
    properties: {
      alive: { type: 'boolean', const: true },
    },
  })
  let observedSchema = null
  const adapter = fakeAdapter({
    beginTurn: async (_, { actionId, outputSchema }) => {
      observedSchema = outputSchema
      return `turn:${actionId}`
    },
  })
  const result = await testController(store, adapter)(REQUEST, CONFIG)
  assert.equal(result.ok, true)
  assert.deepEqual(observedSchema.properties.alive.enum, [true])
  assert.equal(Object.hasOwn(observedSchema.properties.alive, 'const'), false)
  assert.deepEqual(observedSchema.required, ['alive'])
})

test('cleanly tombstoned aborted workflow is not reported as Production success', async () => {
  const { store } = oneBarrierStore(undefined, 'aborted')
  const result = await testController(store, fakeAdapter())(REQUEST, CONFIG)
  assert.equal(result.ok, false)
  assert.equal(isCompletedControllerOutput(result), false)
  assert.equal(result.status, 'aborted')
  assert.equal(result.envelope.status, 'aborted')
  assert.equal(result.execution_path, 'persistent-native-app-server')
  assert.equal(result.fallback_allowed, false)
  assert.equal(result.workflow_receipt.journal.status, 'tombstoned')
})

test('CLI success predicate requires the complete exact Production terminal shape', () => {
  const completed = {
    schema: 'studio-persistent-brainstorm-controller/v1',
    ok: true,
    status: 'completed',
    execution_path: 'persistent-native-app-server',
    fallback_allowed: false,
    envelope: { status: 'completed' },
    workflow_receipt: {
      schema: 'studio-persistent-production-workflow-receipt/v1',
    },
  }
  assert.equal(isCompletedControllerOutput(completed), true)
  for (const invalid of [
    { ...completed, ok: false },
    { ...completed, status: 'aborted' },
    { ...completed, execution_path: 'isolated-runner' },
    { ...completed, fallback_allowed: true },
    { ...completed, envelope: { status: 'failed' } },
    { ...completed, workflow_receipt: { schema: 'wrong' } },
  ]) {
    assert.equal(isCompletedControllerOutput(invalid), false)
  }
})

test('controller refreshes the durable fence between two request_sent transitions', async () => {
  const { store, calls } = twoActionFenceStore()
  const result = await testController(store, fakeAdapter())(REQUEST, CONFIG)
  assert.equal(result.ok, true)
  assert.deepEqual(calls.map(call => call[0]), [
    'request_sent',
    'request_sent',
    'response_received',
    'response_received',
    'terminal_event',
    'terminal_event',
    'apply',
    'tombstone',
  ])
})

test('pending spawn creates only its actor after the durable request_sent fence', async () => {
  const { store } = oneBarrierStore()
  const events = []
  const recordRequestSent = store.recordRequestSent
  store.recordRequestSent = async request => {
    events.push(`request:${request.action_id}`)
    return recordRequestSent(request)
  }
  const adapter = fakeAdapter({
    startRole: async (_, { actorId }) => {
      events.push(`spawn:${actorId}`)
      return `role:${actorId}`
    },
  })
  const result = await testController(store, adapter)(REQUEST, CONFIG)
  assert.equal(result.ok, true)
  assert.deepEqual(events, [
    'request:RUN-controller:a0001',
    'spawn:participant:a',
  ])
  assert.equal(result.cleanup_receipts.length, 1)
})

test('native admission failure stops the persistent Production route with safe diagnostics', async () => {
  const diagnostics = {
    version: { expected: ['codex-cli pinned'], actual: 'codex-cli drifted', matched: false },
    binary_digest: { expected: [`sha256:${'1'.repeat(64)}`], actual: `sha256:${'2'.repeat(64)}`, matched: false },
    schema_digest: { expected: [`sha256:${'3'.repeat(64)}`], actual: `sha256:${'3'.repeat(64)}`, matched: true },
  }
  const execute = testController(
    oneBarrierStore().store,
    fakeAdapter({
      admit: async () => {
        throw new NativeAdapterError(
          'capability_allowlist_mismatch',
          'drifted',
          { allowlist_diagnostics: diagnostics },
        )
      },
    }),
  )
  const result = await execute(REQUEST, CONFIG)
  assert.deepEqual(result, {
    schema: 'studio-persistent-brainstorm-controller/v1',
    ok: false,
    status: 'admission_failed',
    execution_path: 'persistent-native-app-server',
    fallback_allowed: false,
    reason: 'capability_allowlist_mismatch',
    admission_diagnostics: diagnostics,
  })
  assert.equal(isProductionBrainstormResult(result), false)
})

test('partial role-start failure drains siblings, cleans created roles, and forbids fallback', async () => {
  const { store, calls } = twoActionFenceStore()
  const events = []
  const adapter = fakeAdapter({
    startRole: async (_, { actorId }) => {
      events.push(`start:${actorId}`)
      if (actorId === 'participant:b') {
        throw new NativeAdapterError('role_start_failed', 'injected partial start')
      }
      return `role:${actorId}`
    },
    interruptTurn: async (_, turn) => {
      events.push(`interrupt:${turn}`)
      return { schema: 'interrupt-receipt', receipt_digest: `sha256:${'8'.repeat(64)}` }
    },
    cleanupRole: async (_, role) => {
      events.push(`cleanup:${role}`)
      return {
        schema: 'test-cleanup',
        role,
        host_thread_id: role,
        receipt_digest: `sha256:${'9'.repeat(64)}`,
      }
    },
  })
  const result = await testController(store, adapter)(REQUEST, CONFIG)
  assert.equal(result.status, 'recovery_required')
  assert.equal(result.fallback_allowed, false)
  assert.deepEqual(calls.slice(0, 2).map(call => call[0]), ['request_sent', 'request_sent'])
  assert.ok(events.includes('interrupt:turn:RUN-controller:a0001'))
  assert.ok(events.includes('cleanup:role:participant:a'))
  assert.equal(result.cleanup_receipts.length, 1)
  assert.equal(result.interrupt_receipts.length, 1)
})

test('parallel begin and wait failures drain settled siblings before role cleanup', async t => {
  for (const stage of ['begin', 'wait']) {
    await t.test(stage, async () => {
      const { store } = twoActionFenceStore()
      const events = []
      const adapter = fakeAdapter({
        beginTurn: async (_, { actionId }) => {
          if (stage === 'begin' && actionId.endsWith('2')) {
            throw new NativeAdapterError('begin_failed', 'injected begin failure')
          }
          return `turn:${actionId}`
        },
        waitTurn: async (_, turn) => {
          if (stage === 'wait' && turn.endsWith('2')) {
            throw new NativeAdapterError('wait_failed', 'injected wait failure')
          }
          if (stage === 'wait') await new Promise(resolveWait => setTimeout(resolveWait, 5))
          return { schema: 'receipt' }
        },
        interruptTurn: async (_, turn) => {
          events.push(`interrupt:${turn}`)
          return {
            schema: 'interrupt-receipt',
            receipt_digest: `sha256:${'7'.repeat(64)}`,
          }
        },
        cleanupRole: async (_, role) => {
          events.push(`cleanup:${role}`)
          return {
            schema: 'test-cleanup',
            host_thread_id: role,
            receipt_digest: `sha256:${'6'.repeat(64)}`,
          }
        },
      })
      const result = await testController(store, adapter)(REQUEST, CONFIG)
      assert.equal(result.status, 'recovery_required')
      assert.equal(result.fallback_allowed, false)
      assert.equal(result.cleanup_receipts.length, 2)
      assert.ok(events.includes('cleanup:role:participant:a'))
      assert.ok(events.includes('cleanup:role:participant:b'))
      const expectedInterrupted = stage === 'begin'
        ? 'turn:RUN-controller:a0001'
        : 'turn:RUN-controller:a0002'
      assert.deepEqual(
        events.filter(event => event.startsWith('interrupt:')),
        [`interrupt:${expectedInterrupted}`],
      )
    })
  }
})

test('store create failure never preallocates native roles or mints fallback', async () => {
  const events = []
  const store = {
    create: async () => { throw new Error('injected store create failure') },
  }
  const adapter = fakeAdapter({
    startRole: async (_, { actorId }) => {
      events.push(`start:${actorId}`)
      return `role:${actorId}`
    },
    cleanupRole: async (_, role) => {
      events.push(`cleanup:${role}`)
      return { schema: 'cleanup' }
    },
  })
  await assert.rejects(
    testController(store, adapter)(REQUEST, CONFIG),
    /injected store create failure/,
  )
  assert.deepEqual(events, [])
})

test('once beginTurn is accepted, injected terminal failure cannot invoke Runner fallback', async () => {
  const { store, calls } = oneBarrierStore()
  const execute = testController(
    store,
    fakeAdapter({
      waitTurn: async () => {
        throw new NativeAdapterError('terminal_event_missing', 'injected after accepted turn')
      },
    }),
  )
  const result = await execute(REQUEST, CONFIG)
  assert.equal(result.ok, false)
  assert.equal(result.status, 'recovery_required')
  assert.equal(result.execution_path, 'persistent-native-app-server')
  assert.equal(result.fallback_allowed, false)
  assert.deepEqual(calls.map(call => call[0]), [
    'request_sent',
    'response_received',
    'recovery',
  ])
})

test('cleanup failure refreshes projection and returns recovery-required', async () => {
  const { store, calls } = oneBarrierStore()
  let cleanupCalls = 0
  const execute = testController(store, fakeAdapter({
    cleanupRole: async () => {
      cleanupCalls += 1
      if (cleanupCalls === 1) throw new NativeAdapterError('cleanup_incomplete', 'injected')
      return { schema: 'test-cleanup', ordinal: cleanupCalls }
    },
  }))
  const result = await execute(REQUEST, CONFIG)
  assert.equal(result.ok, false)
  assert.equal(result.status, 'recovery_required')
  assert.equal(result.reason, 'cleanup_incomplete')
  assert.equal(result.fallback_allowed, false)
  assert.equal(result.cleanup_receipts.length, 0)
  assert.deepEqual(calls.map(call => call[0]), [
    'request_sent',
    'response_received',
    'terminal_event',
    'apply',
    'recovery',
  ])
})

test('Production entry rejects dependency injection before adapter creation', async () => {
  await assert.rejects(
    executeProductionBrainstorm(REQUEST, {
      ...CONFIG,
      adapterFactory: () => fakeAdapter(),
    }),
    error => error.code === 'controller_config_invalid',
  )
})

test('only completed output failures become exact-validator repair candidates', () => {
  const action = { action_id: 'a', kind: 'followup', host_handle: 'thread-a' }
  const failure = {
    schema: 'studio-native-failure-receipt/v1',
    terminal_status: 'completed',
    error_code: 'output_schema_mismatch',
    host_thread_id: 'thread-a',
    output: { answer: 'must-not-apply' },
  }
  validateNativeTerminalReceipt(action, failure)
  assert.deepEqual(nativeResult(action, failure), {
    action_id: 'a',
    host_handle: 'thread-a',
    tokens: null,
    token_coverage: 'unavailable',
    error: null,
    status: 'succeeded',
    output: { answer: 'must-not-apply' },
  })
  assert.throws(
    () => validateNativeTerminalReceipt(action, {
      ...failure,
      error_code: 'forbidden_terminal_item',
    }),
    error => error.code === 'native_receipt_invalid',
  )
  assert.throws(
    () => validateNativeTerminalReceipt(action, {
      schema: 'studio-native-action-receipt/v1',
      terminal_status: 'failed',
      output: { answer: 'forged-success' },
    }),
    error => error.code === 'native_receipt_invalid',
  )
})
