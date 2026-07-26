// Deterministic contracts for the production Codex workflow runner.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { chmod, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  RunnerError,
  buildCodexArgs,
  executeWorkflow,
  normalizeStrictSchema,
  resolveCodexCli,
  runtimeCapabilityDigest,
  runCodexAgent,
  validateSchema,
  validateSecondaryWorktree,
  validateRuntimeCapability,
} from '../scripts/codex_workflow_runner.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '..', '..', '..')
const FAKE = join(HERE, 'fixtures', 'fake_codex_cli.mjs')
const FORBIDDEN = [
  '--dangerously-bypass-approvals-and-sandbox',
  '--dangerously-bypass-hook-trust',
  '--add-dir',
  '--skip-git-repo-check',
]

await chmod(FAKE, 0o755)

function runtimeCapability(overrides = {}) {
  const capability = {
    schema: 'studio-runtime-capability/v1',
    runtime: 'codex',
    version: 'test-codex-1',
    advertised_models: null,
    advertised_efforts: null,
    verified: true,
    dispatch_allowed: true,
    ...overrides,
  }
  if (!Object.hasOwn(overrides, 'digest')) {
    capability.digest = runtimeCapabilityDigest(capability)
  }
  return capability
}

async function temp() {
  return mkdtemp(join(tmpdir(), 'studio-codex-runner-test-'))
}

function context(env, overrides = {}) {
  return {
    ritual: 'brainstorm',
    cwd: REPO,
    worktree: null,
    env: { ...process.env, STUDIO_CODEX_CLI: FAKE, ...env },
    timeoutMs: 2_000,
    runtimeCapability: runtimeCapability(),
    ...overrides,
  }
}

const SMALL_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['ok'],
  properties: {
    ok: { type: 'boolean' },
    note: { type: 'string' },
  },
}

test('strict schema is normalized and invalid output fails closed', async () => {
  const normalized = normalizeStrictSchema(SMALL_SCHEMA)
  assert.deepEqual(normalized.required.sort(), ['note', 'ok'])
  validateSchema({ ok: true, note: null }, normalized)

  const valid = await runCodexAgent('return the object', {
    schema: SMALL_SCHEMA,
    label: 'unit:valid',
    phase: 'Probe',
  }, context({ FAKE_CODEX_MODE: 'valid' }))
  assert.deepEqual(valid, { ok: false, note: 'fake' })

  await assert.rejects(
    runCodexAgent('return invalid', {
      schema: SMALL_SCHEMA,
      label: 'unit:invalid',
      phase: 'Probe',
    }, context({ FAKE_CODEX_MODE: 'invalid' })),
    error => error instanceof RunnerError && error.code === 'output_schema_mismatch',
  )
})

test('disjoint oneOf is lowered to anyOf without weakening post-validation', () => {
  const schema = normalizeStrictSchema({
    oneOf: [{ type: 'integer' }, { type: 'string' }],
  })
  assert.equal(Object.hasOwn(schema, 'oneOf'), false)
  assert.deepEqual(schema.anyOf, [{ type: 'integer' }, { type: 'string' }])
  validateSchema(7, schema)
  validateSchema('F-0007', schema)
  assert.throws(
    () => validateSchema(true, schema),
    error => error instanceof RunnerError && error.code === 'output_schema_mismatch',
  )
})

test('overlapping or indeterminate oneOf fails closed before provider dispatch', () => {
  assert.throws(
    () => normalizeStrictSchema({
      oneOf: [{ type: 'string', minLength: 1 }, { type: 'string', enum: ['fixed'] }],
    }),
    error => error instanceof RunnerError && error.code === 'schema_unsupported',
  )
  assert.throws(
    () => normalizeStrictSchema({
      oneOf: [{ enum: ['a'] }, { type: 'integer' }],
    }),
    error => error instanceof RunnerError && error.code === 'schema_unsupported',
  )
  assert.throws(
    () => normalizeStrictSchema({
      oneOf: [{ type: 'number' }, { type: 'integer' }],
    }),
    error => error instanceof RunnerError && error.code === 'schema_unsupported',
  )
})

