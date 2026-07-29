import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import {
  chmod, lstat, mkdtemp, mkdir, readFile, realpath, rm, stat, writeFile,
} from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  NativeAdapterError,
  createPersistentNativeAppServer,
  isAdapterOwnedPersistentCapability,
} from '../scripts/persistent_native_app_server.mjs'
import {
  createPersistentNativeAppServerForTest,
  isTestAdapterOwnedPersistentCapability,
} from './fixtures/persistent_native_app_server_test_adapter.mjs'
import * as runtimeExports from '../scripts/persistent_native_app_server_runtime.mjs'
import * as testAdapterExports from './fixtures/persistent_native_app_server_test_adapter.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = await realpath(resolve(HERE, '..', '..', '..'))
const FAKE = join(HERE, 'fixtures', 'fake_persistent_app_server.mjs')
const VERSION = 'codex-cli 0.146.0-alpha.3.1'
const SCHEMA_BYTES = '{"protocol":"fake-codex-app-server-v2","version":1}\n'
const OUTPUT_SCHEMA = Object.freeze({
  type: 'object',
  additionalProperties: false,
  required: ['answer'],
  properties: {
    answer: { type: 'string' },
  },
})

function sha256(value) {
  return `sha256:${createHash('sha256').update(value).digest('hex')}`
}

function resolvedProfile(actorId, overrides = {}) {
  return Object.freeze({
    schema: 'studio-native-resolved-agent-profile/v1',
    actor_id: actorId,
    phase: 'Diverge',
    step: 'diverge',
    role_id: actorId,
    agent_id: actorId,
    model: null,
    effort: null,
    policy_digest: sha256('test-policy'),
    ...overrides,
  })
}

await chmod(FAKE, 0o755)
const BINARY_DIGEST = sha256(await readFile(FAKE))
const SCHEMA_DIGEST = sha256('{"protocol":"fake-codex-app-server-v2","version":1}')

async function harness(t, {
  scenario = 'success',
  now = Date.now,
  freshnessMs = 60_000,
  runtimeEqualsSource = false,
} = {}) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'studio-native-app-server-test-')))
  const sourceHome = join(root, 'source-home')
  const runtimeRoot = runtimeEqualsSource ? sourceHome : join(root, 'runtime')
  await mkdir(sourceHome, { mode: 0o700 })
  if (!runtimeEqualsSource) await mkdir(runtimeRoot, { mode: 0o700 })
  await writeFile(join(sourceHome, 'auth.json'), '{"token":"fixture-only"}\n', { mode: 0o600 })
  const callLog = join(root, 'calls.jsonl')
  const denialLog = join(root, 'denial.json')
  const envLog = join(root, 'environment.json')
  const adapter = createPersistentNativeAppServerForTest({
    binary: FAKE,
    sourceCodexHome: sourceHome,
    runtimeRoot,
    cwd: REPO,
    allowedVersions: [VERSION],
    allowedBinaryDigests: [BINARY_DIGEST],
    allowedSchemaDigests: [SCHEMA_DIGEST],
    freshnessMs,
    requestTimeoutMs: 500,
    turnTimeoutMs: 300,
    interruptTimeoutMs: 50,
    now,
    processEnvOverrides: {
      FAKE_APP_SERVER_SCENARIO: scenario,
      FAKE_APP_SERVER_CALL_LOG: callLog,
      FAKE_APP_SERVER_DENIAL_LOG: denialLog,
      FAKE_APP_SERVER_ENV_LOG: envLog,
    },
  })
  t.after(async () => {
    await adapter.close()
    await rm(root, { recursive: true, force: true })
  })
  return {
    adapter, sourceHome, runtimeRoot, callLog, denialLog, envLog, root,
  }
}

async function admittedRole(t, options = {}, actorId = 'participant:a') {
  const context = await harness(t, options)
  const capability = await context.adapter.admit()
  const role = await context.adapter.startRole(capability, { actorId })
  return { ...context, capability, role }
}

