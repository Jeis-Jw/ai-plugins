#!/usr/bin/env node
import { createHash } from 'node:crypto'
import { lstat, readFile } from 'node:fs/promises'
import { isAbsolute, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  PersistentBrokerError,
} from '../broker/persistent_brainstorm_broker.mjs'
import { PersistentBrainstormStore } from '../broker/persistent_brainstorm_store.mjs'
import {
  NativeAdapterError,
  createPersistentNativeAppServer,
  isAdapterOwnedNativeReceipt,
} from './persistent_native_app_server.mjs'

const CONTROLLER_SCHEMA = 'studio-persistent-brainstorm-controller/v1'
const MAX_REQUEST_BYTES = 1024 * 1024
const PRODUCTION_RESULTS = new WeakSet()
const TEST_RESULTS = new WeakSet()
const WORKFLOW_RECEIPT_SCHEMA = 'studio-persistent-production-workflow-receipt/v1'
const REQUEST_FIELDS = new Set([
  'run_id',
  'workflow_name',
  'agenda',
  'productionProfile',
  'maxRounds',
  'dryStop',
  'criticRubric',
  'personas',
])
const PRODUCTION_OPTION_FIELDS = new Set([
  'stateRoot',
  'runtimeRoot',
  'cwd',
  'concurrency',
])

function unicodeCompare(left, right) {
  const a = Array.from(String(left), character => character.codePointAt(0))
  const b = Array.from(String(right), character => character.codePointAt(0))
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index]
  }
  return a.length - b.length
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort(unicodeCompare).map(key => (
      `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    )).join(',')}}`
  }
  return JSON.stringify(value)
}

function digest(value) {
  return `sha256:${createHash('sha256').update(canonicalJson(value), 'utf8').digest('hex')}`
}

function strictProductionSchema(schema) {
  const value = structuredClone(schema)
  if (Object.hasOwn(value || {}, 'const')) {
    value.enum = [value.const]
    delete value.const
  }
  if (value?.type === 'object') {
    value.required = Object.keys(value.properties || {}).sort(unicodeCompare)
    for (const [key, child] of Object.entries(value.properties || {})) {
      value.properties[key] = strictProductionSchema(child)
    }
  } else if (value?.type === 'array') {
    value.items = strictProductionSchema(value.items)
  }
  return value
}

