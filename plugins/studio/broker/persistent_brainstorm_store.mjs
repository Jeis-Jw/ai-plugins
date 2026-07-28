import { createHash, randomBytes } from 'node:crypto'
import {
  chmod, lstat, mkdir, open, readFile, realpath, rename, rm,
} from 'node:fs/promises'
import {
  isAbsolute, join, parse, resolve, sep,
} from 'node:path'
import {
  BARRIER_RESULT_SCHEMA,
  PersistentBrokerError,
  applyPersistentBarrier,
  createPersistentBrainstorm,
  markPersistentNativeStarted,
  persistentBrainstormEnvelope,
  validatePersistentState,
} from './persistent_brainstorm_broker.mjs'
import {
  isAdapterOwnedNativeReceipt,
  isAdapterOwnedTurnBinding,
} from '../scripts/persistent_native_app_server.mjs'

const MAX_STATE_BYTES = 4 * 1024 * 1024
export const DISPATCH_JOURNAL_SCHEMA = 'studio-native-dispatch-journal/v1'
const JOURNAL_STAGES = Object.freeze([
  'scheduled',
  'request_sent',
  'response_received',
  'terminal_event',
])

function fileKey(runId) {
  return createHash('sha256').update(String(runId), 'utf8').digest('hex')
}

function unicodeCompare(left, right) {
  const a = Array.from(String(left), character => character.codePointAt(0))
  const b = Array.from(String(right), character => character.codePointAt(0))
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index]
  }
  return a.length - b.length
}