async function readJsonEventually(path) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      return JSON.parse(await readFile(path, 'utf8'))
    } catch {
      await new Promise(resolveWait => setTimeout(resolveWait, 10))
    }
  }
  return JSON.parse(await readFile(path, 'utf8'))
}

async function readJsonLinesEventually(path, predicate) {
  let values = []
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      values = (await readFile(path, 'utf8')).trim().split('\n').filter(Boolean).map(JSON.parse)
      if (predicate(values)) return values
    } catch {
      // The fake host may still be flushing its append-only audit record.
    }
    await new Promise(resolveWait => setTimeout(resolveWait, 10))
  }
  return values
}

test('success mints adapter-owned capability and exact host receipt', async t => {
  const {
    adapter, capability, role, runtimeRoot, sourceHome, envLog,
  } = await admittedRole(t)
  const authSnapshot = join(runtimeRoot, 'codex-home', 'auth.json')
  assert.equal(await lstat(authSnapshot).catch(() => null), null)
  await writeFile(join(sourceHome, 'auth.json'), '{"token":"rotated"}\n', { mode: 0o600 })
  assert.equal(await lstat(authSnapshot).catch(() => null), null)
  const inheritedEnvironment = JSON.parse(await readFile(envLog, 'utf8'))
  for (const forbidden of [
    'HOME', 'SHELL', 'TERM', 'HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY',
    'NO_PROXY', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
  ]) {
    assert.equal(inheritedEnvironment.includes(forbidden), false)
  }
  await assert.rejects(
    adapter.startRole({ ...capability }, { actorId: 'forged' }),
    error => error instanceof NativeAdapterError && error.code === 'capability_not_adapter_owned',
  )
  const receipt = await adapter.runTurn(capability, {
    role,
    actionId: 'a-1',
    prompt: 'return structured output',
    outputSchema: OUTPUT_SCHEMA,
  })
  assert.equal(receipt.schema, 'studio-native-action-receipt/v1')
  assert.equal(receipt.terminal_status, 'completed')
  assert.match(receipt.host_thread_id, /^[0-9a-f-]{36}$/)
  assert.match(receipt.host_turn_id, /^[0-9a-f-]{36}$/)
  assert.equal(adapter.verifyReceipt(capability, receipt), true)
  assert.equal(adapter.verifyReceipt(capability, structuredClone(receipt)), false)
  assert.ok(Object.isFrozen(capability))
  assert.ok(Object.isFrozen(receipt))
})

test('explicit controller policy is echoed by thread start and applied to every native turn', async t => {
  const { adapter, callLog } = await harness(t)
  const capability = await adapter.admit()
  const actorId = 'participant:policy'
  const diverge = resolvedProfile(actorId, {
    model: 'policy-model',
    effort: 'high',
  })
  const role = await adapter.startRole(capability, {
    actorId,
    profile: diverge,
  })
  const receipt = await adapter.runTurn(capability, {
    role,
    actionId: 'policy-a-1',
    prompt: 'return structured output',
    outputSchema: OUTPUT_SCHEMA,
    profile: diverge,
  })
  assert.equal(receipt.resolved_profile.model, 'policy-model')
  assert.equal(receipt.resolved_profile.effort, 'high')
  assert.deepEqual(receipt.effective_profile, {
    model: 'policy-model',
    effort: 'high',
  })
  assert.match(receipt.policy_profile_digest, /^sha256:[0-9a-f]{64}$/)
  const calls = await readJsonLinesEventually(
    callLog,
    values => values.some(value => (
      value.method === 'turn/start' && value.params?.clientUserMessageId?.startsWith('studio-')
    )),
  )
  const roleStart = calls.find(value => (
    value.method === 'thread/start'
    && value.params?.serviceName === 'studio-persistent-native'
    && value.params?.model === 'policy-model'
  ))
  assert.equal(roleStart.params.allowProviderModelFallback, false)
  const turnStart = calls.find(value => (
    value.method === 'turn/start'
    && value.params?.clientUserMessageId?.startsWith('studio-')
  ))
  assert.equal(turnStart.params.model, 'policy-model')
  assert.equal(turnStart.params.effort, 'high')
})