function makeWorkflowReceipt({
  authority,
  capability,
  request,
  concurrency,
  cwd,
  project,
  journal,
  cleanupReceipts,
}) {
  const production = authority === 'production'
  const persistedCleanup = journal?.tombstone?.cleanup_receipts
  if (
    !journal
    || journal.schema !== 'studio-native-dispatch-journal/v1'
    || journal.status !== 'tombstoned'
    || journal.dispatch_started !== true
    || journal.native_response_received !== true
    || journal.tombstone?.cleanup !== 'complete'
    || !Array.isArray(persistedCleanup)
    || persistedCleanup.length < 1
    || !Array.isArray(journal.entries)
    || journal.entries.length < 1
    || journal.entries.some(entry => (
      entry.stage !== 'terminal_event'
      || !Number.isInteger(entry.applied_state_revision)
      || !/^sha256:[0-9a-f]{64}$/.test(entry.receipt?.receipt_digest || '')
    ))
    || journal.state_ref?.state_digest !== project.state_ref?.state_digest
    || journal.state_ref?.state_revision !== project.state_ref?.state_revision
    || !Array.isArray(cleanupReceipts)
    || cleanupReceipts.length !== persistedCleanup.length
    || cleanupReceipts.some(receipt => (
      !persistedCleanup.some(projected => projected.receipt_digest === receipt.receipt_digest)
    ))
    || (production && cleanupReceipts.some(receipt => (
      !isAdapterOwnedNativeReceipt(receipt)
      || receipt.schema !== 'studio-native-cleanup-receipt/v1'
      || receipt.deleted !== true
      || receipt.deletion_notified !== true
      || receipt.rollout_absent !== true
      || !/^sha256:[0-9a-f]{64}$/.test(receipt.receipt_digest || '')
    )))
    || (production && (
      !/^sha256:[0-9a-f]{64}$/.test(capability?.admission_evidence_digest || '')
      || !/^sha256:[0-9a-f]{64}$/.test(
        capability?.tool_inventory_capture?.evidence_digest || '',
      )
      || capability?.tool_inventory_capture?.capture_ref
        !== capability?.tool_inventory_capture?.raw_tools_digest
      || typeof capability?.tool_inventory_capture?.model !== 'string'
      || !capability.tool_inventory_capture.model
    ))
  ) {
    throw new NativeAdapterError(
      'workflow_receipt_invalid',
      'Production workflow receipt cannot be proven from the terminal journal and cleanup receipts',
    )
  }
  const base = {
    schema: WORKFLOW_RECEIPT_SCHEMA,
    evidence_class: production
      ? 'adapter-owned-production-chain'
      : 'deterministic-test-chain',
    run_id: journal.run_id,
    admission: {
      evidence_class: production
        ? 'adapter-owned-production-admission'
        : 'deterministic-test-admission',
      admission_evidence_digest: capability?.admission_evidence_digest || null,
      tool_inventory_evidence_digest:
        capability?.tool_inventory_capture?.evidence_digest || null,
      tool_inventory_capture_ref:
        capability?.tool_inventory_capture?.capture_ref || null,
      actual_model: capability?.tool_inventory_capture?.model || null,
      actual_reasoning_effort:
        capability?.tool_inventory_capture?.reasoning_effort ?? null,
    },
    execution_input: {
      request_digest: digest(request),
      concurrency,
      cwd_ref: digest(cwd),
    },
    state_ref: structuredClone(project.state_ref),
    envelope_digest: digest(project.envelope),
    journal: {
      schema: journal.schema,
      status: journal.status,
      journal_revision: journal.journal_revision,
      journal_digest: journal.journal_digest,
      state_ref: structuredClone(journal.state_ref),
      dispatch_started: journal.dispatch_started,
      native_response_received: journal.native_response_received,
      tombstone: structuredClone(journal.tombstone),
    },
    action_receipts: journal.entries.map(entry => ({
      action_id: entry.action_id,
      ordinal: entry.ordinal,
      actor_id: entry.actor_id,
      kind: entry.kind,
      stage: entry.stage,
      action_ref: entry.receipt?.action_ref || null,
      host_thread_id: entry.binding?.host_thread_id || null,
      host_turn_id: entry.binding?.host_turn_id || null,
      receipt_schema: entry.receipt?.schema || null,
      receipt_digest: entry.receipt?.receipt_digest || null,
      result_status: entry.result?.status || null,
      applied_state_revision: entry.applied_state_revision,
    })),
    cleanup_receipts: structuredClone(persistedCleanup),
    raw_state_exposed: false,
    fallback_allowed: false,
  }
  return Object.freeze({
    ...base,
    receipt_digest: digest(base),
  })
}

function validateRequest(request) {
  if (
    !request
    || typeof request !== 'object'
    || Array.isArray(request)
    || Object.keys(request).some(key => !REQUEST_FIELDS.has(key))
    || typeof request.run_id !== 'string'
    || !request.run_id.trim()
    || typeof request.workflow_name !== 'string'
    || !request.workflow_name.trim()
    || !Array.isArray(request.personas)
    || request.personas.length < 2
  ) {
    throw new PersistentBrokerError(
      'invalid_request',
      'controller request differs from the opaque Production brainstorm contract',
    )
  }
  return structuredClone(request)
}

async function mapBounded(values, limit, operation) {
  const results = new Array(values.length)
  const failures = new Array(values.length)
  let cursor = 0
  async function worker() {
    while (cursor < values.length) {
      const index = cursor
      cursor += 1
      try {
        results[index] = await operation(values[index], index)
      } catch (error) {
        failures[index] = error
      }
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(limit, values.length) }, () => worker()),
  )
  const firstFailure = failures.find(Boolean)
  if (firstFailure) throw firstFailure
  return results
}

async function cleanupBoundRoles(adapter, capability, roles) {
  const receipts = []
  let complete = true
  for (const role of roles.values()) {
    try {
      const receipt = await adapter.cleanupRole(capability, role)
      if (!adapter.verifyReceipt(capability, receipt)) {
        throw new NativeAdapterError(
          'native_receipt_required',
          'cleanup receipt was not minted by the active adapter instance',
        )
      }
      receipts.push(receipt)
    } catch {
      complete = false
    }
  }
  return { complete, receipts }
}