function canonicalValue(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalValue).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort(unicodeCompare).map(key => (
      `${JSON.stringify(key)}:${canonicalValue(value[key])}`
    )).join(',')}}`
  }
  return JSON.stringify(value)
}

function digest(value) {
  return `sha256:${createHash('sha256').update(canonicalValue(value), 'utf8').digest('hex')}`
}

function rawDigest(value) {
  return `sha256:${createHash('sha256').update(String(value), 'utf8').digest('hex')}`
}

function withoutJournalDigest(journal) {
  const copy = structuredClone(journal)
  delete copy.journal_digest
  return copy
}

export function persistentDispatchJournalDigest(journal) {
  return digest(withoutJournalDigest(journal))
}

function serialized(value) {
  return `${JSON.stringify(value, null, 2)}\n`
}

async function readRegularJson(path, label = 'state') {
  const info = await lstat(path).catch(() => null)
  if (!info || !info.isFile() || info.isSymbolicLink() || info.size > MAX_STATE_BYTES) {
    throw new PersistentBrokerError(
      `${label}_store_invalid`,
      `${label} file must be a bounded regular file`,
    )
  }
  try {
    return JSON.parse(await readFile(path, 'utf8'))
  } catch {
    throw new PersistentBrokerError(`${label}_store_invalid`, `${label} file is not valid JSON`)
  }
}

async function validateRootComponents(root, allowMissing) {
  const parsed = parse(root)
  const segments = root.slice(parsed.root.length).split(sep).filter(Boolean)
  let current = parsed.root
  for (const segment of segments) {
    current = join(current, segment)
    let info
    try {
      info = await lstat(current)
    } catch (error) {
      if (allowMissing && error.code === 'ENOENT') return
      throw new PersistentBrokerError('state_root_invalid', 'runtime state root component is unavailable')
    }
    if (info.isSymbolicLink() || !info.isDirectory()) {
      throw new PersistentBrokerError('state_root_invalid', 'runtime state root ancestors must be real directories')
    }
  }
}

function stateRef(state) {
  return {
    run_id: state.run_id,
    state_revision: state.state_revision,
    state_digest: state.state_digest,
  }
}

function actionEntry(action) {
  return {
    action_id: action.action_id,
    ordinal: action.ordinal,
    actor_id: action.actor_id,
    kind: action.kind,
    barrier_id: action.barrier_id,
    prompt_schema_digest: action.prompt_schema_digest,
    dispatch_state_revision: action.state_revision,
    dispatch_state_digest: action.state_digest,
    stage: 'scheduled',
    binding: null,
    receipt: null,
    result: null,
    applied_state_revision: null,
  }
}

function sealJournal(journal) {
  journal.journal_digest = persistentDispatchJournalDigest(journal)
  return journal
}

function newJournal(state) {
  const timestamp = new Date().toISOString()
  return sealJournal({
    schema: DISPATCH_JOURNAL_SCHEMA,
    run_id: state.run_id,
    journal_revision: 1,
    journal_digest: null,
    state_ref: stateRef(state),
    status: 'active',
    dispatch_started: false,
    native_response_received: false,
    entries: (state.pending?.actions || []).map(actionEntry),
    created_at: timestamp,
    updated_at: timestamp,
    recovery: null,
    tombstone: null,
  })
}

function advanceJournal(journal) {
  journal.journal_revision += 1
  journal.updated_at = new Date().toISOString()
  return sealJournal(journal)
}

function journalTampered(message) {
  throw new PersistentBrokerError('dispatch_journal_tampered', message)
}

function validateJournal(journal, runId) {
  if (
    !journal
    || journal.schema !== DISPATCH_JOURNAL_SCHEMA
    || journal.run_id !== runId
    || !Number.isInteger(journal.journal_revision)
    || journal.journal_revision < 1
    || journal.journal_digest !== persistentDispatchJournalDigest(journal)
    || !['active', 'recovery_required', 'tombstoned'].includes(journal.status)
    || !Array.isArray(journal.entries)
  ) {
    journalTampered('dispatch journal identity, revision, digest, or status is invalid')
  }
  if (
    journal.state_ref?.run_id !== runId
    || !Number.isInteger(journal.state_ref?.state_revision)
    || !/^sha256:[0-9a-f]{64}$/.test(journal.state_ref?.state_digest || '')
  ) {
    journalTampered('dispatch journal state reference is invalid')
  }
  const actions = new Set()
  const hostTurns = new Set()
  const actorThreads = new Map()
  const threadActors = new Map()
  const threadBindings = new Map()
  for (const entry of journal.entries) {
    const stage = JOURNAL_STAGES.indexOf(entry?.stage)
    if (
      stage < 0
      || typeof entry.action_id !== 'string'
      || actions.has(entry.action_id)
      || !Number.isInteger(entry.ordinal)
      || entry.ordinal < 1
      || typeof entry.actor_id !== 'string'
      || !['spawn', 'followup', 'interrupt'].includes(entry.kind)
      || typeof entry.barrier_id !== 'string'
      || !/^sha256:[0-9a-f]{64}$/.test(entry.prompt_schema_digest || '')
      || !Number.isInteger(entry.dispatch_state_revision)
      || !/^sha256:[0-9a-f]{64}$/.test(entry.dispatch_state_digest || '')
    ) {
      journalTampered('dispatch journal entry identity or stage is invalid')
    }
    actions.add(entry.action_id)
    if (stage < 2 && entry.binding !== null) {
      journalTampered('binding appeared before response_received')
    }
    if (stage < 3 && (entry.receipt !== null || entry.result !== null)) {
      journalTampered('terminal material appeared before terminal_event')
    }
    if (stage >= 2 && entry.binding) {
      const binding = entry.binding
      const idleBinding = (
        entry.kind === 'interrupt'
        && stage === JOURNAL_STAGES.indexOf('terminal_event')
        && binding.schema === 'studio-native-idle-binding/v1'
        && binding.host_turn_id === null
      )
      if (
        (!idleBinding && binding.schema !== 'studio-native-turn-binding/v1')
        || typeof binding.action_ref !== 'string'
        || typeof binding.actor_ref !== 'string'
        || typeof binding.host_thread_id !== 'string'
        || (!idleBinding && typeof binding.host_turn_id !== 'string')
        || (!idleBinding && hostTurns.has(binding.host_turn_id))
      ) {
        journalTampered('serialized native turn binding is invalid or aliases a host turn')
      }
      if (!idleBinding) hostTurns.add(binding.host_turn_id)
      const priorThread = actorThreads.get(entry.actor_id)
      const priorActor = threadActors.get(binding.host_thread_id)
      if (
        (priorThread && priorThread !== binding.host_thread_id)
        || (priorActor && priorActor !== entry.actor_id)
      ) {
        journalTampered('serialized role/thread lineage aliases another actor')
      }
      actorThreads.set(entry.actor_id, binding.host_thread_id)
      threadActors.set(binding.host_thread_id, entry.actor_id)
      threadBindings.set(binding.host_thread_id, binding)
    }
    if (stage >= 3 && (
      !entry.receipt
      || !entry.result
      || entry.result.action_id !== entry.action_id
      || !['succeeded', 'failed', 'cancelled'].includes(entry.result.status)
    )) {
      journalTampered('terminal journal entry is incomplete')
    }
  }
  if (journal.status === 'tombstoned') {
    const cleanupReceipts = journal.tombstone?.cleanup_receipts
    const admittedBinding = threadBindings.values().next().value || null
    if (
      !Number.isFinite(Date.parse(journal.tombstone?.at))
      || journal.tombstone?.cleanup !== 'complete'
      || !Array.isArray(cleanupReceipts)
      || cleanupReceipts.length < threadBindings.size
      || new Set(cleanupReceipts.map(receipt => receipt?.host_thread_id)).size
        !== cleanupReceipts.length
      || new Set(cleanupReceipts.map(receipt => receipt?.actor_ref)).size
        !== cleanupReceipts.length
      || new Set(cleanupReceipts.map(receipt => receipt?.receipt_digest)).size
        !== cleanupReceipts.length
      || [...threadBindings.keys()].some(threadId => (
        !cleanupReceipts.some(receipt => receipt.host_thread_id === threadId)
      ))
      || cleanupReceipts.some(receipt => {
        const binding = threadBindings.get(receipt?.host_thread_id)
        return (
          canonicalValue(
            Object.keys(receipt).sort(unicodeCompare),
          ) !== canonicalValue(
            [
              'schema',
              'actor_ref',
              'host_thread_id',
              'deleted',
              'deletion_notified',
              'rollout_absent',
              'rollout_path_ref',
              'config_digest',
              'environment_digest',
              'receipt_digest',
            ].sort(unicodeCompare),
          )
          || receipt.schema !== 'studio-native-cleanup-receipt/v1'
          || typeof receipt.host_thread_id !== 'string'
          || !/^sha256:[0-9a-f]{64}$/.test(receipt.actor_ref || '')
          || (binding && receipt.actor_ref !== binding.actor_ref)
          || (admittedBinding && receipt.config_digest !== admittedBinding.config_digest)
          || (admittedBinding && receipt.environment_digest !== admittedBinding.environment_digest)
          || receipt.deleted !== true
          || receipt.deletion_notified !== true
          || receipt.rollout_absent !== true
          || !/^sha256:[0-9a-f]{64}$/.test(receipt.rollout_path_ref || '')
          || !/^sha256:[0-9a-f]{64}$/.test(receipt.receipt_digest || '')
        )
      })
    ) {
      journalTampered('tombstoned journal cleanup receipts are incomplete or unbound')
    }
  } else if (journal.tombstone !== null) {
    journalTampered('non-tombstoned journal cannot contain cleanup evidence')
  }
  return journal
}

function syncJournal(journal, state) {
  const byAction = new Map(journal.entries.map(entry => [entry.action_id, entry]))
  for (const action of state.pending?.actions || []) {
    const existing = byAction.get(action.action_id)
    if (existing) {
      if (
        existing.ordinal !== action.ordinal
        || existing.actor_id !== action.actor_id
        || existing.kind !== action.kind
        || existing.barrier_id !== action.barrier_id
        || existing.prompt_schema_digest !== action.prompt_schema_digest
      ) {
        journalTampered('journal action differs from canonical broker action')
      }
    } else {
      journal.entries.push(actionEntry(action))
    }
  }
  const completed = new Map(
    state.ledger
      .filter(entry => entry?.event === 'result')
      .map(entry => [entry.action_id, entry.state_revision]),
  )
  for (const entry of journal.entries) {
    if (completed.has(entry.action_id) && entry.applied_state_revision === null) {
      entry.applied_state_revision = completed.get(entry.action_id) + 1
    }
  }
  journal.state_ref = stateRef(state)
  return journal
}

function bindingProjection(binding) {
  return {
    schema: binding.schema,
    action_ref: binding.action_ref,
    actor_ref: binding.actor_ref,
    host_thread_id: binding.host_thread_id,
    host_turn_id: binding.host_turn_id,
    environment_digest: binding.environment_digest,
    config_digest: binding.config_digest,
  }
}

function receiptProjection(receipt) {
  return {
    schema: receipt.schema,
    action_ref: receipt.action_ref,
    actor_ref: receipt.actor_ref,
    host_thread_id: receipt.host_thread_id,
    host_turn_id: receipt.host_turn_id,
    terminal_status: receipt.terminal_status,
    receipt_digest: receipt.receipt_digest || digest(receipt),
    ...(receipt.error_code ? { error_code: receipt.error_code } : {}),
  }
}

export function nativeResult(action, receipt) {
  const base = {
    action_id: action.action_id,
    host_handle: receipt.host_thread_id || action.host_handle || null,
    tokens: null,
    token_coverage: 'unavailable',
    error: null,
  }
  if (receipt.schema === 'studio-native-interrupt-receipt/v1'
    || receipt.schema === 'studio-native-idle-cancel-receipt/v1') {
    return { ...base, status: 'cancelled', output: { cancelled: true } }
  }
  if (receipt.schema === 'studio-native-action-receipt/v1') {
    return { ...base, status: 'succeeded', output: structuredClone(receipt.output) }
  }
  if (
    receipt.schema === 'studio-native-failure-receipt/v1'
    && receipt.terminal_status === 'completed'
    && TERMINAL_VALIDATION_FAILURES.has(receipt.error_code)
  ) {
    return {
      ...base,
      status: 'succeeded',
      output: Object.hasOwn(receipt, 'output')
        ? structuredClone(receipt.output)
        : null,
    }
  }
  return {
    ...base,
    status: 'failed',
    output: null,
    error: receipt.error_code || 'native_terminal_failed',
  }
}

const TERMINAL_VALIDATION_FAILURES = new Set([
  'output_schema_mismatch',
  'structured_output_invalid',
  'structured_output_missing',
])

export function validateNativeTerminalReceipt(action, receipt) {
  if (receipt.schema === 'studio-native-action-receipt/v1') {
    if (
      action.kind === 'interrupt'
      || receipt.terminal_status !== 'completed'
      || Object.hasOwn(receipt, 'error_code')
      || !Object.hasOwn(receipt, 'output')
    ) {
      throw new PersistentBrokerError(
        'native_receipt_invalid',
        'successful native receipt has an invalid terminal contract',
      )
    }
    return
  }
  if (receipt.schema === 'studio-native-failure-receipt/v1') {
    const validationFailure = (
      receipt.terminal_status === 'completed'
      && TERMINAL_VALIDATION_FAILURES.has(receipt.error_code)
    )
    const hostFailure = (
      ['failed', 'interrupted', 'cancelled'].includes(receipt.terminal_status)
      && receipt.error_code === 'turn_not_completed'
    )
    if (!validationFailure && !hostFailure) {
      throw new PersistentBrokerError(
        'native_receipt_invalid',
        'failure receipt has an unrecognized status/error contract',
      )
    }
    return
  }
  if (receipt.schema === 'studio-native-interrupt-receipt/v1') {
    if (action.kind !== 'interrupt' || receipt.terminal_status !== 'interrupted') {
      throw new PersistentBrokerError(
        'native_receipt_invalid',
        'interrupt receipt does not match an interrupt action',
      )
    }
    return
  }
  if (
    receipt.schema !== 'studio-native-idle-cancel-receipt/v1'
    || action.kind !== 'interrupt'
    || receipt.terminal_status !== 'already_terminal'
    || receipt.output?.cancelled !== true
  ) {
    throw new PersistentBrokerError(
      'native_receipt_invalid',
      'native receipt schema or terminal status is not allowed',
    )
  }
}

export class PersistentBrainstormStore {
  constructor(root) {
    if (!isAbsolute(root)) {
      throw new PersistentBrokerError('state_root_invalid', 'runtime state root must be absolute')
    }
    this.root = resolve(root)
  }

  async initialize() {
    await validateRootComponents(this.root, true)
    await mkdir(this.root, { recursive: true, mode: 0o700 })
    await validateRootComponents(this.root, false)
    let canonicalRoot
    try {
      canonicalRoot = await realpath(this.root)
    } catch {
      throw new PersistentBrokerError('state_root_invalid', 'runtime state root cannot be canonicalized')
    }
    if (canonicalRoot !== this.root) {
      throw new PersistentBrokerError('state_root_invalid', 'runtime state root must use its canonical real path')
    }
    await chmod(this.root, 0o700)
  }

  paths(runId) {
    const key = fileKey(runId)
    return {
      state: join(this.root, `${key}.json`),
      dispatch: join(this.root, `${key}.dispatch.json`),
      lock: join(this.root, `${key}.lock`),
    }
  }

  async #exclusiveCreate(path, value, duplicateCode) {
    let handle
    try {
      handle = await open(path, 'wx', 0o600)
      await handle.writeFile(serialized(value), 'utf8')
      await handle.sync()
    } catch (error) {
      if (error.code === 'EEXIST') {
        throw new PersistentBrokerError(duplicateCode, 'run_id already exists in runtime-owned state')
      }
      throw error
    } finally {
      await handle?.close()
    }
  }

  async create(input) {
    await this.initialize()
    const state = createPersistentBrainstorm(input)
    const paths = this.paths(state.run_id)
    await this.#exclusiveCreate(paths.state, state, 'duplicate_run')
    if (state.admission === 'production') {
      try {
        await this.#exclusiveCreate(paths.dispatch, newJournal(state), 'duplicate_dispatch_journal')
      } catch (error) {
        await rm(paths.state, { force: true })
        throw error
      }
    }
    return this.project(state)
  }

  async read(runId) {
    await this.initialize()
    const state = await readRegularJson(this.paths(runId).state)
    if (state.run_id !== runId) {
      throw new PersistentBrokerError('state_tampered', 'runtime-owned state failed identity/digest validation')
    }
    validatePersistentState(state)
    return state
  }

  async readDispatch(runId) {
    await this.initialize()
    return validateJournal(
      await readRegularJson(this.paths(runId).dispatch, 'dispatch_journal'),
      runId,
    )
  }

  lockPayload() {
    const pid = globalThis.process?.pid
    if (!Number.isInteger(pid) || pid < 1) {
      throw new PersistentBrokerError('lock_owner_unavailable', 'runtime process id is unavailable')
    }
    return `${pid}:${randomBytes(8).toString('hex')}\n`
  }

  async initializeLock(handle) {
    await handle.writeFile(this.lockPayload(), 'utf8')
    await handle.sync()
  }

  async acquire(runId) {
    const { lock } = this.paths(runId)
    let handle
    try {
      handle = await open(lock, 'wx', 0o600)
      await this.initializeLock(handle)
      return { handle, path: lock }
    } catch (error) {
      if (handle) {
        await handle.close().catch(() => {})
        await rm(lock, { force: true }).catch(() => {})
      }
      if (error.code === 'EEXIST') {
        throw new PersistentBrokerError('state_busy', 'another transition owns the run lock')
      }
      throw error
    }
  }

  async #commitPath(target, value) {
    const temp = `${target}.${process.pid}.${randomBytes(8).toString('hex')}.tmp`
    let handle
    try {
      handle = await open(temp, 'wx', 0o600)
      await handle.writeFile(serialized(value), 'utf8')
      await handle.sync()
      await handle.close()
      handle = null
      await rename(temp, target)
    } finally {
      await handle?.close()
      await rm(temp, { force: true })
    }
  }

  async commit(runId, state) {
    await this.#commitPath(this.paths(runId).state, state)
  }

  async commitDispatch(runId, journal) {
    validateJournal(journal, runId)
    await this.#commitPath(this.paths(runId).dispatch, journal)
  }

  async #withLock(runId, operation) {
    await this.initialize()
    const lock = await this.acquire(runId)
    try {
      return await operation()
    } finally {
      await lock.handle.close()
      await rm(lock.path, { force: true })
    }
  }

  #assertStateFence(state, revision, stateDigest) {
    if (state.state_revision !== revision || state.state_digest !== stateDigest) {
      throw new PersistentBrokerError('stale_state', 'expected state revision/digest does not match runtime-owned state')
    }
  }

  #entryForPending(state, journal, actionId) {
    const action = state.pending?.actions.find(candidate => candidate.action_id === actionId)
    const entry = journal.entries.find(candidate => candidate.action_id === actionId)
    if (!action || !entry) {
      throw new PersistentBrokerError('dispatch_action_invalid', 'action is not in the current canonical barrier')
    }
    return { action, entry }
  }

  async recordRequestSent({
    run_id: runId,
    expected_state_revision: revision,
    expected_state_digest: stateDigest,
    action_id: actionId,
  }) {
    return this.#withLock(runId, async () => {
      let state = await this.read(runId)
      this.#assertStateFence(state, revision, stateDigest)
      if (state.admission !== 'production') {
        throw new PersistentBrokerError('production_dispatch_required', 'dispatch journal is Production-only')
      }
      const journal = await this.readDispatch(runId)
      const { entry } = this.#entryForPending(state, journal, actionId)
      if (entry.stage !== 'scheduled') {
        throw new PersistentBrokerError('dispatch_stage_invalid', 'request_sent requires scheduled')
      }
      if (!state.native_started) {
        state = markPersistentNativeStarted(state)
        await this.commit(runId, state)
      }
      entry.stage = 'request_sent'
      journal.dispatch_started = true
      syncJournal(journal, state)
      advanceJournal(journal)
      await this.commitDispatch(runId, journal)
      return structuredClone(entry)
    })
  }

  async recordResponseReceived({
    run_id: runId,
    expected_state_revision: revision,
    expected_state_digest: stateDigest,
    action_id: actionId,
    binding,
  }) {
    return this.#withLock(runId, async () => {
      let state = await this.read(runId)
      this.#assertStateFence(state, revision, stateDigest)
      if (state.admission !== 'production' || !isAdapterOwnedTurnBinding(binding)) {
        throw new PersistentBrokerError(
          'native_binding_required',
          'response_received requires an adapter-owned Production turn binding',
        )
      }
      const journal = await this.readDispatch(runId)
      const { action, entry } = this.#entryForPending(state, journal, actionId)
      if (entry.stage !== 'request_sent') {
        throw new PersistentBrokerError('dispatch_stage_invalid', 'response_received requires request_sent')
      }
      if (
        !binding.action_ref
        || !binding.actor_ref
        || !binding.host_thread_id
        || !binding.host_turn_id
      ) {
        throw new PersistentBrokerError('native_binding_invalid', 'native binding is incomplete')
      }
      const actorEntries = journal.entries.filter(candidate => (
        candidate.actor_id === action.actor_id && candidate.binding
      ))
      const otherEntries = journal.entries.filter(candidate => (
        candidate.actor_id !== action.actor_id && candidate.binding
      ))
      if (
        actorEntries.some(candidate => (
          candidate.binding.host_thread_id !== binding.host_thread_id
          || candidate.binding.actor_ref !== binding.actor_ref
        ))
        || otherEntries.some(candidate => candidate.binding.host_thread_id === binding.host_thread_id)
        || journal.entries.some(candidate => candidate.binding?.host_turn_id === binding.host_turn_id)
        || (action.kind === 'spawn' && action.host_handle !== null)
        || (action.kind !== 'spawn' && action.host_handle !== binding.host_thread_id)
      ) {
        throw new PersistentBrokerError(
          'native_lineage_invalid',
          'native binding aliases or changes canonical actor/thread lineage',
        )
      }
      entry.binding = bindingProjection(binding)
      entry.stage = 'response_received'
      journal.native_response_received = true
      advanceJournal(journal)
      await this.commitDispatch(runId, journal)

      if (!state.native_started) {
        state = markPersistentNativeStarted(state)
        await this.commit(runId, state)
        syncJournal(journal, state)
        advanceJournal(journal)
        await this.commitDispatch(runId, journal)
      }
      return {
        ...this.project(state),
        dispatch: structuredClone(entry),
      }
    })
  }

  async recordTerminalEvent({
    run_id: runId,
    expected_state_revision: revision,
    expected_state_digest: stateDigest,
    action_id: actionId,
    receipt,
  }) {
    return this.#withLock(runId, async () => {
      const state = await this.read(runId)
      this.#assertStateFence(state, revision, stateDigest)
      if (state.admission !== 'production' || !isAdapterOwnedNativeReceipt(receipt)) {
        throw new PersistentBrokerError(
          'native_receipt_required',
          'terminal_event requires an adapter-owned Production receipt',
        )
      }
      const journal = await this.readDispatch(runId)
      const { action, entry } = this.#entryForPending(state, journal, actionId)
      const idleCancellation = receipt.schema === 'studio-native-idle-cancel-receipt/v1'
      validateNativeTerminalReceipt(action, receipt)
      if (
        receipt.config_digest !== state.capability.config_digest
        || receipt.environment_digest !== state.capability.environment_digest
      ) {
        throw new PersistentBrokerError(
          'native_receipt_invalid',
          'receipt differs from the admitted capability environment',
        )
      }
      if (
        (idleCancellation && (action.kind !== 'interrupt' || entry.stage !== 'request_sent'))
        || (!idleCancellation && entry.stage !== 'response_received')
      ) {
        throw new PersistentBrokerError('dispatch_stage_invalid', 'terminal_event follows the wrong journal stage')
      }
      if (idleCancellation) {
        const priorBinding = journal.entries.find(candidate => (
          candidate.actor_id === action.actor_id
          && candidate.action_id !== action.action_id
          && candidate.binding
        ))?.binding
        if (
          !priorBinding
          || receipt.host_thread_id !== action.host_handle
          || receipt.host_thread_id !== priorBinding.host_thread_id
          || receipt.actor_ref !== priorBinding.actor_ref
          || receipt.host_turn_id !== null
          || receipt.output?.cancelled !== true
        ) {
          throw new PersistentBrokerError('native_receipt_invalid', 'idle cancellation receipt is inconsistent')
        }
        entry.binding = {
          schema: 'studio-native-idle-binding/v1',
          action_ref: receipt.action_ref,
          actor_ref: receipt.actor_ref,
          host_thread_id: receipt.host_thread_id,
          host_turn_id: null,
          environment_digest: receipt.environment_digest,
          config_digest: receipt.config_digest,
        }
      } else if (
        receipt.action_ref !== entry.binding?.action_ref
        || receipt.actor_ref !== entry.binding?.actor_ref
        || receipt.host_thread_id !== entry.binding?.host_thread_id
        || receipt.host_turn_id !== entry.binding?.host_turn_id
        || receipt.config_digest !== entry.binding?.config_digest
        || receipt.environment_digest !== entry.binding?.environment_digest
        || receipt.binary_digest !== state.capability.binary_digest
        || receipt.schema_digest !== state.capability.schema_digest
      ) {
        throw new PersistentBrokerError('native_receipt_invalid', 'receipt differs from the admitted turn binding')
      }
      entry.receipt = receiptProjection(receipt)
      entry.result = nativeResult(action, receipt)
      entry.stage = 'terminal_event'
      advanceJournal(journal)
      await this.commitDispatch(runId, journal)
      return structuredClone(entry)
    })
  }

  async applyProductionBarrier({
    run_id: runId,
    expected_state_revision: revision,
    expected_state_digest: stateDigest,
  }) {
    return this.#withLock(runId, async () => {
      const state = await this.read(runId)
      this.#assertStateFence(state, revision, stateDigest)
      if (state.admission !== 'production' || !state.native_started || !state.pending) {
        throw new PersistentBrokerError('production_dispatch_required', 'no native Production barrier is pending')
      }
      const journal = await this.readDispatch(runId)
      const entries = state.pending.action_ids.map(actionId => (
        journal.entries.find(entry => entry.action_id === actionId)
      ))
      if (entries.some(entry => entry?.stage !== 'terminal_event')) {
        throw new PersistentBrokerError('barrier_incomplete', 'every native action needs a terminal_event')
      }
      const barrier = {
        schema: BARRIER_RESULT_SCHEMA,
        run_id: state.run_id,
        state_revision: state.state_revision,
        state_digest: state.state_digest,
        barrier_id: state.pending.barrier_id,
        results: entries.map(entry => structuredClone(entry.result)),
      }
      const next = applyPersistentBarrier(state, barrier)
      await this.commit(runId, next)
      for (const entry of entries) entry.applied_state_revision = next.state_revision
      syncJournal(journal, next)
      advanceJournal(journal)
      await this.commitDispatch(runId, journal)
      return this.project(next)
    })
  }

  async reconcileDispatch(runId) {
    return this.#withLock(runId, async () => {
      let state = await this.read(runId)
      if (state.admission !== 'production') return this.project(state)
      let journal
      try {
        journal = await this.readDispatch(runId)
      } catch (error) {
        if (error.code !== 'dispatch_journal_store_invalid' || state.native_started) throw error
        journal = newJournal(state)
        await this.#exclusiveCreate(
          this.paths(runId).dispatch,
          journal,
          'duplicate_dispatch_journal',
        )
      }
      const hasNativeResponse = journal.entries.some(entry => (
        JOURNAL_STAGES.indexOf(entry.stage) >= JOURNAL_STAGES.indexOf('response_received')
      ))
      if (hasNativeResponse && !state.native_started) {
        state = markPersistentNativeStarted(state)
        await this.commit(runId, state)
      }
      syncJournal(journal, state)
      advanceJournal(journal)
      await this.commitDispatch(runId, journal)
      return {
        ...this.project(state),
        dispatch_status: journal.status,
        dispatch_started: journal.dispatch_started,
        native_response_received: journal.native_response_received,
      }
    })
  }

  async markDispatchRecoveryRequired(runId, details = {}) {
    return this.#withLock(runId, async () => {
      const state = await this.read(runId)
      if (state.admission !== 'production') {
        throw new PersistentBrokerError('production_dispatch_required', 'recovery journal is Production-only')
      }
      const journal = await this.readDispatch(runId)
      journal.status = 'recovery_required'
      journal.recovery = {
        at: new Date().toISOString(),
        code: String(details.code || 'native_recovery_required'),
        action_id: details.action_id ? String(details.action_id) : null,
      }
      syncJournal(journal, state)
      advanceJournal(journal)
      await this.commitDispatch(runId, journal)
      return structuredClone(journal.recovery)
    })
  }

  async tombstoneDispatch(runId, { cleanupReceipts } = {}) {
    return this.#withLock(runId, async () => {
      const state = await this.read(runId)
      if (state.admission !== 'production' || state.pending !== null) {
        throw new PersistentBrokerError('dispatch_tombstone_invalid', 'only a terminal Production run may tombstone')
      }
      const journal = await this.readDispatch(runId)
      const expectedBindings = new Map()
      for (const entry of journal.entries) {
        if (entry.binding) expectedBindings.set(entry.binding.actor_ref, entry.binding)
      }
      const expectedActorRefs = new Set([
        ...state.participants,
        state.critic,
        state.summarizer,
      ].map(actor => rawDigest(`actor:${actor.actor_id}`)))
      if (
        !Array.isArray(cleanupReceipts)
        || cleanupReceipts.length !== expectedActorRefs.size
        || new Set(cleanupReceipts.map(receipt => receipt?.host_thread_id)).size
          !== cleanupReceipts.length
        || new Set(cleanupReceipts.map(receipt => receipt?.actor_ref)).size
          !== cleanupReceipts.length
        || new Set(cleanupReceipts.map(receipt => receipt?.receipt_digest)).size
          !== cleanupReceipts.length
        || cleanupReceipts.some(receipt => {
          const binding = expectedBindings.get(receipt?.actor_ref)
          return (
            !expectedActorRefs.has(receipt?.actor_ref)
            || !isAdapterOwnedNativeReceipt(receipt)
            || receipt.schema !== 'studio-native-cleanup-receipt/v1'
            || (binding && receipt.host_thread_id !== binding.host_thread_id)
            || receipt.config_digest !== state.capability.config_digest
            || receipt.environment_digest !== state.capability.environment_digest
            || receipt.deleted !== true
            || receipt.deletion_notified !== true
            || receipt.rollout_absent !== true
            || !/^sha256:[0-9a-f]{64}$/.test(receipt.rollout_path_ref || '')
            || !/^sha256:[0-9a-f]{64}$/.test(receipt.receipt_digest || '')
          )
        })
      ) {
        throw new PersistentBrokerError(
          'dispatch_tombstone_invalid',
          'terminal Production cleanup receipts are incomplete or not adapter-owned',
        )
      }
      journal.status = 'tombstoned'
      journal.tombstone = {
        at: new Date().toISOString(),
        cleanup: 'complete',
        cleanup_receipts: cleanupReceipts.map(receipt => ({
          schema: receipt.schema,
          actor_ref: receipt.actor_ref,
          host_thread_id: receipt.host_thread_id,
          deleted: receipt.deleted,
          deletion_notified: receipt.deletion_notified,
          rollout_absent: receipt.rollout_absent,
          rollout_path_ref: receipt.rollout_path_ref,
          config_digest: receipt.config_digest,
          environment_digest: receipt.environment_digest,
          receipt_digest: receipt.receipt_digest,
        })),
      }
      syncJournal(journal, state)
      advanceJournal(journal)
      await this.commitDispatch(runId, journal)
      return structuredClone(journal.tombstone)
    })
  }

  async apply({
    run_id: runId,
    expected_state_revision: revision,
    expected_state_digest: stateDigest,
    receipt,
  }) {
    return this.#withLock(runId, async () => {
      const current = await this.read(runId)
      this.#assertStateFence(current, revision, stateDigest)
      if (current.admission === 'production') {
        throw new PersistentBrokerError(
          'native_receipt_required',
          'Production barriers are assembled only from the runtime-owned native dispatch journal',
        )
      }
      const next = applyPersistentBarrier(current, receipt)
      await this.commit(runId, next)
      return this.project(next)
    })
  }

  project(state) {
    return {
      state_ref: stateRef(state),
      envelope: persistentBrainstormEnvelope(state),
    }
  }
}