test('CLI resolver gives one explicit override precedence and rejects ambiguous relative overrides', async () => {
  assert.equal(
    await resolveCodexCli({ STUDIO_CODEX_CLI: FAKE, PATH: '' }),
    await realpath(FAKE),
  )
  await assert.rejects(
    resolveCodexCli({ STUDIO_CODEX_CLI: 'relative/codex', PATH: process.env.PATH }),
    error => error instanceof RunnerError && error.code === 'cli_override_invalid',
  )
})

test('runtime capability digest is canonical and exact shape is enforced', () => {
  const capability = runtimeCapability({
    advertised_models: ['z-model', 'a-model'],
    advertised_efforts: ['low', 'high'],
  })
  const payload = [
    '{"advertised_efforts":["high","low"],',
    '"advertised_models":["a-model","z-model"],',
    '"runtime":"codex",',
    '"schema":"studio-runtime-capability/v1",',
    '"version":"test-codex-1"}',
  ].join('')
  assert.equal(
    capability.digest,
    `sha256:${createHash('sha256').update(payload, 'utf8').digest('hex')}`,
  )
  const validated = validateRuntimeCapability(capability)
  assert.deepEqual(validated.advertised_models, ['a-model', 'z-model'])
  assert.deepEqual(validated.advertised_efforts, ['high', 'low'])

  for (const invalid of [
    { ...capability, digest: 'sha256:' + '0'.repeat(64) },
    { runtime: 'codex', verified: true, dispatch_allowed: true },
    { ...capability, extra: true },
    runtimeCapability({ schema: 'studio-runtime-capability/v0' }),
    runtimeCapability({ version: ' ' }),
    runtimeCapability({ advertised_models: ['duplicate', 'duplicate'] }),
    runtimeCapability({ advertised_efforts: [''] }),
    runtimeCapability({ verified: false }),
    runtimeCapability({ dispatch_allowed: false }),
  ]) {
    assert.throws(
      () => validateRuntimeCapability(invalid),
      error => error instanceof RunnerError && error.code === 'runtime_capability_invalid',
    )
  }
})

test('resolved model and effort must be advertised before spawn', async () => {
  await assert.rejects(
    runCodexAgent('unsupported model', {
      schema: SMALL_SCHEMA,
      label: 'unit:model',
      phase: 'Contract',
      model: 'other-model',
    }, context({}, {
      runtimeCapability: runtimeCapability({ advertised_models: ['allowed-model'] }),
    })),
    error => error instanceof RunnerError && error.code === 'runtime_capability_invalid',
  )
  await assert.rejects(
    runCodexAgent('unsupported effort', {
      schema: SMALL_SCHEMA,
      label: 'unit:effort',
      phase: 'Contract',
      effort: 'high',
    }, context({}, {
      runtimeCapability: runtimeCapability({ advertised_efforts: ['low'] }),
    })),
    error => error instanceof RunnerError && error.code === 'runtime_capability_invalid',
  )
})

test('argv is shell-free, approval-denying, bounded, and rejects unsupported effort', async () => {
  const argv = buildCodexArgs({
    cwd: REPO,
    schemaPath: '/tmp/schema.json',
    outputPath: '/tmp/output.json',
    sandbox: 'read-only',
    model: 'gpt-test',
    effort: 'high',
  })
  assert.equal(argv[0], 'exec')
  assert.ok(argv.includes('approval_policy="never"'))
  assert.ok(argv.includes('--ephemeral'))
  assert.ok(argv.includes('--output-schema'))
  assert.ok(argv.includes('--output-last-message'))
  for (const arg of FORBIDDEN) assert.ok(!argv.includes(arg), arg)
  assert.throws(
    () => buildCodexArgs({
      cwd: REPO,
      schemaPath: '/tmp/schema.json',
      outputPath: '/tmp/output.json',
      sandbox: 'read-only',
      effort: 'ultra-unknown',
    }),
    error => error instanceof RunnerError && error.code === 'effort_unsupported',
  )
})