async function drainActiveTurns(adapter, capability, activeTurns) {
  const receipts = []
  let complete = true
  for (const { turn } of activeTurns.values()) {
    try {
      const receipt = await adapter.interruptTurn(capability, turn)
      if (!adapter.verifyReceipt(capability, receipt)) {
        throw new NativeAdapterError(
          'native_receipt_required',
          'interrupt receipt was not minted by the active adapter instance',
        )
      }
      receipts.push(receipt)
    } catch {
      complete = false
    }
  }
  activeTurns.clear()
  return { complete, receipts }
}

function actorIds(request) {
  const participants = request.personas.map(persona => `participant:${String(persona?.crew || persona?.name || '').trim()}`)
  if (participants.some(value => value === 'participant:') || new Set(participants).size !== participants.length) {
    throw new PersistentBrokerError('invalid_actor', 'controller personas need unique non-empty crew names')
  }
  return [...participants, 'critic:critic', 'summarizer:summarizer']
}

function admissionFailureResult(error) {
  return {
    schema: CONTROLLER_SCHEMA,
    ok: false,
    status: 'admission_failed',
    execution_path: 'persistent-native-app-server',
    fallback_allowed: false,
    reason: error.code || 'native_admission_unavailable',
    admission_diagnostics: error.details?.allowlist_diagnostics || null,
  }
}

function recoveryResult(project, error) {
  return {
    schema: CONTROLLER_SCHEMA,
    ok: false,
    status: 'recovery_required',
    execution_path: 'persistent-native-app-server',
    fallback_allowed: false,
    reason: error.code || 'native_recovery_required',
    ...(project ? { ...project } : {}),
  }
}

function brandResult(result, authority) {
  const value = Object.freeze(result)
  ;(authority === 'production' ? PRODUCTION_RESULTS : TEST_RESULTS).add(value)
  return value
}

export function isProductionBrainstormResult(value) {
  return Boolean(value && typeof value === 'object' && PRODUCTION_RESULTS.has(value))
}

export function isCompletedControllerOutput(result) {
  return Boolean(
    result
    && result.schema === CONTROLLER_SCHEMA
    && result.ok === true
    && result.status === 'completed'
    && result.execution_path === 'persistent-native-app-server'
    && result.fallback_allowed === false
    && result.envelope?.status === 'completed'
    && result.workflow_receipt?.schema === WORKFLOW_RECEIPT_SCHEMA
  )
}

async function terminalReceipt(adapter, capability, turn) {
  let receipt
  try {
    receipt = await adapter.waitTurn(capability, turn)
  } catch (error) {
    if (error instanceof NativeAdapterError && error.details?.receipt) {
      receipt = error.details.receipt
    } else {
      throw error
    }
  }
  if (!adapter.verifyReceipt(capability, receipt)) {
    throw new NativeAdapterError(
      'native_receipt_required',
      'terminal receipt was not minted by the active adapter instance',
    )
  }
  return receipt
}