test('role admission rejects a host model echo that differs from resolved policy', async t => {
  const { adapter } = await harness(t, { scenario: 'model-echo-mismatch' })
  const capability = await adapter.admit()
  const actorId = 'participant:model-mismatch'
  await assert.rejects(
    adapter.startRole(capability, {
      actorId,
      profile: resolvedProfile(actorId, { model: 'policy-model' }),
    }),
    error => error instanceof NativeAdapterError && error.code === 'thread_policy_invalid',
  )
})

test('test authority cannot mint a Production adapter capability', async t => {
  const { adapter } = await harness(t)
  const capability = await adapter.admit()
  assert.equal(isTestAdapterOwnedPersistentCapability(capability), true)
  assert.equal(isAdapterOwnedPersistentCapability(capability), false)
  assert.equal(capability.tool_inventory_capture.captured, true)
  assert.equal(
    capability.tool_inventory_capture.evidence_class,
    'deterministic-test-fixture',
  )
  assert.equal(capability.tool_inventory_capture.provider_scope, 'fake-app-server-only')
  assert.deepEqual(
    capability.inventory_evidence.enabled_local_execution_features,
    [],
  )
  assert.equal(capability.tool_inventory_capture.tool_count, 0)
  assert.deepEqual(capability.tool_inventory_capture.tools, [])
  assert.equal(capability.model_tool_surface, 'context-only-empty')
  assert.equal(capability.repository_mutation_allowed, false)
  assert.equal(capability.agent_tool_network_access, false)
  assert.equal(capability.sandbox_network_access, false)
  assert.equal(capability.provider_model_transport, 'required-outside-agent-tool-sandbox')
  assert.equal(capability.auth_snapshot_hygiene_only, true)
  assert.equal(capability.credential_confidentiality_guaranteed, false)
  assert.equal(capability.same_user_filesystem_read_confidentiality, 'out-of-scope')
  assert.equal('outbound_model_tools' in capability.inventory_evidence, false)
  assert.ok(Object.isFrozen(capability.tool_inventory_capture))
})

test('test-runner environment and fixture imports cannot mint Production authority', async t => {
  assert.equal(
    Object.hasOwn(runtimeExports, 'createPersistentNativeAppServerForProductionContractTest'),
    false,
  )
  assert.equal(
    Object.hasOwn(testAdapterExports, 'createPersistentNativeAppServerForProductionContractTest'),
    false,
  )
  const { adapter } = await harness(t)
  const capability = await adapter.admit()
  assert.equal(isTestAdapterOwnedPersistentCapability(capability), true)
  assert.equal(isAdapterOwnedPersistentCapability(capability), false)
})

test('capability freshness is enforced after admission', async t => {
  let clock = 1_000
  const { adapter } = await harness(t, { now: () => clock, freshnessMs: 10 })
  const capability = await adapter.admit()
  clock = 1_010
  await assert.rejects(
    adapter.startRole(capability, { actorId: 'stale' }),
    error => error instanceof NativeAdapterError && error.code === 'capability_stale',
  )
})

test('freshly admitted workflow lease survives TTL through turns, resume, and cleanup', async t => {
  let clock = 2_000
  const { adapter } = await harness(t, { now: () => clock, freshnessMs: 10 })
  const capability = await adapter.admit()
  const role = await adapter.startRole(capability, { actorId: 'long-major-workflow' })
  clock = 2_100
  const first = await adapter.runTurn(capability, {
    role,
    actionId: 'long-1',
    prompt: 'return structured output',
    outputSchema: OUTPUT_SCHEMA,
  })
  assert.equal(first.terminal_status, 'completed')
  await adapter.resumeRole(capability, role)
  const second = await adapter.runTurn(capability, {
    role,
    actionId: 'long-2',
    prompt: 'return another structured output',
    outputSchema: OUTPUT_SCHEMA,
  })
  assert.equal(second.terminal_status, 'completed')
  const cleanup = await adapter.cleanupRole(capability, role)
  assert.equal(cleanup.deleted, true)
  assert.equal(adapter.verifyReceipt(capability, cleanup), true)
  await assert.rejects(
    adapter.startRole(capability, { actorId: 'new-workflow-after-lease-close' }),
    error => error instanceof NativeAdapterError && error.code === 'workflow_lease_closed',
  )
})

