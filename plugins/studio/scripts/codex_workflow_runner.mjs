#!/usr/bin/env node
/**
 * Production Codex workflow runner for the existing Studio brokers.
 * Broker source stays runtime-neutral; this adapter injects the Codex CLI
 * agent boundary and enforces the execution contract fail-closed.
 */
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { constants as fsConstants } from 'node:fs'
import {
  access, mkdtemp, readFile, realpath, rm, stat, writeFile,
} from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { delimiter, dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const PLUGIN = resolve(HERE, '..')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const MAX_OUTPUT_BYTES = 1024 * 1024
const DEFAULT_TIMEOUT_MS = 120_000
const ALLOWED_EFFORTS = new Set(['minimal', 'low', 'medium', 'high', 'xhigh'])
const FORBIDDEN_ARGS = new Set([
  '--dangerously-bypass-approvals-and-sandbox',
  '--dangerously-bypass-hook-trust',
  '--add-dir',
  '--skip-git-repo-check',
])
const RUNTIME_CAPABILITY_FIELDS = new Set([
  'schema',
  'runtime',
  'version',
  'advertised_models',
  'advertised_efforts',
  'verified',
  'dispatch_allowed',
  'digest',
])

export class RunnerError extends Error {
  constructor(code, message, details = {}) {
    super(message)
    this.name = 'RunnerError'
    this.code = code
    this.details = details
  }
}

function unicodeCompare(left, right) {
  const a = Array.from(left, character => character.codePointAt(0))
  const b = Array.from(right, character => character.codePointAt(0))
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

function runtimeCapabilityBase(capability) {
  return {
    schema: capability.schema,
    runtime: capability.runtime,
    version: capability.version,
    advertised_models: capability.advertised_models === null
      ? null
      : [...capability.advertised_models].sort(unicodeCompare),
    advertised_efforts: capability.advertised_efforts === null
      ? null
      : [...capability.advertised_efforts].sort(unicodeCompare),
  }
}

export function runtimeCapabilityDigest(capability) {
  const payload = canonicalJson(runtimeCapabilityBase(capability))
  return `sha256:${createHash('sha256').update(payload, 'utf8').digest('hex')}`
}

function validAdvertisedSet(value) {
  return value === null || (
    Array.isArray(value)
    && value.every(item => typeof item === 'string' && item.trim().length > 0)
    && new Set(value).size === value.length
  )
}

export function validateRuntimeCapability(capability) {
  const fields = capability && typeof capability === 'object' && !Array.isArray(capability)
    ? Object.keys(capability)
    : []
  const exactFields = fields.length === RUNTIME_CAPABILITY_FIELDS.size
    && fields.every(field => RUNTIME_CAPABILITY_FIELDS.has(field))
  const versionValid = capability && (
    capability.version === null
    || (typeof capability.version === 'string' && capability.version.trim().length > 0)
  )
  if (
    !exactFields
    || capability.schema !== 'studio-runtime-capability/v1'
    || capability.runtime !== 'codex'
    || !versionValid
    || !validAdvertisedSet(capability.advertised_models)
    || !validAdvertisedSet(capability.advertised_efforts)
    || capability.verified !== true
    || capability.dispatch_allowed !== true
    || typeof capability.digest !== 'string'
    || capability.digest !== runtimeCapabilityDigest(capability)
  ) {
    throw new RunnerError(
      'runtime_capability_invalid',
      'runtimeCapability must be the exact canonical verified Codex capability',
    )
  }
  return {
    ...capability,
    advertised_models: capability.advertised_models === null
      ? null
      : [...capability.advertised_models].sort(unicodeCompare),
    advertised_efforts: capability.advertised_efforts === null
      ? null
      : [...capability.advertised_efforts].sort(unicodeCompare),
  }
}

function validateAgentCapability(options, capability) {
  if (!capability) {
    throw new RunnerError(
      'runtime_capability_invalid',
      'agent dispatch requires the validated Codex runtime capability',
    )
  }
  for (const [option, advertised] of [
    ['model', 'advertised_models'],
    ['effort', 'advertised_efforts'],
  ]) {
    const value = options[option]
    const allowed = capability[advertised]
    if (value !== null && value !== undefined && allowed !== null && !allowed.includes(value)) {
      throw new RunnerError(
        'runtime_capability_invalid',
        `resolved ${option} is not advertised by the verified Codex capability`,
      )
    }
  }
}

async function executable(path) {
  try {
    await access(path, fsConstants.X_OK)
    return true
  } catch {
    return false
  }
}

export async function resolveCodexCli(env = process.env) {
  const override = env.STUDIO_CODEX_CLI
  if (override) {
    if (!isAbsolute(override)) {
      throw new RunnerError('cli_override_invalid', 'STUDIO_CODEX_CLI must be an absolute executable path')
    }
    const canonical = await realpath(override).catch(() => null)
    if (!canonical || !(await executable(canonical))) {
      throw new RunnerError('cli_override_unavailable', 'STUDIO_CODEX_CLI is not executable')
    }
    return canonical
  }

  for (const directory of String(env.PATH || '').split(delimiter).filter(Boolean)) {
    const candidate = join(directory, 'codex')
    if (await executable(candidate)) return realpath(candidate)
  }

  const bundled = '/Applications/ChatGPT.app/Contents/Resources/codex'
  if (await executable(bundled)) return realpath(bundled)
  throw new RunnerError('cli_unavailable', 'codex CLI was not found in STUDIO_CODEX_CLI, PATH, or the macOS bundle')
}

function git(path, args) {
  const result = spawnSync('git', ['-C', path, ...args], {
    encoding: 'utf8',
    shell: false,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  if (result.status !== 0) {
    throw new RunnerError('worktree_invalid', result.stderr.trim() || `git ${args.join(' ')} failed`)
  }
  return result.stdout.trim()
}

async function gitCommonDir(path) {
  const raw = git(path, ['rev-parse', '--git-common-dir'])
  return realpath(isAbsolute(raw) ? raw : resolve(path, raw))
}

export async function validateSecondaryWorktree(path, expectedBranch = null, runnerCwd = null) {
  if (!path || !isAbsolute(path)) {
    throw new RunnerError('worktree_invalid', 'pairing worktreePath must be absolute')
  }
  if (!runnerCwd || !isAbsolute(runnerCwd)) {
    throw new RunnerError('worktree_invalid', 'pairing validation requires the Runner canonical cwd')
  }
  const canonical = await realpath(path).catch(() => null)
  if (!canonical) throw new RunnerError('worktree_invalid', 'pairing worktreePath does not exist')
  const top = await realpath(git(canonical, ['rev-parse', '--show-toplevel']))
  if (top !== canonical) {
    throw new RunnerError('worktree_invalid', 'pairing worktreePath must be the git worktree root')
  }
  const branch = git(canonical, ['branch', '--show-current'])
  if (!branch || (expectedBranch && branch !== expectedBranch)) {
    throw new RunnerError('worktree_invalid', 'pairing worktree branch does not match the sealed branch')
  }
  const records = git(canonical, ['worktree', 'list', '--porcelain'])
    .split('\n')
    .filter(line => line.startsWith('worktree '))
    .map(line => line.slice('worktree '.length))
  if (records.length < 2 || await realpath(records[0]) === canonical) {
    throw new RunnerError('worktree_invalid', 'pairing requires a secondary git worktree')
  }
  const [targetCommonDir, runnerCommonDir] = await Promise.all([
    gitCommonDir(canonical),
    gitCommonDir(await realpath(runnerCwd)),
  ])
  if (targetCommonDir !== runnerCommonDir) {
    throw new RunnerError('worktree_invalid', 'pairing worktree must belong to the Runner repository')
  }
  return { path: canonical, branch }
}

function nullable(schema) {
  if (!schema || typeof schema !== 'object') return schema
  if (schema.type === 'null') return schema
  if (Array.isArray(schema.type) && schema.type.includes('null')) return schema
  if (Array.isArray(schema.anyOf) && schema.anyOf.some(item => item && item.type === 'null')) return schema
  return { anyOf: [schema, { type: 'null' }] }
}

function rootTypes(schema) {
  if (!schema || typeof schema !== 'object') return null
  if (typeof schema.type === 'string') return new Set([schema.type])
  if (Array.isArray(schema.type) && schema.type.every(type => typeof type === 'string')) {
    return new Set(schema.type)
  }
  if (Array.isArray(schema.anyOf)) {
    const combined = new Set()
    for (const branch of schema.anyOf) {
      const branchTypes = rootTypes(branch)
      if (!branchTypes) return null
      for (const type of branchTypes) combined.add(type)
    }
    return combined
  }
  return null
}

function assertDisjointBranches(branches) {
  const seen = new Set()
  for (const branch of branches) {
    const types = rootTypes(branch)
    if (!types || types.size === 0) {
      throw new RunnerError(
        'schema_unsupported',
        'oneOf branches need statically disjoint root types for provider lowering',
      )
    }
    for (const type of types) {
      const overlaps = seen.has(type)
        || (type === 'integer' && seen.has('number'))
        || (type === 'number' && seen.has('integer'))
      if (overlaps) {
        throw new RunnerError(
          'schema_unsupported',
          `oneOf root type ${type} overlaps and cannot be lowered without weakening validation`,
        )
      }
      seen.add(type)
    }
  }
}

/**
 * Codex structured output uses the strict JSON-schema subset. Optional object
 * properties are represented as required nullable fields at the CLI boundary.
 * `oneOf` is lowered only when branch root types prove that `anyOf` preserves
 * exactly-one semantics; ambiguous or overlapping unions fail before dispatch.
 */
export function normalizeStrictSchema(input) {
  if (!input || typeof input !== 'object') return input
  if (Array.isArray(input)) return input.map(normalizeStrictSchema)
  const schema = {}
  for (const [key, value] of Object.entries(input)) {
    if (key === 'properties' || key === 'oneOf') continue
    schema[key] = normalizeStrictSchema(value)
  }
  if (Array.isArray(input.oneOf)) {
    if (input.oneOf.length < 2) {
      throw new RunnerError('schema_unsupported', 'oneOf needs at least two branches')
    }
    const branches = input.oneOf.map(normalizeStrictSchema)
    assertDisjointBranches(branches)
    if (schema.anyOf) {
      throw new RunnerError('schema_unsupported', 'schemas combining oneOf and anyOf are unsupported')
    }
    schema.anyOf = branches
  }
  if (input.properties && typeof input.properties === 'object') {
    const originallyRequired = new Set(input.required || [])
    schema.properties = Object.fromEntries(
      Object.entries(input.properties).map(([key, value]) => {
        const normalized = normalizeStrictSchema(value)
        return [key, originallyRequired.has(key) ? normalized : nullable(normalized)]
      }),
    )
    schema.required = Object.keys(input.properties)
  }
  return schema
}

function typeMatches(value, type) {
  if (type === 'null') return value === null
  if (type === 'array') return Array.isArray(value)
  if (type === 'object') return value !== null && typeof value === 'object' && !Array.isArray(value)
  if (type === 'integer') return Number.isInteger(value)
  return typeof value === type
}

export function validateSchema(value, schema, at = '$') {
  if (!schema || typeof schema !== 'object') return
  if (schema.anyOf) {
    const passed = schema.anyOf.some(option => {
      try {
        validateSchema(value, option, at)
        return true
      } catch {
        return false
      }
    })
    if (!passed) throw new RunnerError('output_schema_mismatch', `${at} does not match anyOf`)
    return
  }
  if (schema.oneOf) {
    const passed = schema.oneOf.filter(option => {
      try {
        validateSchema(value, option, at)
        return true
      } catch {
        return false
      }
    }).length
    if (passed !== 1) throw new RunnerError('output_schema_mismatch', `${at} does not match exactly one oneOf branch`)
    return
  }
  if (schema.type && !typeMatches(value, schema.type)) {
    throw new RunnerError('output_schema_mismatch', `${at} must be ${schema.type}`)
  }
  if (schema.enum && !schema.enum.includes(value)) {
    throw new RunnerError('output_schema_mismatch', `${at} is outside enum`)
  }
  if (typeof value === 'string' && schema.minLength && value.length < schema.minLength) {
    throw new RunnerError('output_schema_mismatch', `${at} is shorter than minLength`)
  }
  if (Array.isArray(value) && schema.items) {
    value.forEach((item, index) => validateSchema(item, schema.items, `${at}[${index}]`))
  }
  if (value !== null && typeof value === 'object' && !Array.isArray(value) && schema.properties) {
    for (const key of schema.required || []) {
      if (!(key in value)) throw new RunnerError('output_schema_mismatch', `${at}.${key} is required`)
    }
    if (schema.additionalProperties === false) {
      for (const key of Object.keys(value)) {
        if (!(key in schema.properties)) {
          throw new RunnerError('output_schema_mismatch', `${at}.${key} is not allowed`)
        }
      }
    }
    for (const [key, child] of Object.entries(schema.properties)) {
      if (key in value) validateSchema(value[key], child, `${at}.${key}`)
    }
  }
}

export function buildCodexArgs({
  cwd, schemaPath, outputPath, sandbox, model = null, effort = null,
}) {
  if (!['read-only', 'workspace-write'].includes(sandbox)) {
    throw new RunnerError('sandbox_invalid', `unsupported sandbox: ${sandbox}`)
  }
  if (effort && !ALLOWED_EFFORTS.has(effort)) {
    throw new RunnerError('effort_unsupported', `unsupported Codex effort: ${effort}`)
  }
  const args = [
    'exec',
    '--ephemeral',
    '--ignore-user-config',
    '--strict-config',
    '-c', 'approval_policy="never"',
    '--sandbox', sandbox,
    '--cd', cwd,
    '--output-schema', schemaPath,
    '--output-last-message', outputPath,
    '--color', 'never',
  ]
  if (model) args.push('--model', model)
  if (effort) args.push('-c', `model_reasoning_effort="${effort}"`)
  args.push('-')
  if (args.some(arg => FORBIDDEN_ARGS.has(arg))) {
    throw new RunnerError('forbidden_argument', 'dangerous or boundary-expanding Codex argument was generated')
  }
  return args
}

function terminateProcessGroup(child, graceMs = 750) {
  if (!child.pid) return Promise.resolve()
  try {
    process.kill(-child.pid, 'SIGTERM')
  } catch (error) {
    if (error.code !== 'ESRCH') throw error
  }
  return new Promise(resolveKill => {
    const timer = setTimeout(() => {
      try {
        process.kill(-child.pid, 'SIGKILL')
      } catch (error) {
        if (error.code !== 'ESRCH') throw error
      }
      resolveKill()
    }, graceMs)
    timer.unref()
    child.once('exit', () => {
      clearTimeout(timer)
      resolveKill()
    })
  })
}

export async function runCodexAgent(prompt, options, context) {
  validateAgentCapability(options, context.runtimeCapability)
  const depth = Number.parseInt(String(context.env.STUDIO_CODEX_RUNNER_DEPTH || '0'), 10)
  if (!Number.isInteger(depth) || depth !== 0) {
    throw new RunnerError('recursion_forbidden', 'nested Studio Codex runner invocation is forbidden')
  }
  const cli = await resolveCodexCli(context.env)
  const schema = normalizeStrictSchema(options.schema)
  const temp = await mkdtemp(join(tmpdir(), 'studio-codex-workflow-'))
  const schemaPath = join(temp, 'schema.json')
  const outputPath = join(temp, 'output.json')
  const sandbox = context.ritual === 'pairing' && String(options.label).startsWith('dev:')
    ? 'workspace-write'
    : 'read-only'
  const cwd = context.ritual === 'pairing' ? context.worktree.path : context.cwd
  let child
  let stderr = ''
  try {
    const encodedSchema = JSON.stringify(schema)
    if (Buffer.byteLength(encodedSchema) > MAX_OUTPUT_BYTES) {
      throw new RunnerError('schema_too_large', 'normalized schema exceeds the 1 MiB limit')
    }
    await writeFile(schemaPath, encodedSchema, { encoding: 'utf8', mode: 0o600 })
    const argv = buildCodexArgs({
      cwd,
      schemaPath,
      outputPath,
      sandbox,
      model: options.model,
      effort: options.effort,
    })
    child = spawn(cli, argv, {
      cwd,
      detached: process.platform !== 'win32',
      env: {
        ...context.env,
        STUDIO_CODEX_RUNNER_DEPTH: '1',
        STUDIO_CODEX_AGENT_LABEL: String(options.label || ''),
        STUDIO_CODEX_AGENT_PHASE: String(options.phase || ''),
      },
      shell: false,
      stdio: ['pipe', 'ignore', 'pipe'],
    })
    child.stderr.setEncoding('utf8')
    child.stderr.on('data', chunk => {
      if (stderr.length < MAX_OUTPUT_BYTES) stderr += chunk
    })
    child.stdin.end(prompt)

    let timedOut = false
    const exit = new Promise((resolveExit, rejectExit) => {
      child.once('error', rejectExit)
      child.once('exit', (code, signal) => resolveExit({ code, signal }))
    })
    const timeout = setTimeout(() => {
      timedOut = true
      void terminateProcessGroup(child)
    }, context.timeoutMs)
    timeout.unref()
    const status = await exit
    clearTimeout(timeout)
    if (timedOut) {
      await terminateProcessGroup(child)
      throw new RunnerError('agent_timeout', `Codex agent timed out after ${context.timeoutMs}ms`)
    }
    if (status.code !== 0) {
      throw new RunnerError('codex_exec_failed', `codex exec failed (${status.code ?? status.signal})`, {
        stderr: stderr.slice(0, 4000),
      })
    }
    const info = await stat(outputPath).catch(() => null)
    if (!info || info.size > MAX_OUTPUT_BYTES) {
      throw new RunnerError('output_invalid', 'Codex output is missing or exceeds the 1 MiB limit')
    }
    let parsed
    try {
      parsed = JSON.parse(await readFile(outputPath, 'utf8'))
    } catch {
      throw new RunnerError('output_invalid', 'Codex output is not JSON')
    }
    validateSchema(parsed, schema)
    return parsed
  } finally {
    if (child && child.exitCode === null && child.signalCode === null) {
      await terminateProcessGroup(child)
    }
    await rm(temp, { recursive: true, force: true })
  }
}

export async function loadBroker(name) {
  if (!['brainstorm', 'pairing'].includes(name)) {
    throw new RunnerError('broker_invalid', 'broker must be brainstorm or pairing')
  }
  const path = join(PLUGIN, 'broker', `${name}.workflow.js`)
  const source = (await readFile(path, 'utf8')).replace('export const meta', 'const meta')
  return new AsyncFunction('args', 'budget', 'phase', 'parallel', 'agent', 'log', source)
}

function assertRuntimeCapability(args) {
  if (!args || args.agentRuntime !== 'codex') {
    throw new RunnerError(
      'runtime_capability_invalid',
      'Codex workflow dispatch requires a matching verified and dispatchable runtimeCapability',
    )
  }
  return validateRuntimeCapability(args.runtimeCapability)
}

export async function executeWorkflow({
  brokerName,
  args,
  cwd = process.cwd(),
  env = process.env,
  timeoutMs = DEFAULT_TIMEOUT_MS,
}) {
  const runtimeCapability = assertRuntimeCapability(args)
  const canonicalCwd = await realpath(cwd)
  let worktree = null
  if (brokerName === 'pairing') {
    worktree = await validateSecondaryWorktree(args.worktreePath, args.branch || null, canonicalCwd)
  }
  const broker = await loadBroker(brokerName)
  const phases = []
  const logs = []
  const output = await broker(
    args,
    { spent: () => null },
    value => phases.push(value),
    jobs => Promise.all(jobs.map(job => job())),
    (prompt, options) => runCodexAgent(prompt, options, {
      ritual: brokerName,
      cwd: canonicalCwd,
      worktree,
      env,
      timeoutMs,
      runtimeCapability,
    }),
    value => logs.push(value),
  )
  if (output.error) {
    return {
      schema: 'studio-codex-workflow-runner/v1',
      dispatch_allowed: false,
      error: 'broker_error',
      message: String(output.error),
      details: {
        broker: brokerName,
        phases,
        logs,
        output,
      },
    }
  }
  return {
    schema: 'studio-codex-workflow-runner/v1',
    dispatch_allowed: true,
    broker: brokerName,
    phases,
    logs,
    output,
  }
}

function parseCli(argv) {
  const parsed = {}
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (!['--broker', '--args-file', '--timeout-ms'].includes(arg)) {
      throw new RunnerError('usage', `unknown argument: ${arg}`)
    }
    if (index + 1 >= argv.length) throw new RunnerError('usage', `${arg} needs a value`)
    parsed[arg.slice(2)] = argv[++index]
  }
  if (!parsed.broker || !parsed['args-file']) {
    throw new RunnerError('usage', '--broker and --args-file are required')
  }
  if (!isAbsolute(parsed['args-file'])) {
    throw new RunnerError('args_file_invalid', '--args-file must be an absolute sealed input path')
  }
  const timeoutMs = parsed['timeout-ms'] ? Number.parseInt(parsed['timeout-ms'], 10) : DEFAULT_TIMEOUT_MS
  if (!Number.isInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 600_000) {
    throw new RunnerError('usage', '--timeout-ms must be an integer from 100 to 600000')
  }
  return { brokerName: parsed.broker, argsFile: parsed['args-file'], timeoutMs }
}

async function main() {
  try {
    const cli = parseCli(process.argv.slice(2))
    const args = JSON.parse(await readFile(resolve(cli.argsFile), 'utf8'))
    const result = await executeWorkflow({
      brokerName: cli.brokerName,
      args,
      timeoutMs: cli.timeoutMs,
    })
    process.stdout.write(`${JSON.stringify(result)}\n`)
    if (!result.dispatch_allowed) process.exitCode = 1
  } catch (error) {
    const known = error instanceof RunnerError
    process.stdout.write(`${JSON.stringify({
      schema: 'studio-codex-workflow-runner/v1',
      dispatch_allowed: false,
      error: known ? error.code : 'internal_error',
      message: error.message,
      details: known ? error.details : {},
    })}\n`)
    process.exitCode = 1
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main()
}