test('brainstorm agents are read-only and broker phase/result ordering survives', async () => {
  const scratch = await temp()
  try {
    const record = join(scratch, 'record.jsonl')
    const result = await executeWorkflow({
      brokerName: 'brainstorm',
      args: {
        agenda: 'probe ordering',
        personas: [
          { name: 'a', role: 'architect', prior: 'small', body: 'design' },
          { name: 'b', role: 'qa', prior: 'safe', body: 'attack' },
        ],
        maxRounds: 1,
        dryStop: 1,
        agentRuntime: 'codex',
        runtimeCapability: runtimeCapability(),
      },
      cwd: REPO,
      env: {
        ...process.env,
        STUDIO_CODEX_CLI: FAKE,
        FAKE_CODEX_MODE: 'broker',
        FAKE_CODEX_RECORD: record,
      },
      timeoutMs: 2_000,
    })
    assert.equal(result.schema, 'studio-codex-workflow-runner/v1')
    assert.equal(result.dispatch_allowed, true)
    assert.deepEqual(result.phases, ['Diverge', 'Debate', 'Converge'])
    assert.equal(result.output.ritual, 'brainstorm')
    assert.deepEqual(result.output.participants, ['a', 'b'])
    assert.equal(result.output.receipt.schema, 'workflow-receipt/v1')
    const calls = (await readFile(record, 'utf8')).trim().split('\n').map(JSON.parse)
    assert.ok(calls.length >= 7)
    for (const call of calls) {
      assert.equal(call.args[call.args.indexOf('--sandbox') + 1], 'read-only')
      assert.equal(call.depth, '1')
      assert.equal(call.providerSchemaHasOneOf, false, `provider schema retained oneOf for ${call.label}`)
      for (const arg of FORBIDDEN) assert.ok(!call.args.includes(arg), arg)
    }
    assert.ok(calls.findIndex(call => call.label === 'summarizer') < calls.findIndex(call => call.label === 'critic:final'))
  } finally {
    await rm(scratch, { recursive: true, force: true })
  }
})

async function secondaryWorktree(scratch, name = 'repo') {
  const primary = join(scratch, `${name}-primary`)
  const secondary = join(scratch, `${name}-secondary`)
  execFileSync('git', ['init', primary], { stdio: 'ignore' })
  execFileSync('git', ['-C', primary, 'config', 'user.email', 'probe@example.invalid'])
  execFileSync('git', ['-C', primary, 'config', 'user.name', 'Probe'])
  await writeFile(join(primary, 'README.md'), 'probe\n')
  execFileSync('git', ['-C', primary, 'add', 'README.md'])
  execFileSync('git', ['-C', primary, 'commit', '-m', 'probe'], { stdio: 'ignore' })
  execFileSync('git', ['-C', primary, 'worktree', 'add', '-b', 'task/probe', secondary], { stdio: 'ignore' })
  return { primary, secondary }
}