test('version and schema drift fail admission before a role can start', async t => {
  const version = await harness(t, { scenario: 'success' })
  version.adapter = createPersistentNativeAppServerForTest({
    binary: FAKE,
    sourceCodexHome: version.sourceHome,
    runtimeRoot: version.runtimeRoot,
    cwd: REPO,
    allowedVersions: ['codex-cli impossible'],
    allowedBinaryDigests: [BINARY_DIGEST],
    allowedSchemaDigests: [SCHEMA_DIGEST],
    processEnvOverrides: { FAKE_APP_SERVER_SCENARIO: 'success' },
  })
  await assert.rejects(
    version.adapter.admit(),
    error => {
      assert.ok(error instanceof NativeAdapterError)
      assert.equal(error.code, 'capability_allowlist_mismatch')
      assert.deepEqual(error.details.allowlist_diagnostics.version, {
        expected: ['codex-cli impossible'],
        actual: VERSION,
        matched: false,
      })
      assert.equal(error.details.allowlist_diagnostics.binary_digest.matched, true)
      assert.equal(error.details.allowlist_diagnostics.schema_digest.matched, true)
      return true
    },
  )

  const schema = await harness(t, { scenario: 'schema-drift' })
  await assert.rejects(
    schema.adapter.admit(),
    error => (
      error instanceof NativeAdapterError
      && error.code === 'capability_allowlist_mismatch'
      && error.details.allowlist_diagnostics.version.matched === true
      && error.details.allowlist_diagnostics.binary_digest.matched === true
      && error.details.allowlist_diagnostics.schema_digest.matched === false
    ),
  )
})

test('shared CODEX_HOME is rejected without starting app-server', async t => {
  const { adapter } = await harness(t, { runtimeEqualsSource: true })
  await assert.rejects(
    adapter.admit(),
    error => error instanceof NativeAdapterError && error.code === 'shared_codex_home_forbidden',
  )
  const existing = await harness(t)
  await mkdir(join(existing.runtimeRoot, 'codex-home'), { mode: 0o700 })
  await assert.rejects(
    existing.adapter.admit(),
    error => error instanceof NativeAdapterError && error.code === 'isolated_home_exists',
  )
})

test('server request is denied and poisons the active turn', async t => {
  const {
    adapter, capability, role, denialLog, callLog,
  } = await admittedRole(t, { scenario: 'server-request' })
  const turn = await adapter.beginTurn(capability, {
    role,
    actionId: 'server-request',
    prompt: 'must not ask for approval',
    outputSchema: OUTPUT_SCHEMA,
  })
  await assert.rejects(
    adapter.waitTurn(capability, turn),
    error => error instanceof NativeAdapterError && error.code === 'recovery_required',
  )
  const denial = await readJsonEventually(denialLog)
  assert.equal(denial.id, 'server-request-1')
  assert.equal(denial.result.decision, 'decline')
  const calls = await readJsonLinesEventually(
    callLog,
    values => values.some(call => call.method === 'turn/interrupt'),
  )
  assert.ok(calls.some(call => call.method === 'turn/interrupt'))
})