async function executeBrainstorm(request, {
  stateRoot,
  runtimeRoot,
  cwd,
  concurrency = 4,
}, {
  adapterFactory,
  store,
  authority,
}) {
  const input = validateRequest(request)
  if (
    !isAbsolute(stateRoot || '')
    || !isAbsolute(runtimeRoot || '')
    || !isAbsolute(cwd || '')
    || !Number.isInteger(concurrency)
    || concurrency < 1
    || concurrency > 16
  ) {
    throw new PersistentBrokerError(
      'controller_config_invalid',
      'stateRoot, runtimeRoot, cwd and bounded concurrency are required',
    )
  }

  const runtimeStore = store
  const adapter = adapterFactory({ runtimeRoot, cwd })
  const roles = new Map()
  const activeTurns = new Map()
  let capability
  let project = null
  let dispatchStarted = false
  let terminal = false
  try {
    try {
      capability = await adapter.admit()
    } catch (error) {
      if (error instanceof NativeAdapterError) {
        return brandResult(admissionFailureResult(error), authority)
      }
      throw error
    }

    actorIds(input)
    project = await runtimeStore.create({
      ...input,
      admission: 'production',
      capability,
    })

    for (let barrierCount = 0; barrierCount < 128; barrierCount += 1) {
      const state = await runtimeStore.read(input.run_id)
      if (!state.pending) {
        terminal = true
        project = runtimeStore.project(state)
        break
      }

      for (const action of state.pending.actions) {
        const current = await runtimeStore.read(input.run_id)
        dispatchStarted = true
        await runtimeStore.recordRequestSent({
          run_id: current.run_id,
          expected_state_revision: current.state_revision,
          expected_state_digest: current.state_digest,
          action_id: action.action_id,
        })
      }

      const ordinary = state.pending.actions.filter(action => action.kind !== 'interrupt')
      const prepared = await mapBounded(ordinary, concurrency, async action => {
        let role = roles.get(action.actor_id)
        if (action.kind === 'spawn') {
          if (role) {
            throw new NativeAdapterError(
              'host_identity_reused',
              'spawn action actor already has a native role',
            )
          }
          role = await adapter.startRole(capability, { actorId: action.actor_id })
          roles.set(action.actor_id, role)
        } else if (!role) {
          throw new NativeAdapterError('role_reference_invalid', 'canonical actor has no native role')
        }
        if (action.kind === 'followup') await adapter.resumeRole(capability, role)
        const turn = await adapter.beginTurn(capability, {
          role,
          actionId: action.action_id,
          prompt: action.prompt,
          outputSchema: strictProductionSchema(action.output_schema),
        })
        activeTurns.set(action.action_id, { action, turn, role })
        return {
          action,
          turn,
          binding: adapter.inspectTurnBinding(capability, turn),
        }
      })

      for (const item of prepared) {
        const current = await runtimeStore.read(input.run_id)
        project = await runtimeStore.recordResponseReceived({
          run_id: current.run_id,
          expected_state_revision: current.state_revision,
          expected_state_digest: current.state_digest,
          action_id: item.action.action_id,
          binding: item.binding,
        })
      }

      const received = await mapBounded(prepared, concurrency, async item => {
        const receipt = await terminalReceipt(adapter, capability, item.turn)
        activeTurns.delete(item.action.action_id)
        return { action: item.action, receipt }
      })
      for (const item of received) {
        const current = await runtimeStore.read(input.run_id)
        await runtimeStore.recordTerminalEvent({
          run_id: current.run_id,
          expected_state_revision: current.state_revision,
          expected_state_digest: current.state_digest,
          action_id: item.action.action_id,
          receipt: item.receipt,
        })
      }

      for (const action of state.pending.actions.filter(item => item.kind === 'interrupt')) {
        const role = roles.get(action.actor_id)
        if (!role) {
          throw new NativeAdapterError('role_reference_invalid', 'cancel actor has no native role')
        }
        const idleReceipt = adapter.confirmRoleIdle(capability, role, {
          actionId: action.action_id,
        })
        if (!adapter.verifyReceipt(capability, idleReceipt)) {
          throw new NativeAdapterError(
            'native_receipt_required',
            'idle cancellation receipt was not minted by the active adapter instance',
          )
        }
        const current = await runtimeStore.read(input.run_id)
        await runtimeStore.recordTerminalEvent({
          run_id: current.run_id,
          expected_state_revision: current.state_revision,
          expected_state_digest: current.state_digest,
          action_id: action.action_id,
          receipt: idleReceipt,
        })
      }

      const current = await runtimeStore.read(input.run_id)
      project = await runtimeStore.applyProductionBarrier({
        run_id: current.run_id,
        expected_state_revision: current.state_revision,
        expected_state_digest: current.state_digest,
      })
    }

    if (!terminal) {
      throw new PersistentBrokerError('barrier_limit_exceeded', 'Production brainstorm exceeded the barrier bound')
    }

    const cleanup = await cleanupBoundRoles(adapter, capability, roles)
    const cleanupReceipts = cleanup.receipts
    if (!cleanup.complete || cleanupReceipts.length !== roles.size) {
      const cleanupError = new NativeAdapterError(
        'cleanup_incomplete',
        'one or more native role threads were not proven deleted',
      )
      await runtimeStore.markDispatchRecoveryRequired(input.run_id, {
        code: cleanupError.code,
      })
      const latest = await runtimeStore.read(input.run_id)
      project = runtimeStore.project(latest)
      return brandResult({
        ...recoveryResult(project, cleanupError),
        cleanup_receipts: cleanupReceipts,
      }, authority)
    }
    await runtimeStore.tombstoneDispatch(input.run_id, { cleanupReceipts })
    const journal = await runtimeStore.readDispatch(input.run_id)
    const workflowReceipt = makeWorkflowReceipt({
      authority,
      capability,
      request: input,
      concurrency,
      cwd,
      project,
      journal,
      cleanupReceipts,
    })
    const completed = (
      project.envelope.status === 'completed'
      && workflowReceipt.schema === WORKFLOW_RECEIPT_SCHEMA
    )
    return brandResult({
      schema: CONTROLLER_SCHEMA,
      ok: completed,
      status: project.envelope.status,
      execution_path: 'persistent-native-app-server',
      fallback_allowed: false,
      cleanup_receipts: cleanupReceipts,
      workflow_receipt: workflowReceipt,
      ...project,
    }, authority)
  } catch (error) {
    if (dispatchStarted) {
      const drained = capability
        ? await drainActiveTurns(adapter, capability, activeTurns)
        : { complete: false, receipts: [] }
      const cleaned = capability
        ? await cleanupBoundRoles(adapter, capability, roles)
        : { complete: false, receipts: [] }
      const recoveryCode = drained.complete && cleaned.complete
        ? (error.code || 'native_recovery_required')
        : 'cleanup_incomplete'
      await runtimeStore.markDispatchRecoveryRequired(input.run_id, {
        code: recoveryCode,
      }).catch(() => {})
      const latest = await runtimeStore.read(input.run_id).catch(() => null)
      if (latest) project = runtimeStore.project(latest)
      return brandResult({
        ...recoveryResult(project, {
          code: recoveryCode,
        }),
        cleanup_receipts: cleaned.receipts,
        interrupt_receipts: drained.receipts,
      }, authority)
    }
    throw error
  } finally {
    await adapter.close().catch(() => {})
  }
}