test('pairing grants workspace-write only to dev in a validated secondary worktree', async () => {
  const scratch = await temp()
  try {
    const { primary, secondary } = await secondaryWorktree(scratch)
    await assert.rejects(
      validateSecondaryWorktree(primary, 'master', primary),
      error => error instanceof RunnerError && error.code === 'worktree_invalid',
    )
    const validated = await validateSecondaryWorktree(secondary, 'task/probe', primary)
    assert.equal(validated.path, await realpath(secondary))

    const record = join(scratch, 'record.jsonl')
    const result = await executeWorkflow({
      brokerName: 'pairing',
      args: {
        taskSpec: 'probe pairing',
        acceptanceCriteria: ['broker completes'],
        worktreePath: secondary,
        branch: 'task/probe',
        personas: { dev: { body: 'build' }, qa: { body: 'attack' } },
        maxRounds: 1,
        agentRuntime: 'codex',
        runtimeCapability: runtimeCapability(),
      },
      cwd: primary,
      env: {
        ...process.env,
        STUDIO_CODEX_CLI: FAKE,
        FAKE_CODEX_MODE: 'broker',
        FAKE_CODEX_RECORD: record,
      },
      timeoutMs: 2_000,
    })
    assert.equal(result.schema, 'studio-codex-workflow-runner/v1')
    assert.equal(result.dispatch_allowed, true)
    assert.deepEqual(result.phases, ['Build', 'Attack', 'Verdict'])
    assert.equal(result.output.ritual, 'pairing')
    assert.equal(result.output.readyForIntegration, true)
    const calls = (await readFile(record, 'utf8')).trim().split('\n').map(JSON.parse)
    const dev = calls.find(call => call.label === 'dev:r1')
    const qa = calls.find(call => call.label === 'qa:r1')
    const critic = calls.find(call => call.label === 'critic:verdict')
    assert.ok(calls.length >= 3)
    for (const call of calls) {
      assert.equal(call.providerSchemaHasOneOf, false, `provider schema retained oneOf for ${call.label}`)
    }
    assert.equal(dev.args[dev.args.indexOf('--sandbox') + 1], 'workspace-write')
    assert.equal(qa.args[qa.args.indexOf('--sandbox') + 1], 'read-only')
    assert.equal(critic.args[critic.args.indexOf('--sandbox') + 1], 'read-only')
    assert.equal(dev.cwd, await realpath(secondary))
  } finally {
    await rm(scratch, { recursive: true, force: true })
  }
})

test('solo uses one workspace-write Codex call and preserves criterion binding', async () => {
  const scratch = await temp()
  try {
    const { primary, secondary } = await secondaryWorktree(scratch)
    const record = join(scratch, 'record.jsonl')
    const criteria = [{
      id: 'AC-1', source_ref: 'spec.md#AC-1',
      measure: 'fake-check', mechanical: true,
    }]
    const criteriaDigest = `sha256:${createHash('sha256').update(
      JSON.stringify([{ id: 'AC-1', mechanical: true, measure: 'fake-check', source_ref: 'spec.md#AC-1' }]),
    ).digest('hex')}`
    const result = await executeWorkflow({
      brokerName: 'solo',
      args: {
        objective: 'bounded edit', worktreePath: secondary, branch: 'task/probe',
        persona: { name: 'dev', body: 'build' }, criteria, criteriaDigest,
        agentRuntime: 'codex', runtimeCapability: runtimeCapability(),
      },
      cwd: primary,
      env: {
        ...process.env, STUDIO_CODEX_CLI: FAKE,
        FAKE_CODEX_MODE: 'broker', FAKE_CODEX_RECORD: record,
      },
      timeoutMs: 2_000,
    })
    assert.equal(result.dispatch_allowed, true)
    assert.equal(result.output.ritual, 'solo')
    assert.equal(result.output.receipt.counters.model_calls, 1)
    assert.equal(result.output.criteria_digest, criteriaDigest)
    const calls = (await readFile(record, 'utf8')).trim().split('\n').map(JSON.parse)
    assert.equal(calls.length, 1)
    assert.equal(calls[0].label, 'solo:dev')
    assert.equal(calls[0].args[calls[0].args.indexOf('--sandbox') + 1], 'workspace-write')
    assert.equal(calls[0].cwd, await realpath(secondary))
  } finally {
    await rm(scratch, { recursive: true, force: true })
  }
})

test('pairing rejects a secondary worktree from an unrelated repository', async () => {
  const scratch = await temp()
  try {
    const runnerRepo = await secondaryWorktree(scratch, 'runner')
    const unrelatedRepo = await secondaryWorktree(scratch, 'unrelated')
    await assert.rejects(
      validateSecondaryWorktree(
        unrelatedRepo.secondary,
        'task/probe',
        runnerRepo.primary,
      ),
      error => error instanceof RunnerError && error.code === 'worktree_invalid',
    )
  } finally {
    await rm(scratch, { recursive: true, force: true })
  }
})