test('different actors receive different host threads', async t => {
  const { adapter } = await harness(t)
  const capability = await adapter.admit()
  const roleA = await adapter.startRole(capability, { actorId: 'participant:a' })
  const roleB = await adapter.startRole(capability, { actorId: 'participant:b' })
  const [a, b] = await Promise.all([
    adapter.runTurn(capability, {
      role: roleA,
      actionId: 'a',
      prompt: 'a',
      outputSchema: OUTPUT_SCHEMA,
    }),
    adapter.runTurn(capability, {
      role: roleB,
      actionId: 'b',
      prompt: 'b',
      outputSchema: OUTPUT_SCHEMA,
    }),
  ])
  assert.notEqual(a.host_thread_id, b.host_thread_id)
})

test('concurrent startRole rejects a duplicate actor reservation before host allocation', async t => {
  const { adapter } = await harness(t)
  const capability = await adapter.admit()
  const outcomes = await Promise.allSettled([
    adapter.startRole(capability, { actorId: 'participant:same' }),
    adapter.startRole(capability, { actorId: 'participant:same' }),
  ])
  assert.equal(outcomes.filter(item => item.status === 'fulfilled').length, 1)
  const [rejected] = outcomes.filter(item => item.status === 'rejected')
  assert.equal(rejected.reason.code, 'actor_already_bound')
})

test('same-role beginTurn uses an atomic reservation across the host await', async t => {
  const {
    adapter, capability, role,
  } = await admittedRole(t, { scenario: 'interrupt' })
  const outcomes = await Promise.allSettled([
    adapter.beginTurn(capability, {
      role,
      actionId: 'atomic-a',
      prompt: 'remain active',
      outputSchema: OUTPUT_SCHEMA,
    }),
    adapter.beginTurn(capability, {
      role,
      actionId: 'atomic-b',
      prompt: 'must be rejected before host allocation',
      outputSchema: OUTPUT_SCHEMA,
    }),
  ])
  assert.equal(outcomes.filter(item => item.status === 'fulfilled').length, 1)
  const [rejected] = outcomes.filter(item => item.status === 'rejected')
  assert.equal(rejected.reason.code, 'actor_turn_active')
  const [accepted] = outcomes.filter(item => item.status === 'fulfilled')
  await adapter.interruptTurn(capability, accepted.value)
})

test('same actor follow-up reuses the exact host thread', async t => {
  const {
    adapter, capability, role,
  } = await admittedRole(t)
  const first = await adapter.runTurn(capability, {
    role,
    actionId: 'first',
    prompt: 'first',
    outputSchema: OUTPUT_SCHEMA,
  })
  await adapter.resumeRole(capability, role)
  const second = await adapter.runTurn(capability, {
    role,
    actionId: 'second',
    prompt: 'second',
    outputSchema: OUTPUT_SCHEMA,
  })
  assert.equal(first.host_thread_id, second.host_thread_id)
  assert.notEqual(first.host_turn_id, second.host_turn_id)
})

test('idle cancellation is adapter-attested and active roles cannot be acknowledged idle', async t => {
  const {
    adapter, capability, role,
  } = await admittedRole(t, { scenario: 'interrupt' })
  const turn = await adapter.beginTurn(capability, {
    role,
    actionId: 'active-before-idle',
    prompt: 'remain active',
    outputSchema: OUTPUT_SCHEMA,
  })
  assert.throws(
    () => adapter.confirmRoleIdle(capability, role, { actionId: 'cancel-active' }),
    error => error instanceof NativeAdapterError && error.code === 'actor_busy',
  )
  await adapter.interruptTurn(capability, turn)
  const receipt = adapter.confirmRoleIdle(capability, role, { actionId: 'cancel-idle' })
  assert.equal(receipt.schema, 'studio-native-idle-cancel-receipt/v1')
  assert.equal(receipt.terminal_status, 'already_terminal')
  assert.deepEqual(receipt.output, { cancelled: true })
  assert.equal(adapter.verifyReceipt(capability, receipt), true)
})