export async function executeProductionBrainstorm(request, options = {}) {
  if (
    !options
    || typeof options !== 'object'
    || Array.isArray(options)
    || Object.keys(options).some(key => !PRODUCTION_OPTION_FIELDS.has(key))
  ) {
    throw new PersistentBrokerError(
      'controller_config_invalid',
      'Production controller accepts only stateRoot, runtimeRoot, cwd and concurrency',
    )
  }
  return executeBrainstorm(request, options, {
    adapterFactory: createPersistentNativeAppServer,
    store: new PersistentBrainstormStore(options.stateRoot),
    authority: 'production',
  })
}

export function createPersistentBrainstormControllerForTest({
  adapterFactory,
  store,
}) {
  if (!process.env.NODE_TEST_CONTEXT) {
    throw new PersistentBrokerError(
      'test_factory_forbidden',
      'controller dependency injection is test-runner only',
    )
  }
  if (typeof adapterFactory !== 'function' || !store) {
    throw new PersistentBrokerError(
      'controller_config_invalid',
      'test controller requires an adapter factory and store',
    )
  }
  return (request, options) => executeBrainstorm(request, options, {
    adapterFactory,
    store,
    authority: 'test',
  })
}

function parse(argv) {
  const parsed = {}
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index]
    const value = argv[index + 1]
    if (!['--request-file', '--state-root', '--runtime-root', '--cwd'].includes(flag) || !value) {
      throw new PersistentBrokerError(
        'usage',
        'usage: persistent_brainstorm_controller.mjs --request-file FILE --state-root DIR --runtime-root DIR --cwd DIR',
      )
    }
    parsed[flag.slice(2)] = value
  }
  for (const key of ['request-file', 'state-root', 'runtime-root', 'cwd']) {
    if (!isAbsolute(parsed[key] || '')) {
      throw new PersistentBrokerError('usage', `${key} must be absolute`)
    }
  }
  return parsed
}

async function readRequest(path) {
  const info = await lstat(path).catch(() => null)
  if (!info || !info.isFile() || info.isSymbolicLink() || info.size > MAX_REQUEST_BYTES) {
    throw new PersistentBrokerError('request_file_invalid', 'request must be a bounded regular non-symlink file')
  }
  try {
    return JSON.parse(await readFile(path, 'utf8'))
  } catch {
    throw new PersistentBrokerError('request_file_invalid', 'request file is not valid JSON')
  }
}

async function main() {
  try {
    const cli = parse(process.argv.slice(2))
    const result = await executeProductionBrainstorm(
      await readRequest(cli['request-file']),
      {
        stateRoot: cli['state-root'],
        runtimeRoot: cli['runtime-root'],
        cwd: cli.cwd,
      },
    )
    process.stdout.write(`${JSON.stringify(result)}\n`)
    if (!isCompletedControllerOutput(result)) process.exitCode = 1
  } catch (error) {
    process.stdout.write(`${JSON.stringify({
      schema: CONTROLLER_SCHEMA,
      ok: false,
      status: 'error',
      error: error.code || 'internal_error',
      message: String(error.message || error),
    })}\n`)
    process.exitCode = 1
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main()
}