test('broker-declared errors keep the production envelope fail-closed', async () => {
  const result = await executeWorkflow({
    brokerName: 'brainstorm',
    args: {
      agenda: 'invalid cast',
      personas: [{ name: 'only-one', role: 'architect', prior: 'single', body: 'single' }],
      agentRuntime: 'codex',
      runtimeCapability: runtimeCapability(),
    },
    cwd: REPO,
    env: {
      ...process.env,
      STUDIO_CODEX_CLI: FAKE,
      FAKE_CODEX_MODE: 'broker',
    },
    timeoutMs: 2_000,
  })
  assert.equal(result.schema, 'studio-codex-workflow-runner/v1')
  assert.equal(result.dispatch_allowed, false)
  assert.equal(result.error, 'broker_error')
  assert.equal(result.details.output.ritual, 'brainstorm')
  assert.match(result.message, /needs >=2 personas/)
})

test('production dispatch rejects absent or unverified Codex runtime capability', async () => {
  await assert.rejects(
    executeWorkflow({
      brokerName: 'brainstorm',
      args: {
        agenda: 'unverified',
        personas: [
          { name: 'a', role: 'architect', prior: 'a', body: 'a' },
          { name: 'b', role: 'qa', prior: 'b', body: 'b' },
        ],
      },
      cwd: REPO,
      env: { ...process.env, STUDIO_CODEX_CLI: FAKE },
      timeoutMs: 2_000,
    }),
    error => error instanceof RunnerError && error.code === 'runtime_capability_invalid',
  )
})

test('approval-required action fails closed and recursion is rejected', async () => {
  await assert.rejects(
    runCodexAgent('try a forbidden mutation', {
      schema: SMALL_SCHEMA,
      label: 'unit:approval',
      phase: 'Probe',
    }, context({ FAKE_CODEX_MODE: 'approval' })),
    error => error instanceof RunnerError && error.code === 'codex_exec_failed',
  )
  await assert.rejects(
    runCodexAgent('nested', {
      schema: SMALL_SCHEMA,
      label: 'unit:nested',
      phase: 'Probe',
    }, context({ STUDIO_CODEX_RUNNER_DEPTH: '1' })),
    error => error instanceof RunnerError && error.code === 'recursion_forbidden',
  )
})

function alive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    if (error.code === 'ESRCH') return false
    throw error
  }
}

test('timeout terminates the detached process group including grandchildren', async () => {
  if (process.platform === 'win32') return
  const scratch = await temp()
  try {
    const pidFile = join(scratch, 'pids.json')
    await assert.rejects(
      runCodexAgent('hang', {
        schema: SMALL_SCHEMA,
        label: 'unit:hang',
        phase: 'Probe',
      }, context({
        FAKE_CODEX_MODE: 'hang',
        FAKE_CODEX_PIDS: pidFile,
      }, { timeoutMs: 250 })),
      error => error instanceof RunnerError && error.code === 'agent_timeout',
    )
    let pids = null
    for (let attempt = 0; attempt < 20 && !pids; attempt += 1) {
      try {
        pids = JSON.parse(await readFile(pidFile, 'utf8'))
      } catch {
        await new Promise(resolveWait => setTimeout(resolveWait, 25))
      }
    }
    assert.ok(pids, 'child/grandchild pid evidence was not written')
    await new Promise(resolveWait => setTimeout(resolveWait, 100))
    assert.equal(alive(pids.child), false, `child ${pids.child} survived`)
    assert.equal(alive(pids.grandchild), false, `grandchild ${pids.grandchild} survived`)
  } finally {
    await rm(scratch, { recursive: true, force: true })
  }
})