test('host structured output must satisfy the exact schema', async t => {
  const {
    adapter, capability, role,
  } = await admittedRole(t, { scenario: 'schema-fail' })
  await assert.rejects(
    adapter.runTurn(capability, {
      role,
      actionId: 'schema-fail',
      prompt: 'bad schema',
      outputSchema: OUTPUT_SCHEMA,
    }),
    error => error instanceof NativeAdapterError && error.code === 'output_schema_mismatch',
  )
})

test('context-only terminal rejects commandExecution without minting a receipt', async t => {
  for (const scenario of ['command-item', 'failed-command-item']) {
    await t.test(scenario, async child => {
      const {
        adapter, capability, role,
      } = await admittedRole(child, { scenario })
      let rejected
      await assert.rejects(
        adapter.runTurn(capability, {
          role,
          actionId: `forbidden-${scenario}`,
          prompt: 'must remain context-only',
          outputSchema: OUTPUT_SCHEMA,
        }),
        error => {
          rejected = error
          return (
            error instanceof NativeAdapterError
            && error.code === 'recovery_required'
            && error.details.cause === 'forbidden_terminal_item'
            && error.details.receipt === undefined
          )
        },
      )
      assert.equal(adapter.verifyReceipt(capability, rejected.details.receipt), false)
    })
  }
})

test('interrupt requires the matching interrupted terminal event', async t => {
  const {
    adapter, capability, role,
  } = await admittedRole(t, { scenario: 'interrupt' })
  const turn = await adapter.beginTurn(capability, {
    role,
    actionId: 'interrupt',
    prompt: 'wait',
    outputSchema: OUTPUT_SCHEMA,
  })
  const receipt = await adapter.interruptTurn(capability, turn)
  assert.equal(receipt.terminal_status, 'interrupted')
})

test('unknown interrupt is recovery-required and cannot be retried as success', async t => {
  const {
    adapter, capability, role,
  } = await admittedRole(t, { scenario: 'interrupt-unknown' })
  const turn = await adapter.beginTurn(capability, {
    role,
    actionId: 'interrupt-unknown',
    prompt: 'wait',
    outputSchema: OUTPUT_SCHEMA,
  })
  await assert.rejects(
    adapter.interruptTurn(capability, turn),
    error => error instanceof NativeAdapterError && error.code === 'interrupt_unknown',
  )
  await assert.rejects(
    adapter.interruptTurn(capability, turn),
    error => error instanceof NativeAdapterError && error.code === 'interrupt_unknown',
  )
})

test('EOF before terminal completion enters recovery-required', async t => {
  const {
    adapter, capability, role,
  } = await admittedRole(t, { scenario: 'eof' })
  await assert.rejects(
    adapter.runTurn(capability, {
      role,
      actionId: 'eof',
      prompt: 'disconnect',
      outputSchema: OUTPUT_SCHEMA,
    }),
    error => error instanceof NativeAdapterError && error.code === 'recovery_required',
  )
})

test('late interrupted event cannot revive a timed-out turn', async t => {
  const {
    adapter, capability, role,
  } = await admittedRole(t, { scenario: 'late-interrupt' })
  const turn = await adapter.beginTurn(capability, {
    role,
    actionId: 'late',
    prompt: 'late terminal',
    outputSchema: OUTPUT_SCHEMA,
  })
  await assert.rejects(
    adapter.interruptTurn(capability, turn),
    error => error instanceof NativeAdapterError && error.code === 'interrupt_unknown',
  )
  await new Promise(resolveWait => setTimeout(resolveWait, 230))
  await assert.rejects(
    adapter.waitTurn(capability, turn),
    error => error instanceof NativeAdapterError
      && error.code === 'late_result'
      && adapter.inspectTurnLifecycle(capability, turn).late_result_tombstone === true,
  )
})

test('auth absence observations are adapter-owned, unique, and filesystem-backed', async t => {
  const { adapter } = await harness(t)
  const capability = await adapter.admit()
  const observation = await adapter.observeAuthSnapshotAbsence(capability, {
    checkpoint: 'before-role-start',
  })
  assert.equal(observation.evidence_class, 'trusted-local-observation')
  assert.equal(observation.absent, true)
  assert.match(observation.evidence_digest, /^sha256:[0-9a-f]{64}$/)
  await assert.rejects(
    adapter.observeAuthSnapshotAbsence(capability, { checkpoint: 'before-role-start' }),
    error => error.code === 'observation_checkpoint_invalid',
  )
})

test('fixed command/exec write probe records nonzero read-only denial and no file', async t => {
  const { adapter } = await harness(t)
  const capability = await adapter.admit()
  const target = join(REPO, 'studio-live-canary-write-probe-test.txt')
  assert.equal(await lstat(target).catch(() => null), null)
  const observation = await adapter.probeReadOnlyWriteDenial(capability, { target })
  assert.equal(observation.evidence_class, 'trusted-local-observation')
  assert.deepEqual(observation.command_argv, ['/usr/bin/touch', '--', target])
  assert.equal(observation.exit_code, 1)
  assert.equal(observation.denial_kind, 'eperm')
  assert.equal(observation.target_absent, true)
  assert.equal(observation.sandbox_network_access, false)
  assert.equal(await lstat(target).catch(() => null), null)
})

test('cleanup cleans terminals, deletes thread, and invalidates the role', async t => {
  const {
    adapter, capability, role, callLog, runtimeRoot,
  } = await admittedRole(t)
  const cleanup = await adapter.cleanupRole(capability, role)
  assert.equal(cleanup.deleted, true)
  assert.equal(cleanup.deletion_notified, true)
  assert.equal(cleanup.rollout_absent, true)
  assert.match(cleanup.rollout_path_ref, /^sha256:[0-9a-f]{64}$/)
  await assert.rejects(
    adapter.runTurn(capability, {
      role,
      actionId: 'after-cleanup',
      prompt: 'must fail',
      outputSchema: OUTPUT_SCHEMA,
    }),
    error => error instanceof NativeAdapterError && error.code === 'role_reference_invalid',
  )
  const calls = (await readFile(callLog, 'utf8'))
    .trim()
    .split('\n')
    .map(line => JSON.parse(line))
  const methods = calls.map(call => call.method)
  assert.ok(methods.includes('thread/backgroundTerminals/clean'))
  assert.ok(methods.includes('thread/backgroundTerminals/list'))
  assert.ok(methods.includes('thread/delete'))
  const starts = calls.filter(call => call.method === 'thread/start')
  assert.ok(starts.length >= 2)
  assert.equal(starts.every(call => call.params.ephemeral === false), true)
  assert.equal((await stat(join((await realpath(dirname(callLog))), 'source-home', 'auth.json'))).mode & 0o777, 0o600)
  await adapter.close()
  assert.equal(await lstat(join(runtimeRoot, 'codex-home')).catch(() => null), null)
})

test('unknown and inherited inventories fail admission', async t => {
  for (const scenario of [
    'unknown-capability',
    'startup-capability',
    'nonempty-inventory',
    'nonempty-skill',
    'nonempty-plugin',
    'nonempty-app',
    'nonempty-mcp',
    'inherited-capability',
    'unsafe-policy',
    'bad-delete-notification',
  ]) {
    await t.test(scenario, async child => {
      const { adapter } = await harness(child, { scenario })
      await assert.rejects(adapter.admit(), error => error instanceof NativeAdapterError)
    })
  }
})

test('unsafe process and raw thread RPC surfaces are not exposed', async t => {
  const { adapter, runtimeRoot } = await harness(t)
  for (const name of [
    'requestThread',
    'shellCommand',
    'spawn',
    'processSpawn',
    'commandExec',
    'threadShellCommand',
  ]) {
    assert.equal(adapter[name], undefined)
  }
  assert.throws(
    () => createPersistentNativeAppServer({ runtimeRoot, cwd: REPO, binary: FAKE }),
    error => error instanceof NativeAdapterError && error.code === 'adapter_config_forbidden',
  )
})
