import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { constants as fsConstants } from 'node:fs'
import {
  access, chmod, lstat, mkdir, mkdtemp, readFile, realpath, readdir, rm, writeFile,
} from 'node:fs/promises'
import { createServer } from 'node:http'
import { homedir, tmpdir } from 'node:os'
import {
  basename, dirname, isAbsolute, join, relative,
} from 'node:path'

export const NATIVE_CAPABILITY_SCHEMA = 'studio-native-persistent-capability/v2'
export const NATIVE_ACTION_RECEIPT_SCHEMA = 'studio-native-action-receipt/v1'
const RESOLVED_PROFILE_SCHEMA = 'studio-native-resolved-agent-profile/v1'
export const APP_SERVER_PROTOCOL = 'codex-app-server-stdio/v2'
export const APP_SERVER_CONTRACT_STABILITY = 'pinned-experimental-v2'
export const BUNDLED_CODEX_BINARY = '/Applications/ChatGPT.app/Contents/Resources/codex'
export const PINNED_CODEX_VERSION = 'codex-cli 0.146.0-alpha.3.1'
export const LEGACY_PINNED_BINARY_DIGEST = 'sha256:6d8be49e49751554df16572369e636cbe02c84b208cad3dc35528c846eeca223'
export const PINNED_BINARY_DIGEST = 'sha256:fb2b6b35789e59c885cf4d2aee12475809dd67b2c10df580e638122fd6b3438e'
export const PINNED_SCHEMA_DIGEST = 'sha256:a911a642ce504968155a282435e8f2a3300c7815fc1c6e1633e7c55c5f924293'
export const SUPPORTED_BINARY_DIGESTS = Object.freeze([
  LEGACY_PINNED_BINARY_DIGEST,
  PINNED_BINARY_DIGEST,
])

const MAX_PROTOCOL_BYTES = 1024 * 1024
const TOOL_CAPTURE_PROVIDER = 'studio_tool_capture'
const TOOL_CAPTURE_TOKEN_ENV = 'STUDIO_TOOL_CAPTURE_TOKEN'
const UUID_V7 = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SAFE_ENABLED_FEATURES = new Set([
  'enable_request_compression',
  'fast_mode',
  'personality',
  'remote_compaction_v2',
])
const FORBIDDEN_NOTIFICATION = /^(?:app|hook|mcp|plugin|skill)|capabilit/i
const SAFE_ITEM_TYPES = new Set([
  'userMessage',
  'agentMessage',
  'reasoning',
  'contextCompaction',
])
const PRODUCTION_CAPABILITIES = new WeakSet()
const PRODUCTION_TURN_BINDINGS = new WeakSet()
const PRODUCTION_RECEIPTS = new WeakSet()
const PRODUCTION_OBSERVATIONS = new WeakSet()
const TEST_CAPABILITIES = new WeakSet()
const TEST_TURN_BINDINGS = new WeakSet()
const TEST_RECEIPTS = new WeakSet()
const TEST_OBSERVATIONS = new WeakSet()
const KNOWN_NOTIFICATIONS = new Set([
  'turn/started',
  'turn/completed',
  'item/started',
  'item/completed',
  'item/agentMessage/delta',
  'item/reasoning/summaryTextDelta',
  'item/reasoning/textDelta',
  'item/commandExecution/outputDelta',
  'thread/tokenUsage/updated',
  'thread/started',
  'thread/settings/updated',
  'thread/status/changed',
  'thread/deleted',
  'turn/diff/updated',
  'turn/plan/updated',
  'remoteControl/status/changed',
  'deprecationNotice',
])
export const PERSISTENT_NATIVE_MINIMAL_CONFIG = [
  'include_apps_instructions = false',
  'include_collaboration_mode_instructions = false',
  'include_environment_context = false',
  'web_search = "disabled"',
  'cli_auth_credentials_store = "file"',
  'approval_policy = "never"',
  'sandbox_mode = "read-only"',
  '',
  '[features]',
  'apps = false',
  'auth_elicitation = false',
  'browser_use = false',
  'browser_use_external = false',
  'browser_use_full_cdp_access = false',
  'code_mode = false',
  'code_mode_host = false',
  'computer_use = false',
  'default_mode_request_user_input = false',
  'enable_mcp_apps = false',
  'goals = false',
  'guardian_approval = false',
  'hooks = false',
  'image_generation = false',
  'in_app_browser = false',
  'memories = false',
  'mentions_v2 = false',
  'multi_agent = false',
  'multi_agent_v2 = false',
  'plugin_sharing = false',
  'plugins = false',
  'remote_plugin = false',
  'request_permissions_tool = false',
  'shell_snapshot = false',
  'skill_mcp_dependency_install = false',
  'skill_search = false',
  'standalone_web_search = false',
  'tool_call_mcp_elicitation = false',
  'tool_suggest = false',
  'web_search_cached = false',
  'web_search_request = false',
  'workspace_dependencies = false',
  'shell_tool = false',
  'unified_exec = false',
  '',
].join('\n')
export const PINNED_CONFIG_DIGEST = sha256(PERSISTENT_NATIVE_MINIMAL_CONFIG)

function toolCaptureConfig(baseUrl) {
  const providerSelection = `model_provider = "${TOOL_CAPTURE_PROVIDER}"\n`
  const providerConfig = [
    '',
    `[model_providers.${TOOL_CAPTURE_PROVIDER}]`,
    'name = "Studio loopback tool inventory capture"',
    `base_url = "${baseUrl}"`,
    `env_key = "${TOOL_CAPTURE_TOKEN_ENV}"`,
    'wire_api = "responses"',
    'requires_openai_auth = false',
    'request_max_retries = 0',
    'stream_max_retries = 0',
    'stream_idle_timeout_ms = 5000',
    '',
  ].join('\n')
  const config = PERSISTENT_NATIVE_MINIMAL_CONFIG.replace('\n[features]', `\n${providerSelection}\n[features]`)
    + providerConfig
  return {
    config,
    provider_delta: {
      model_provider: TOOL_CAPTURE_PROVIDER,
      provider: {
        name: 'Studio loopback tool inventory capture',
        base_url: baseUrl,
        env_key: TOOL_CAPTURE_TOKEN_ENV,
        wire_api: 'responses',
        requires_openai_auth: false,
        request_max_retries: 0,
        stream_max_retries: 0,
        stream_idle_timeout_ms: 5000,
      },
    },
  }
}

export class NativeAdapterError extends Error {
  constructor(code, message, details = {}) {
    super(message)
    this.name = 'NativeAdapterError'
    this.code = code
    this.details = details
  }
}

export function isAdapterOwnedPersistentCapability(value) {
  return Boolean(value && typeof value === 'object' && PRODUCTION_CAPABILITIES.has(value))
}

export function isAdapterOwnedTurnBinding(value) {
  return Boolean(value && typeof value === 'object' && PRODUCTION_TURN_BINDINGS.has(value))
}

export function isAdapterOwnedNativeReceipt(value) {
  return Boolean(value && typeof value === 'object' && PRODUCTION_RECEIPTS.has(value))
}

export function isAdapterOwnedNativeObservation(value) {
  return Boolean(value && typeof value === 'object' && PRODUCTION_OBSERVATIONS.has(value))
}

export function isTestAdapterOwnedPersistentCapability(value) {
  return Boolean(value && typeof value === 'object' && TEST_CAPABILITIES.has(value))
}

function authorityRegistry(authority, production, fixture) {
  return authority === 'production' ? production : fixture
}

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

function sha256(value) {
  const bytes = Buffer.isBuffer(value) ? value : Buffer.from(String(value), 'utf8')
  return `sha256:${createHash('sha256').update(bytes).digest('hex')}`
}

async function executable(path) {
  try {
    await access(path, fsConstants.X_OK)
    return true
  } catch {
    return false
  }
}

async function resolveBundledCodex(binary, expectedBinary = BUNDLED_CODEX_BINARY) {
  if (!binary || !isAbsolute(binary)) {
    throw new NativeAdapterError('binary_invalid', 'Production app-server binary must be an absolute path')
  }
  const canonical = await realpath(binary).catch(() => null)
  if (!canonical || !(await executable(canonical))) {
    throw new NativeAdapterError('binary_unavailable', 'Production app-server binary is not executable')
  }
  const canonicalExpected = await realpath(expectedBinary).catch(() => null)
  if (!canonicalExpected || canonical !== canonicalExpected) {
    throw new NativeAdapterError('binary_identity_mismatch', 'Production app-server binary identity is not pinned')
  }
  return canonical
}

async function ensureRegularFile(path, label, expectedMode = null) {
  const info = await lstat(path).catch(() => null)
  if (!info || !info.isFile() || info.isSymbolicLink()) {
    throw new NativeAdapterError('isolated_home_invalid', `${label} must be a regular file`)
  }
  if (expectedMode !== null && (info.mode & 0o777) !== expectedMode) {
    throw new NativeAdapterError('isolated_home_invalid', `${label} has unsafe permissions`)
  }
}

async function createIsolatedCodexHome({
  runtimeRoot,
  sourceCodexHome,
  authFile = 'auth.json',
}) {
  const canonicalRuntimeRoot = await realpath(runtimeRoot)
  const canonicalSourceHome = await realpath(sourceCodexHome)
  if (canonicalRuntimeRoot === canonicalSourceHome) {
    throw new NativeAdapterError('shared_codex_home_forbidden', 'Production admission forbids shared CODEX_HOME')
  }
  const sourceAuth = join(canonicalSourceHome, authFile)
  await ensureRegularFile(sourceAuth, 'source auth')
  const isolatedHome = join(canonicalRuntimeRoot, 'codex-home')
  if (await lstat(isolatedHome).catch(() => null)) {
    throw new NativeAdapterError('isolated_home_exists', 'isolated CODEX_HOME must be newly created')
  }
  await mkdir(isolatedHome, { recursive: false, mode: 0o700 })
  const canonicalHome = await realpath(isolatedHome)
  const homeInfo = await lstat(isolatedHome)
  if (
    canonicalHome === canonicalSourceHome
    || homeInfo.isSymbolicLink()
    || !homeInfo.isDirectory()
    || (homeInfo.mode & 0o777) !== 0o700
  ) {
    throw new NativeAdapterError('shared_codex_home_forbidden', 'isolated CODEX_HOME aliases the source home')
  }
  const authSnapshot = join(canonicalHome, authFile)
  const configPath = join(canonicalHome, 'config.toml')
  try {
    const authBytes = await readFile(sourceAuth)
    try {
      await writeFile(authSnapshot, authBytes, { mode: 0o600, flag: 'wx' })
    } finally {
      authBytes.fill(0)
    }
    await writeFile(configPath, PERSISTENT_NATIVE_MINIMAL_CONFIG, { encoding: 'utf8', mode: 0o600, flag: 'wx' })
    await ensureRegularFile(authSnapshot, 'auth snapshot', 0o600)
    await ensureRegularFile(configPath, 'minimal config', 0o600)
    const entries = (await readdir(canonicalHome)).sort(unicodeCompare)
    if (canonicalJson(entries) !== canonicalJson([authFile, 'config.toml'].sort(unicodeCompare))) {
      throw new NativeAdapterError('isolated_home_contaminated', 'isolated CODEX_HOME contains inherited state')
    }
  } catch (error) {
    await rm(canonicalHome, { recursive: true, force: true }).catch(() => {})
    throw error
  }
  return {
    path: canonicalHome,
    mode: '0700',
    auth_snapshot: true,
    config_digest: sha256(PERSISTENT_NATIVE_MINIMAL_CONFIG),
  }
}

async function createToolCaptureCodexHome(runtimeRoot, baseUrl) {
  const canonicalRuntimeRoot = await realpath(runtimeRoot)
  const captureHome = join(canonicalRuntimeRoot, 'tool-capture-codex-home')
  if (await lstat(captureHome).catch(() => null)) {
    throw new NativeAdapterError(
      'tool_inventory_capture_unavailable',
      'tool inventory capture CODEX_HOME must be newly created',
    )
  }
  await mkdir(captureHome, { recursive: false, mode: 0o700 })
  const canonicalHome = await realpath(captureHome)
  const homeInfo = await lstat(captureHome)
  if (
    homeInfo.isSymbolicLink()
    || !homeInfo.isDirectory()
    || (homeInfo.mode & 0o777) !== 0o700
  ) {
    throw new NativeAdapterError(
      'tool_inventory_capture_unavailable',
      'tool inventory capture CODEX_HOME is unsafe',
    )
  }
  const capture = toolCaptureConfig(baseUrl)
  const configPath = join(canonicalHome, 'config.toml')
  try {
    await writeFile(configPath, capture.config, { encoding: 'utf8', mode: 0o600, flag: 'wx' })
    await ensureRegularFile(configPath, 'tool capture config', 0o600)
    const entries = await readdir(canonicalHome)
    if (canonicalJson(entries) !== canonicalJson(['config.toml'])) {
      throw new NativeAdapterError(
        'tool_inventory_capture_unavailable',
        'tool inventory capture CODEX_HOME contains inherited state',
      )
    }
  } catch (error) {
    await rm(canonicalHome, { recursive: true, force: true }).catch(() => {})
    throw error
  }
  return {
    path: canonicalHome,
    config_digest: sha256(capture.config),
    provider_delta_digest: sha256(canonicalJson(capture.provider_delta)),
  }
}

function boundedSpawn(binary, args, options = {}) {
  const result = spawnSync(binary, args, {
    cwd: options.cwd,
    env: options.env,
    encoding: 'utf8',
    shell: false,
    stdio: ['ignore', 'pipe', 'pipe'],
    maxBuffer: MAX_PROTOCOL_BYTES,
    timeout: options.timeoutMs || 20_000,
  })
  if (result.status !== 0) {
    throw new NativeAdapterError('binary_probe_failed', 'Codex binary probe failed', {
      status: result.status,
      signal: result.signal,
      stderr_bytes: Buffer.byteLength(String(result.stderr || ''), 'utf8'),
    })
  }
  return String(result.stdout || '').trim()
}

export function sanitizedEnvironment(base, codexHome, overrides = {}) {
  const allowed = ['PATH', 'LANG', 'LC_ALL', 'TMPDIR']
  const env = {}
  for (const key of allowed) {
    if (typeof base[key] === 'string') env[key] = base[key]
  }
  env.CODEX_HOME = codexHome
  env.NO_COLOR = '1'
  for (const [key, value] of Object.entries(overrides)) {
    if (!key.startsWith('FAKE_APP_SERVER_') || typeof value !== 'string') {
      throw new NativeAdapterError('environment_override_forbidden', 'test environment override is not allowed')
    }
    env[key] = value
  }
  return env
}

function exactFixedEnvironment(fixed, codexHome, overrides) {
  if (
    !fixed
    || typeof fixed !== 'object'
    || Array.isArray(fixed)
    || Object.keys(fixed).sort().join(',')
      !== ['LANG', 'LC_ALL', 'PATH', 'TMPDIR'].sort().join(',')
    || Object.values(fixed).some(value => typeof value !== 'string' || !value)
    || !isAbsolute(fixed.TMPDIR)
  ) {
    throw new NativeAdapterError(
      'environment_policy_invalid',
      'fixed environment must seal exact PATH, LANG, LC_ALL, and absolute TMPDIR',
    )
  }
  const env = {
    PATH: fixed.PATH,
    LANG: fixed.LANG,
    LC_ALL: fixed.LC_ALL,
    TMPDIR: fixed.TMPDIR,
    CODEX_HOME: codexHome,
    NO_COLOR: '1',
  }
  for (const [key, value] of Object.entries(overrides)) {
    if (!key.startsWith('FAKE_APP_SERVER_') || typeof value !== 'string') {
      throw new NativeAdapterError(
        'environment_override_forbidden',
        'test environment override is not allowed',
      )
    }
    env[key] = value
  }
  return env
}

export async function fingerprintAppServer({
  binary,
  cwd,
  env,
  isolatedHome,
  allowedVersions,
  allowedBinaryDigests,
  allowedSchemaDigests,
  expectedBinary = BUNDLED_CODEX_BINARY,
  processEnvOverrides = {},
  fixedProcessEnvironment = null,
  freshnessMs = 5 * 60_000,
  now = Date.now(),
}) {
  const canonicalBinary = await resolveBundledCodex(binary, expectedBinary)
  const canonicalCwd = await realpath(cwd)
  const processEnv = fixedProcessEnvironment
    ? exactFixedEnvironment(
      fixedProcessEnvironment,
      isolatedHome.path,
      processEnvOverrides,
    )
    : sanitizedEnvironment(env, isolatedHome.path, processEnvOverrides)
  const version = boundedSpawn(canonicalBinary, ['--version'], {
    cwd: canonicalCwd,
    env: processEnv,
  })
  const schemaRoot = await mkdtemp(join(tmpdir(), 'studio-app-server-schema-'))
  try {
    boundedSpawn(canonicalBinary, [
      'app-server', 'generate-json-schema', '--experimental', '--out', schemaRoot,
    ], { cwd: canonicalCwd, env: processEnv })
    const schemaPath = join(schemaRoot, 'codex_app_server_protocol.v2.schemas.json')
    let schema
    try {
      schema = JSON.parse(await readFile(schemaPath, 'utf8'))
    } catch {
      throw new NativeAdapterError('schema_probe_invalid', 'app-server schema is not canonical JSON')
    }
    const schemaDigest = sha256(canonicalJson(schema))
    const binaryDigest = sha256(await readFile(canonicalBinary))
    const allowlistDiagnostics = {
      version: {
        expected: [...allowedVersions],
        actual: version,
        matched: allowedVersions.includes(version),
      },
      binary_digest: {
        expected: [...allowedBinaryDigests],
        actual: binaryDigest,
        matched: allowedBinaryDigests.includes(binaryDigest),
      },
      schema_digest: {
        expected: [...allowedSchemaDigests],
        actual: schemaDigest,
        matched: allowedSchemaDigests.includes(schemaDigest),
      },
    }
    if (Object.values(allowlistDiagnostics).some(field => !field.matched)) {
      throw new NativeAdapterError('capability_allowlist_mismatch', 'binary/version/schema is outside the fresh allowlist', {
        allowlist_diagnostics: allowlistDiagnostics,
      })
    }
    const verifiedAt = new Date(now).toISOString()
    const expiresAt = new Date(now + freshnessMs).toISOString()
    return {
      canonicalBinary,
      canonicalCwd,
      processEnv,
      version,
      binaryDigest,
      schemaDigest,
      verifiedAt,
      expiresAt,
      environmentDigest: sha256(canonicalJson({
        binary_digest: binaryDigest,
        version,
        schema_digest: schemaDigest,
        workspace_digest: sha256(canonicalCwd),
        config_digest: isolatedHome.config_digest,
        process_environment: processEnv,
      })),
    }
  } finally {
    await rm(schemaRoot, { recursive: true, force: true })
  }
}

export class AppServerStdio {
  #binary
  #cwd
  #env
  #child = null
  #nextId = 1
  #pending = new Map()
  #notifications = []
  #waiters = new Set()
  #activeTurns = new Map()
  #forbiddenRequest = null
  #stdoutBuffer = ''
  #stderrBytes = 0
  #fatalError = null
  #closing = false
  #requestTimeoutMs
  #responseTombstones = new Set()
  #turnTombstones = new Set()
  #serverRequestHandler
  #processStartedHandler
  #serverRequestIds = new Set()
  #serverCallIds = new Set()
  #notificationBytes = 0
  #processExitPromise = null
  #processExitReceipt = null

  constructor({
    binary,
    cwd,
    env,
    requestTimeoutMs = 15_000,
    serverRequestHandler = null,
    processStartedHandler = null,
  }) {
    this.#binary = binary
    this.#cwd = cwd
    this.#env = env
    this.#requestTimeoutMs = requestTimeoutMs
    if (serverRequestHandler !== null && typeof serverRequestHandler !== 'function') {
      throw new NativeAdapterError(
        'server_request_handler_invalid',
        'server request handler must be a function',
      )
    }
    this.#serverRequestHandler = serverRequestHandler
    if (processStartedHandler !== null && typeof processStartedHandler !== 'function') {
      throw new NativeAdapterError(
        'process_started_handler_invalid',
        'process started handler must be a function',
      )
    }
    this.#processStartedHandler = processStartedHandler
  }

  get notifications() {
    return structuredClone(this.#notifications)
  }

  get forbiddenRequest() {
    return this.#forbiddenRequest ? structuredClone(this.#forbiddenRequest) : null
  }

  async start() {
    this.#child = spawn(this.#binary, ['app-server', '--stdio', '--strict-config'], {
      cwd: this.#cwd,
      env: this.#env,
      shell: false,
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    const child = this.#child
    this.#processExitPromise = new Promise(resolveExit => {
      child.once('exit', (code, signal) => {
        this.#processExitReceipt = Object.freeze({
          process_exited: true,
          pid: child.pid ?? null,
          exit_code: code,
          signal: signal ?? null,
        })
        resolveExit(this.#processExitReceipt)
        if (!this.#closing) {
          this.#failAll(new NativeAdapterError(
            'recovery_required',
            'app-server exited before cleanup',
          ))
        }
      })
    })
    this.#child.stdout.setEncoding('utf8')
    this.#child.stdout.on('data', chunk => this.#consumeStdout(chunk))
    this.#child.stderr.on('data', chunk => {
      this.#stderrBytes += chunk.length
      if (this.#stderrBytes > MAX_PROTOCOL_BYTES) {
        this.#protocolFatal(new NativeAdapterError(
          'stderr_limit_exceeded',
          'app-server stderr exceeded its bound',
        ))
      }
    })
    this.#child.once('error', () => {
      this.#failAll(new NativeAdapterError('recovery_required', 'app-server process failed'))
    })
    this.#child.stdout.once('close', () => {
      if (!this.#closing) {
        this.#failAll(new NativeAdapterError('recovery_required', 'app-server stdout closed'))
      }
    })
    if (this.#processStartedHandler) {
      try {
        await this.#processStartedHandler({ pid: child.pid })
        let alive = false
        if (Number.isInteger(child.pid) && child.pid > 0) {
          try {
            process.kill(child.pid, 0)
            alive = true
          } catch (error) {
            alive = error.code === 'EPERM'
          }
        }
        if (
          this.#child !== child
          || this.#processExitReceipt
          || child.exitCode !== null
          || child.signalCode !== null
          || !alive
        ) {
          throw new NativeAdapterError(
            'app_server_process_identity_missing',
            'spawned app-server exited before its durable identity fence',
          )
        }
      } catch (error) {
        const closeReceipt = await this.#killAndWait()
        if (closeReceipt.process_exited !== true) {
          throw new NativeAdapterError(
            'app_server_exit_unconfirmed',
            'app-server startup failure could not prove process exit',
            { cause: error.code || error.name },
          )
        }
        throw error
      }
    }
    const initialized = await this.#request('initialize', {
      clientInfo: { name: 'studio-persistent-native', title: 'Studio Persistent Native', version: '0.11.1' },
      capabilities: {
        experimentalApi: true,
        requestAttestation: false,
        optOutNotificationMethods: ['account/rateLimits/updated'],
      },
    })
    await this.#send({ method: 'initialized' })
    return initialized
  }

  #consumeStdout(chunk) {
    this.#stdoutBuffer += chunk
    if (Buffer.byteLength(this.#stdoutBuffer, 'utf8') > MAX_PROTOCOL_BYTES) {
      this.#protocolFatal(new NativeAdapterError(
        'output_limit_exceeded',
        'app-server stdout frame exceeded its bound',
      ))
      return
    }
    for (;;) {
      const newline = this.#stdoutBuffer.indexOf('\n')
      if (newline < 0) break
      const line = this.#stdoutBuffer.slice(0, newline)
      this.#stdoutBuffer = this.#stdoutBuffer.slice(newline + 1)
      if (line.trim()) this.#receive(line)
    }
  }

  async #send(message) {
    if (this.#fatalError) throw this.#fatalError
    if (!this.#child?.stdin?.writable) {
      throw new NativeAdapterError('app_server_eof', 'app-server stdin is closed')
    }
    const frame = `${JSON.stringify(message)}\n`
    if (Buffer.byteLength(frame, 'utf8') > MAX_PROTOCOL_BYTES) {
      throw new NativeAdapterError('request_limit_exceeded', 'app-server request exceeded its bound')
    }
    await new Promise((resolveWrite, rejectWrite) => {
      this.#child.stdin.write(frame, error => {
        if (error) {
          rejectWrite(new NativeAdapterError('recovery_required', 'app-server stdin write failed'))
        } else resolveWrite()
      })
    })
  }

  #request(method, params, timeoutMs = this.#requestTimeoutMs) {
    const id = this.#nextId++
    return new Promise((resolveRequest, rejectRequest) => {
      const timer = setTimeout(() => {
        this.#pending.delete(String(id))
        this.#responseTombstones.add(String(id))
        const error = new NativeAdapterError(
          'recovery_required',
          `${method} timed out and poisoned the app-server`,
          { cause: 'app_server_timeout' },
        )
        rejectRequest(error)
        this.#protocolFatal(error)
      }, timeoutMs)
      this.#pending.set(String(id), { method, resolve: resolveRequest, reject: rejectRequest, timer })
      void this.#send(params === undefined ? { id, method } : { id, method, params }).catch(error => {
        clearTimeout(timer)
        this.#pending.delete(String(id))
        rejectRequest(error)
      })
    })
  }

  #receive(line) {
    let message
    try {
      message = JSON.parse(line)
    } catch {
      this.#protocolFatal(new NativeAdapterError('protocol_invalid', 'app-server emitted non-JSON stdout'))
      return
    }
    if (!message || typeof message !== 'object' || Array.isArray(message)) {
      this.#protocolFatal(new NativeAdapterError('protocol_invalid', 'app-server emitted an invalid envelope'))
      return
    }
    if (message.method && message.id !== undefined) {
      if (message.method === 'item/tool/call' && this.#serverRequestHandler) {
        const requestId = String(message.id)
        const callId = message.params?.callId
        if (
          this.#serverRequestIds.has(requestId)
          || typeof callId !== 'string'
          || this.#serverCallIds.has(callId)
        ) {
          this.#denyServerRequest(message)
          return
        }
        this.#serverRequestIds.add(requestId)
        this.#serverCallIds.add(callId)
        void this.#handleServerRequest(message)
      } else {
        this.#denyServerRequest(message)
      }
      return
    }
    if (message.id !== undefined) {
      const pending = this.#pending.get(String(message.id))
      if (!pending) {
        if (this.#responseTombstones.delete(String(message.id))) return
        this.#protocolFatal(new NativeAdapterError(
          'protocol_correlation_invalid',
          'app-server emitted an unknown response id',
        ))
        return
      }
      clearTimeout(pending.timer)
      this.#pending.delete(String(message.id))
      if (message.error) {
        pending.reject(new NativeAdapterError('app_server_rpc_error', `${pending.method} failed`, {
          rpc_error: message.error,
        }))
      } else pending.resolve(message.result)
      return
    }
    if (
      message.method === 'remoteControl/status/changed'
      && message.params?.status !== 'disabled'
    ) {
      this.#protocolFatal(new NativeAdapterError(
        'unknown_capability',
        'remote control must remain disabled',
      ))
      return
    }
    if (
      message.method === 'deprecationNotice'
      && (
        typeof message.params?.summary !== 'string'
        || typeof message.params?.details !== 'string'
        || message.params.summary.length > 4096
        || message.params.details.length > 16 * 1024
      )
    ) {
      this.#protocolFatal(new NativeAdapterError(
        'protocol_event_invalid',
        'deprecation notice fields are invalid',
      ))
      return
    }
    if (message.method === 'thread/status/changed') {
      const status = message.params?.status
      const statusType = status?.type
      const keys = status && typeof status === 'object'
        ? Object.keys(status).sort(unicodeCompare)
        : []
      const valid = (
        typeof message.params?.threadId === 'string'
        && ['notLoaded', 'idle', 'systemError', 'active'].includes(statusType)
        && (
          (statusType === 'active'
            && canonicalJson(keys) === canonicalJson(['activeFlags', 'type'])
            && Array.isArray(status.activeFlags)
            && status.activeFlags.every(flag => (
              ['waitingOnApproval', 'waitingOnUserInput'].includes(flag)
            )))
          || (statusType !== 'active' && canonicalJson(keys) === canonicalJson(['type']))
        )
      )
      if (!valid) {
        this.#protocolFatal(new NativeAdapterError(
          'protocol_event_invalid',
          'thread status notification is invalid',
        ))
        return
      }
    }
    if (message.method === 'thread/settings/updated') {
      const settings = message.params?.threadSettings
      if (
        !UUID_V7.test(message.params?.threadId || '')
        || !settings
        || typeof settings !== 'object'
        || typeof settings.model !== 'string'
        || !settings.model
        || !(
          settings.effort === null
          || settings.effort === undefined
          || (typeof settings.effort === 'string' && settings.effort)
        )
      ) {
        this.#protocolFatal(new NativeAdapterError(
          'protocol_event_invalid',
          'thread settings notification is invalid',
        ))
        return
      }
    }
    if (message.method === 'thread/deleted') {
      const keys = message.params && typeof message.params === 'object'
        ? Object.keys(message.params).sort(unicodeCompare)
        : []
      if (
        canonicalJson(keys) !== canonicalJson(['threadId'])
        || !UUID_V7.test(message.params.threadId)
      ) {
        this.#protocolFatal(new NativeAdapterError(
          'protocol_event_invalid',
          'thread deleted notification is invalid',
        ))
        return
      }
    }
    if (typeof message.method !== 'string' || !KNOWN_NOTIFICATIONS.has(message.method)) {
      this.#protocolFatal(new NativeAdapterError(
        'protocol_event_unknown',
        'app-server emitted an unknown notification',
        {
          method: typeof message.method === 'string' ? message.method : 'invalid',
          parameter_keys: message.params && typeof message.params === 'object'
            ? Object.keys(message.params).sort(unicodeCompare)
            : [],
          status: typeof message.params?.status === 'string' ? message.params.status : null,
          state: typeof message.params?.state === 'string' ? message.params.state : null,
          enabled: typeof message.params?.enabled === 'boolean' ? message.params.enabled : null,
        },
      ))
      return
    }
    const eventTurnId = message.params?.turn?.id
    const eventThreadId = message.params?.threadId
    if (
      typeof eventTurnId === 'string'
      && typeof eventThreadId === 'string'
      && this.#turnTombstones.has(`${eventThreadId}:${eventTurnId}`)
    ) return
    const notificationBytes = Buffer.byteLength(JSON.stringify(message), 'utf8')
    if (
      this.#notifications.length >= 8192
      || this.#notificationBytes + notificationBytes > 16 * 1024 * 1024
    ) {
      this.#protocolFatal(new NativeAdapterError(
        'notification_limit_exceeded',
        'persistent app-server notification retention exceeded its bound',
      ))
      return
    }
    this.#notificationBytes += notificationBytes
    this.#notifications.push(message)
    if (message.method === 'turn/started') {
      this.#activeTurns.set(message.params.turn.id, message.params.threadId)
    } else if (message.method === 'turn/completed') {
      this.#activeTurns.delete(message.params.turn.id)
    }
    for (const waiter of [...this.#waiters]) {
      if (waiter.method !== message.method || !waiter.predicate(message.params)) continue
      clearTimeout(waiter.timer)
      this.#waiters.delete(waiter)
      waiter.resolve(message)
    }
  }

  async #handleServerRequest(message) {
    let handlerTimeout = null
    try {
      const result = await Promise.race([
        this.#serverRequestHandler({
          method: message.method,
          params: structuredClone(message.params),
          commandExec: params => this.commandExec(params),
        }),
        new Promise((_, reject) => {
          handlerTimeout = setTimeout(() => reject(new NativeAdapterError(
            'dynamic_tool_timeout',
            'dynamic tool handler exceeded its bounded deadline',
          )), 130_000)
        }),
      ])
      if (
        !result
        || typeof result !== 'object'
        || Array.isArray(result)
        || Object.keys(result).sort().join(',') !== 'contentItems,success'
        || typeof result.success !== 'boolean'
        || !Array.isArray(result.contentItems)
        || result.contentItems.length < 1
        || result.contentItems.length > 16
        || result.contentItems.some(item => (
          !item
          || typeof item !== 'object'
          || item.type !== 'inputText'
          || typeof item.text !== 'string'
          || Buffer.byteLength(item.text, 'utf8') > MAX_PROTOCOL_BYTES
        ))
      ) {
        throw new NativeAdapterError(
          'dynamic_tool_response_invalid',
          'dynamic tool handler returned an invalid response',
        )
      }
      await this.#send({ id: message.id, result })
    } catch (cause) {
      await this.#send({
        id: message.id,
        result: {
          success: false,
          contentItems: [{
            type: 'inputText',
            text: JSON.stringify({
              ok: false,
              code: String(cause?.code || 'dynamic_tool_rejected'),
            }),
          }],
        },
      }).catch(() => {})
      this.#forbiddenRequest = {
        method: message.method,
        received_at: new Date().toISOString(),
      }
      const threadId = message.params?.threadId
      const turnId = message.params?.turnId
      if (typeof threadId === 'string' && typeof turnId === 'string') {
        await this.interruptTurn(threadId, turnId).catch(() => {})
        this.tombstoneTurn(threadId, turnId)
      }
      this.#protocolFatal(new NativeAdapterError(
        'server_request_forbidden',
        'dynamic tool request failed the controller contract',
        {
          method: message.method,
          cause: cause?.code || 'dynamic_tool_rejected',
        },
      ))
    } finally {
      if (handlerTimeout) clearTimeout(handlerTimeout)
    }
  }

  #denyServerRequest(message) {
    this.#forbiddenRequest = {
      method: message.method,
      received_at: new Date().toISOString(),
    }
    let response
    if (['item/commandExecution/requestApproval', 'item/fileChange/requestApproval'].includes(message.method)) {
      response = { id: message.id, result: { decision: 'decline' } }
    } else if (['execCommandApproval', 'applyPatchApproval'].includes(message.method)) {
      response = { id: message.id, result: { decision: 'denied' } }
    } else {
      response = {
        id: message.id,
        error: { code: -32601, message: 'Studio Production adapter denies server-initiated requests' },
      }
    }
    const interruptTargets = new Map(this.#activeTurns)
    if (
      typeof message.params?.turnId === 'string'
      && typeof message.params?.threadId === 'string'
    ) {
      interruptTargets.set(message.params.turnId, message.params.threadId)
    }
    const interrupts = [...interruptTargets].map(([turnId, threadId]) => ({
      id: `studio-deny-${this.#nextId++}`,
      method: 'turn/interrupt',
      params: { threadId, turnId },
    }))
    const frames = [response, ...interrupts].map(frame => `${JSON.stringify(frame)}\n`).join('')
    this.#child.stdin.write(frames, () => {
      this.#failAll(new NativeAdapterError(
        'server_request_forbidden',
        'app-server issued a forbidden server request',
        { method: message.method },
      ))
      setTimeout(() => {
        void this.#killAndWait()
      }, 500)
    })
  }

  #protocolFatal(error) {
    this.#failAll(error)
    void this.#killAndWait()
  }

  #failAll(error) {
    this.#fatalError ||= error
    for (const pending of this.#pending.values()) {
      clearTimeout(pending.timer)
      pending.reject(this.#fatalError)
    }
    this.#pending.clear()
    for (const waiter of this.#waiters) {
      clearTimeout(waiter.timer)
      waiter.reject(this.#fatalError)
    }
    this.#waiters.clear()
  }

  waitFor(method, predicate, since = 0, timeoutMs = 15_000) {
    for (let index = since; index < this.#notifications.length; index += 1) {
      const message = this.#notifications[index]
      if (message.method === method && predicate(message.params)) return Promise.resolve(message)
    }
    if (this.#fatalError) return Promise.reject(this.#fatalError)
    return new Promise((resolveWait, rejectWait) => {
      const waiter = {
        method,
        predicate,
        resolve: resolveWait,
        reject: rejectWait,
        timer: setTimeout(() => {
          this.#waiters.delete(waiter)
          rejectWait(new NativeAdapterError('terminal_event_missing', `${method} was not observed`))
        }, timeoutMs),
      }
      this.#waiters.add(waiter)
    })
  }

  requestPreflight(method, params) {
    const allowed = new Set([
      'experimentalFeature/list', 'permissionProfile/list', 'hooks/list', 'skills/list',
      'plugin/list', 'app/list', 'mcpServerStatus/list',
    ])
    if (!allowed.has(method)) {
      throw new NativeAdapterError('adapter_surface_forbidden', `preflight method is not allowed: ${method}`)
    }
    return this.#request(method, params)
  }

  startThread(params) { return this.#request('thread/start', params) }
  listThreads(params) { return this.#request('thread/list', params) }
  readThread(params) { return this.#request('thread/read', params) }
  resumeThread(params) { return this.#request('thread/resume', params) }
  startTurn(params) { return this.#request('turn/start', params) }
  updateThreadSettings(params) { return this.#request('thread/settings/update', params) }
  commandExec(params) { return this.#request('command/exec', params) }
  terminateCommand(processId) {
    return this.#request('command/exec/terminate', { processId })
  }
  interruptTurn(threadId, turnId) {
    return this.#request('turn/interrupt', { threadId, turnId })
  }
  cleanTerminals(threadId) {
    return this.#request('thread/backgroundTerminals/clean', { threadId })
  }
  listTerminals(threadId) {
    return this.#request('thread/backgroundTerminals/list', { threadId })
  }
  deleteThread(threadId) { return this.#request('thread/delete', { threadId }) }

  notificationMark() {
    return this.#notifications.length
  }

  tombstoneTurn(threadId, turnId) {
    this.#turnTombstones.add(`${threadId}:${turnId}`)
  }

  isTurnTombstoned(threadId, turnId) {
    return this.#turnTombstones.has(`${threadId}:${turnId}`)
  }

  clearThreadTombstones(threadId) {
    const prefix = `${threadId}:`
    for (const key of this.#turnTombstones) {
      if (key.startsWith(prefix)) this.#turnTombstones.delete(key)
    }
  }

  poisonTurn(threadId, turnId, cause) {
    this.tombstoneTurn(threadId, turnId)
    this.#protocolFatal(new NativeAdapterError(
      'recovery_required',
      'turn lifecycle timed out and poisoned the app-server',
      { cause },
    ))
  }

  async #waitForProcessExit(timeoutMs) {
    if (this.#processExitReceipt) return this.#processExitReceipt
    if (!this.#processExitPromise) {
      return Object.freeze({
        process_exited: this.#child === null,
        pid: this.#child?.pid ?? null,
        exit_code: this.#child?.exitCode ?? null,
        signal: this.#child?.signalCode ?? null,
      })
    }
    return Promise.race([
      this.#processExitPromise,
      new Promise(resolveTimeout => setTimeout(() => resolveTimeout(Object.freeze({
        process_exited: false,
        pid: this.#child?.pid ?? null,
        exit_code: this.#child?.exitCode ?? null,
        signal: this.#child?.signalCode ?? null,
      })), timeoutMs)),
    ])
  }

  async #killAndWait() {
    if (!this.#child) {
      return Object.freeze({
        process_exited: true,
        pid: null,
        exit_code: null,
        signal: null,
      })
    }
    if (this.#processExitReceipt) return this.#processExitReceipt
    this.#closing = true
    if (this.#child.exitCode === null && this.#child.signalCode === null) {
      this.#child.kill('SIGTERM')
    }
    let receipt = await this.#waitForProcessExit(1_000)
    if (
      receipt.process_exited !== true
      && this.#child.exitCode === null
      && this.#child.signalCode === null
    ) {
      this.#child.kill('SIGKILL')
      receipt = await this.#waitForProcessExit(1_000)
    }
    return receipt
  }

  async close() {
    if (!this.#child) {
      return Object.freeze({
        process_exited: true,
        pid: null,
        exit_code: null,
        signal: null,
      })
    }
    if (this.#processExitReceipt) return this.#processExitReceipt
    this.#closing = true
    this.#child.stdin.end()
    const receipt = await this.#waitForProcessExit(2_000)
    return receipt.process_exited === true
      ? receipt
      : this.#killAndWait()
  }
}

async function startToolCaptureServer(timeoutMs) {
  let settleCapture
  let rejectCapture
  let settled = false
  const capture = new Promise((resolveCapture, rejectCapturePromise) => {
    settleCapture = resolveCapture
    rejectCapture = rejectCapturePromise
  })
  const server = createServer((request, response) => {
    if (settled) {
      response.writeHead(409, { 'content-type': 'application/json' })
      response.end('{"error":{"message":"capture already completed"}}')
      return
    }
    if (request.method !== 'POST' || request.url !== '/v1/responses') {
      settled = true
      const error = new NativeAdapterError(
        'tool_inventory_capture_invalid',
        'capture provider received an unexpected request',
        { method: request.method || null, path: request.url || null },
      )
      rejectCapture(error)
      response.writeHead(404, { 'content-type': 'application/json' })
      response.end('{"error":{"message":"unexpected capture request"}}')
      return
    }
    const chunks = []
    let bytes = 0
    request.on('data', chunk => {
      bytes += chunk.length
      if (bytes > MAX_PROTOCOL_BYTES) {
        settled = true
        rejectCapture(new NativeAdapterError(
          'tool_inventory_capture_invalid',
          'captured outbound model request exceeded its bound',
        ))
        request.destroy()
        return
      }
      chunks.push(chunk)
    })
    request.on('error', () => {
      if (settled) return
      settled = true
      rejectCapture(new NativeAdapterError(
        'tool_inventory_capture_unavailable',
        'capture provider request stream failed',
      ))
    })
    request.on('end', () => {
      if (settled) return
      try {
        const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        const tools = body?.tools ?? []
        if (!Array.isArray(tools)) {
          throw new NativeAdapterError(
            'tool_inventory_capture_invalid',
            'outbound model request tools must be absent or an array',
          )
        }
        if (tools.length !== 0) {
          const identities = tools.map(tool => {
            const type = typeof tool?.type === 'string' ? tool.type : 'invalid'
            const name = typeof tool?.name === 'string'
              ? tool.name
              : (typeof tool?.function?.name === 'string' ? tool.function.name : '')
            return `${type}:${name}`
          })
          throw new NativeAdapterError(
            'unknown_outbound_model_tool',
            'context-only Production requires an exact empty outbound tools array',
            { identities },
          )
        }
        settled = true
        settleCapture({
          model: typeof body.model === 'string' ? body.model : null,
          raw_tools: structuredClone(tools),
          descriptors: [],
          request_projection_digest: sha256(canonicalJson({
            model: body.model ?? null,
            tools,
            tool_choice: body.tool_choice ?? null,
            parallel_tool_calls: body.parallel_tool_calls ?? null,
            reasoning: body.reasoning ?? null,
          })),
        })
        response.writeHead(500, { 'content-type': 'application/json' })
        response.end('{"error":{"message":"Studio tool capture complete"}}')
      } catch (error) {
        settled = true
        rejectCapture(error instanceof NativeAdapterError
          ? error
          : new NativeAdapterError(
            'tool_inventory_capture_invalid',
            'capture provider received invalid JSON',
          ))
        response.writeHead(400, { 'content-type': 'application/json' })
        response.end('{"error":{"message":"invalid capture payload"}}')
      }
    })
  })
  await new Promise((resolveListen, rejectListen) => {
    server.once('error', rejectListen)
    server.listen(0, '127.0.0.1', () => {
      server.off('error', rejectListen)
      resolveListen()
    })
  }).catch(() => {
    throw new NativeAdapterError(
      'tool_inventory_capture_unavailable',
      'loopback capture provider could not listen',
    )
  })
  const address = server.address()
  if (!address || typeof address === 'string' || address.address !== '127.0.0.1') {
    server.close()
    throw new NativeAdapterError(
      'tool_inventory_capture_unavailable',
      'capture provider is not confined to IPv4 loopback',
    )
  }
  const timer = setTimeout(() => {
    if (settled) return
    settled = true
    rejectCapture(new NativeAdapterError(
      'tool_inventory_capture_unavailable',
      'outbound model tool inventory was not captured before timeout',
    ))
  }, timeoutMs)
  return {
    baseUrl: `http://127.0.0.1:${address.port}/v1`,
    capture: capture.finally(() => clearTimeout(timer)),
    async close() {
      server.closeAllConnections?.()
      await new Promise(resolveClose => server.close(() => resolveClose()))
    },
  }
}

async function captureOutboundToolInventory({
  binary,
  cwd,
  runtimeRoot,
  processEnv,
  model,
  effort,
  requestTimeoutMs,
}) {
  if (typeof model !== 'string' || !model) {
    throw new NativeAdapterError(
      'tool_inventory_capture_unavailable',
      'effective Production model is unavailable for tool capture',
    )
  }
  const provider = await startToolCaptureServer(requestTimeoutMs)
  let captureHome = null
  let transport = null
  try {
    captureHome = await createToolCaptureCodexHome(runtimeRoot, provider.baseUrl)
    const captureEnv = {
      ...processEnv,
      CODEX_HOME: captureHome.path,
      [TOOL_CAPTURE_TOKEN_ENV]: 'studio-loopback-capture-non-secret',
    }
    transport = new AppServerStdio({
      binary,
      cwd,
      env: captureEnv,
      requestTimeoutMs,
    })
    await transport.start()
    const thread = await transport.startThread({
      ephemeral: true,
      cwd,
      model,
      modelProvider: TOOL_CAPTURE_PROVIDER,
      approvalPolicy: 'never',
      permissions: ':read-only',
      environments: [],
      selectedCapabilityRoots: [],
      dynamicTools: [],
      runtimeWorkspaceRoots: [cwd],
      serviceName: 'studio-persistent-native-tool-capture',
    })
    const threadId = assertHostId(thread?.thread?.id, 'tool capture thread id')
    if (
      thread.model !== model
      || thread.modelProvider !== TOOL_CAPTURE_PROVIDER
      || thread.cwd !== cwd
      || thread.approvalPolicy !== 'never'
      || thread.activePermissionProfile?.id !== ':read-only'
      || thread.sandbox?.type !== 'readOnly'
      || thread.sandbox?.networkAccess !== false
      || !safeRuntimeRoots(thread.runtimeWorkspaceRoots, cwd)
      || thread.instructionSources?.length
    ) {
      throw new NativeAdapterError(
        'tool_inventory_capture_invalid',
        'capture thread did not preserve the effective Production policy',
      )
    }
    const mark = transport.notificationMark()
    const turnResponse = await transport.startTurn({
      threadId,
      input: [{
        type: 'text',
        text: 'Return exactly {"captured":true}. Do not call tools.',
      }],
      outputSchema: {
        type: 'object',
        additionalProperties: false,
        required: ['captured'],
        properties: { captured: { type: 'boolean' } },
      },
      clientUserMessageId: `studio-tool-capture-${sha256(model).slice(7, 39)}`,
      model,
      effort: effort ?? null,
      approvalPolicy: 'never',
      permissions: ':read-only',
      environments: [],
      runtimeWorkspaceRoots: [cwd],
    })
    const turnId = assertHostId(turnResponse?.turn?.id, 'tool capture turn id')
    const terminalBeforeCapture = transport.waitFor(
      'turn/completed',
      params => params?.threadId === threadId && params?.turn?.id === turnId,
      mark,
      requestTimeoutMs,
    ).then(notification => {
      throw new NativeAdapterError(
        'tool_inventory_capture_unavailable',
        'capture turn completed before a model request was observed',
        {
          status: notification.params?.turn?.status || null,
          error_kind: notification.params?.turn?.error
            ? Object.keys(notification.params.turn.error).sort(unicodeCompare)
            : [],
        },
      )
    })
    const captured = await Promise.race([provider.capture, terminalBeforeCapture])
    if (captured.model !== model) {
      throw new NativeAdapterError(
        'tool_inventory_capture_invalid',
        'captured request model differs from the admitted Production model',
        { admitted_model: model, captured_model: captured.model },
      )
    }
    const rawToolsDigest = sha256(canonicalJson(captured.raw_tools))
    const evidence = {
      schema: 'studio-native-tool-inventory-capture/v1',
      evidence_class: 'live-loopback-raw-request',
      captured: true,
      provider_scope: 'loopback-only',
      model,
      reasoning_effort: effort ?? null,
      tool_count: captured.raw_tools.length,
      tools: captured.descriptors,
      raw_tools_digest: rawToolsDigest,
      capture_ref: rawToolsDigest,
      request_projection_digest: captured.request_projection_digest,
      base_config_digest: PINNED_CONFIG_DIGEST,
      capture_config_digest: captureHome.config_digest,
      provider_delta_digest: captureHome.provider_delta_digest,
    }
    return deepFreeze({
      ...evidence,
      evidence_digest: sha256(canonicalJson(evidence)),
    })
  } finally {
    if (transport) await transport.close().catch(() => {})
    if (captureHome?.path) {
      await rm(captureHome.path, { recursive: true, force: true }).catch(() => {})
    }
    await provider.close().catch(() => {})
  }
}

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value
  for (const child of Object.values(value)) deepFreeze(child)
  return Object.freeze(value)
}

function deterministicTestToolInventoryCapture(model, effort) {
  const rawTools = []
  const rawToolsDigest = sha256(canonicalJson(rawTools))
  const base = {
    schema: 'studio-native-tool-inventory-capture/v1',
    evidence_class: 'deterministic-test-fixture',
    captured: true,
    provider_scope: 'fake-app-server-only',
    model,
    reasoning_effort: effort ?? null,
    tool_count: 0,
    tools: [],
    raw_tools_digest: rawToolsDigest,
    capture_ref: rawToolsDigest,
    request_projection_digest: sha256(canonicalJson({ model, tools: rawTools })),
    base_config_digest: PINNED_CONFIG_DIGEST,
    capture_config_digest: sha256('deterministic-test-capture-config'),
    provider_delta_digest: sha256('deterministic-test-provider-delta'),
  }
  return deepFreeze({ ...base, evidence_digest: sha256(canonicalJson(base)) })
}

function requireObject(value, code, message) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new NativeAdapterError(code, message)
  }
  return value
}

function exactPathList(actual, expected) {
  return (
    Array.isArray(actual)
    && actual.length === expected.length
    && actual.every((entry, index) => entry === expected[index])
  )
}

function safeRuntimeRoots(actual, cwd) {
  return exactPathList(actual, []) || exactPathList(actual, [cwd])
}

function pathWithin(root, candidate) {
  if (!isAbsolute(root) || !isAbsolute(candidate)) return false
  const child = relative(root, candidate)
  return Boolean(child)
    && child !== '..'
    && !child.startsWith(`..${process.platform === 'win32' ? '\\' : '/'}`)
    && !isAbsolute(child)
}

function assertStrictSchema(schema, at = '$') {
  requireObject(schema, 'output_schema_invalid', `${at} must be an object schema`)
  if (typeof schema.type !== 'string') {
    throw new NativeAdapterError('output_schema_invalid', `${at}.type must be explicit`)
  }
  const allowedKeywords = new Set(['type', 'description', 'enum'])
  if (schema.type === 'object') {
    allowedKeywords.add('additionalProperties')
    allowedKeywords.add('properties')
    allowedKeywords.add('required')
    if (schema.additionalProperties !== false) {
      throw new NativeAdapterError('output_schema_invalid', `${at} must deny additional properties`)
    }
    requireObject(schema.properties, 'output_schema_invalid', `${at}.properties must be an object`)
    const keys = Object.keys(schema.properties).sort(unicodeCompare)
    const required = Array.isArray(schema.required)
      ? [...schema.required].sort(unicodeCompare)
      : []
    if (canonicalJson(keys) !== canonicalJson(required)) {
      throw new NativeAdapterError('output_schema_invalid', `${at}.required must list every property exactly`)
    }
    for (const [key, child] of Object.entries(schema.properties)) {
      assertStrictSchema(child, `${at}.${key}`)
    }
  } else if (schema.type === 'array') {
    allowedKeywords.add('items')
    assertStrictSchema(schema.items, `${at}[]`)
  } else if (schema.type === 'string') {
    allowedKeywords.add('minLength')
  } else if (!['boolean', 'integer', 'number', 'null'].includes(schema.type)) {
    throw new NativeAdapterError('output_schema_invalid', `${at}.type is unsupported`)
  }
  const unknown = Object.keys(schema).filter(key => !allowedKeywords.has(key))
  if (unknown.length) {
    throw new NativeAdapterError('output_schema_invalid', `${at} contains unsupported schema keywords`)
  }
  return schema
}

function typeMatches(value, type) {
  if (type === 'object') return value !== null && typeof value === 'object' && !Array.isArray(value)
  if (type === 'array') return Array.isArray(value)
  if (type === 'integer') return Number.isInteger(value)
  if (type === 'number') return typeof value === 'number' && Number.isFinite(value)
  if (type === 'null') return value === null
  return typeof value === type
}

function validateValue(value, schema, at = '$') {
  if (!typeMatches(value, schema.type)) {
    throw new NativeAdapterError('output_schema_mismatch', `${at} does not match ${schema.type}`)
  }
  if (Array.isArray(schema.enum) && !schema.enum.some(candidate => Object.is(candidate, value))) {
    throw new NativeAdapterError('output_schema_mismatch', `${at} is outside enum`)
  }
  if (typeof value === 'string' && Number.isInteger(schema.minLength) && value.length < schema.minLength) {
    throw new NativeAdapterError('output_schema_mismatch', `${at} is shorter than minLength`)
  }
  if (schema.type === 'array') {
    value.forEach((entry, index) => validateValue(entry, schema.items, `${at}[${index}]`))
  }
  if (schema.type === 'object') {
    const expected = new Set(Object.keys(schema.properties))
    for (const key of schema.required) {
      if (!Object.hasOwn(value, key)) {
        throw new NativeAdapterError('output_schema_mismatch', `${at}.${key} is required`)
      }
    }
    for (const [key, child] of Object.entries(value)) {
      if (!expected.has(key)) {
        throw new NativeAdapterError('output_schema_mismatch', `${at}.${key} is not allowed`)
      }
      validateValue(child, schema.properties[key], `${at}.${key}`)
    }
  }
  return value
}

function assertHostId(value, label) {
  if (typeof value !== 'string' || !UUID_V7.test(value)) {
    throw new NativeAdapterError('host_identity_invalid', `${label} is not a host UUIDv7`)
  }
  return value
}

function inventoryArray(response, key, label) {
  const value = response?.[key]
  if (!Array.isArray(value)) {
    throw new NativeAdapterError('inventory_invalid', `${label} returned an invalid inventory`)
  }
  return value
}

export async function probePersistentNativeInventory({
  transport,
  cwd,
  threadId,
}) {
  async function paged(method, params) {
    const data = []
    const cursors = new Set()
    let cursor = null
    for (let page = 0; page < 100; page += 1) {
      const response = await transport.requestPreflight(method, {
        ...params,
        ...(cursor === null ? {} : { cursor }),
      })
      data.push(...inventoryArray(response, 'data', method))
      if (response.nextCursor === null || response.nextCursor === undefined) return data
      if (
        typeof response.nextCursor !== 'string'
        || !response.nextCursor
        || cursors.has(response.nextCursor)
      ) {
        throw new NativeAdapterError('inventory_invalid', `${method} returned an invalid cursor`)
      }
      cursors.add(response.nextCursor)
      cursor = response.nextCursor
    }
    throw new NativeAdapterError('inventory_invalid', `${method} exceeded the pagination bound`)
  }

  const features = await paged('experimentalFeature/list', { threadId })
  for (const feature of features) {
    if (
      feature?.enabled === true
      && feature?.stage !== 'removed'
      && !SAFE_ENABLED_FEATURES.has(feature.name)
    ) {
      throw new NativeAdapterError(
        'unknown_capability',
        'an unknown model capability is enabled',
        { feature: feature.name || 'unknown', stage: feature.stage || null },
      )
    }
  }
  const profiles = await paged('permissionProfile/list', { cwd })
  if (!profiles.some(profile => profile?.id === ':read-only' && profile.allowed === true)) {
    throw new NativeAdapterError(
      'readonly_profile_unavailable',
      'read-only permission profile is unavailable',
    )
  }
  const hooks = inventoryArray(await transport.requestPreflight(
    'hooks/list',
    { cwds: [cwd] },
  ), 'data', 'hooks')
  const skills = inventoryArray(await transport.requestPreflight(
    'skills/list',
    { cwds: [cwd], forceReload: true },
  ), 'data', 'skills')
  const plugins = await transport.requestPreflight('plugin/list', {
    cwds: [cwd],
    forceRefetch: false,
    marketplaceKinds: ['local'],
  })
  const marketplaces = inventoryArray(plugins, 'marketplaces', 'plugins')
  const apps = await paged('app/list', { threadId, forceRefetch: false })
  const mcp = await paged('mcpServerStatus/list', { threadId, detail: 'full' })
  if (
    hooks.some(entry => (
      entry?.hooks?.length || entry?.errors?.length || entry?.warnings?.length
    ))
    || skills.some(entry => entry?.skills?.length || entry?.errors?.length)
    || marketplaces.some(entry => entry?.plugins?.length)
    || plugins?.featuredPluginIds?.length
    || plugins?.marketplaceLoadErrors?.length
    || apps.length
    || mcp.length
  ) {
    throw new NativeAdapterError(
      'inherited_inventory',
      'hook/skill/plugin/app/MCP inventory is not empty',
    )
  }
  const enabledFeatures = features
    .filter(feature => feature?.enabled === true && feature?.stage !== 'removed')
    .map(feature => feature.name)
    .sort(unicodeCompare)
  return {
    enabled_features: enabledFeatures,
    enabled_local_execution_features: enabledFeatures
      .filter(name => ['shell_tool', 'unified_exec'].includes(name)),
    permission_profiles: profiles
      .filter(profile => profile?.allowed === true)
      .map(profile => profile.id)
      .sort(unicodeCompare),
    hooks: 0,
    skills: 0,
    plugins: 0,
    apps: 0,
    mcp_servers: 0,
  }
}

function roleReference(actorId) {
  return deepFreeze({
    schema: 'studio-native-role-reference/v1',
    actor_ref: sha256(`actor:${actorId}`),
  })
}

function denialKind(output) {
  const value = String(output || '')
  if (/\bEPERM\b|operation not permitted/i.test(value)) return 'eperm'
  if (/permission denied/i.test(value)) return 'permission_denied'
  if (/read-only file system/i.test(value)) return 'readonly_filesystem'
  if (/declined|denied|not allowed|policy/i.test(value)) return 'policy_denied'
  return null
}

function validateResolvedProfile(profile, actorId) {
  const fields = new Set([
    'schema',
    'actor_id',
    'phase',
    'step',
    'role_id',
    'agent_id',
    'model',
    'effort',
    'policy_digest',
  ])
  if (
    !profile
    || typeof profile !== 'object'
    || Array.isArray(profile)
    || Object.keys(profile).length !== fields.size
    || Object.keys(profile).some(key => !fields.has(key))
    || profile.schema !== RESOLVED_PROFILE_SCHEMA
    || profile.actor_id !== actorId
    || [profile.phase, profile.step, profile.role_id, profile.agent_id]
      .some(value => typeof value !== 'string' || !value.trim())
    || !/^sha256:[0-9a-f]{64}$/.test(profile.policy_digest || '')
  ) {
    throw new NativeAdapterError(
      'agent_policy_invalid',
      'native action requires the exact controller-resolved agent profile',
    )
  }
  for (const field of ['model', 'effort']) {
    if (
      profile[field] !== null
      && (typeof profile[field] !== 'string' || !profile[field].trim())
    ) {
      throw new NativeAdapterError(
        'agent_policy_invalid',
        `resolved ${field} must be a non-empty string or null`,
      )
    }
  }
  return deepFreeze(structuredClone(profile))
}

function inheritedResolvedProfile(actorId) {
  return deepFreeze({
    schema: RESOLVED_PROFILE_SCHEMA,
    actor_id: actorId,
    phase: 'Inherited',
    step: 'inherit',
    role_id: actorId,
    agent_id: actorId,
    model: null,
    effort: null,
    policy_digest: sha256('studio-native-inherited-agent-policy/v1'),
  })
}

class PersistentNativeAppServer {
  #options
  #transport = null
  #fingerprint = null
  #isolatedHome = null
  #admissionEvidence = null
  #capability = null
  #defaultProfile = null
  #rolesByActor = new Map()
  #startingActors = new Set()
  #roles = new WeakMap()
  #turns = new WeakMap()
  #receipts = new WeakSet()
  #hostThreadIds = new Set()
  #hostTurnIds = new Set()
  #actionIds = new Set()
  #observationCheckpoints = new Set()
  #workflowLeaseActive = false
  #workflowLeaseClosed = false
  #closed = false

  constructor(options) {
    this.#options = options
  }

  async admit() {
    if (this.#capability) return this.#capability
    const runtimeRoot = await realpath(this.#options.runtimeRoot)
    const sourceCodexHome = await realpath(this.#options.sourceCodexHome)
    try {
      this.#isolatedHome = await createIsolatedCodexHome({ runtimeRoot, sourceCodexHome })
      if (this.#isolatedHome.config_digest !== PINNED_CONFIG_DIGEST) {
        throw new NativeAdapterError('config_identity_mismatch', 'minimal config digest is not pinned')
      }
      this.#fingerprint = await fingerprintAppServer({
        binary: this.#options.binary,
        expectedBinary: this.#options.expectedBinary,
        cwd: this.#options.cwd,
        env: this.#options.env,
        processEnvOverrides: this.#options.processEnvOverrides,
        isolatedHome: this.#isolatedHome,
        allowedVersions: this.#options.allowedVersions,
        allowedBinaryDigests: this.#options.allowedBinaryDigests,
        allowedSchemaDigests: this.#options.allowedSchemaDigests,
        freshnessMs: this.#options.freshnessMs,
        now: this.#options.now(),
      })
      this.#transport = new AppServerStdio({
        binary: this.#fingerprint.canonicalBinary,
        cwd: this.#fingerprint.canonicalCwd,
        env: this.#fingerprint.processEnv,
        requestTimeoutMs: this.#options.requestTimeoutMs,
      })
      await this.#transport.start()
      const materializedSkills = join(this.#isolatedHome.path, 'skills')
      if (await lstat(materializedSkills).catch(() => null)) {
        await rm(materializedSkills, { recursive: true, force: true })
      }
      if (await lstat(materializedSkills).catch(() => null)) {
        throw new NativeAdapterError(
          'system_skill_cleanup_failed',
          'materialized system skills remain in isolated CODEX_HOME',
        )
      }
      this.#isolatedHome.system_skills_removed = true
      await rm(join(this.#isolatedHome.path, 'auth.json'), { force: false })
      if (await lstat(join(this.#isolatedHome.path, 'auth.json')).catch(() => null)) {
        throw new NativeAdapterError('auth_snapshot_cleanup_failed', 'auth snapshot remains after initialize')
      }
      this.#isolatedHome.auth_snapshot = false
      this.#isolatedHome.auth_snapshot_removed = true
      const probe = await this.#startThread(false)
      this.#defaultProfile = deepFreeze({
        model: probe.response.model,
        effort: probe.response.reasoningEffort ?? null,
      })
      const inventory = await this.#probeInventory(probe.threadId)
      const toolInventoryCapture = this.#options.authority === 'production'
        ? await captureOutboundToolInventory({
          binary: this.#fingerprint.canonicalBinary,
          cwd: this.#fingerprint.canonicalCwd,
          runtimeRoot,
          processEnv: this.#fingerprint.processEnv,
          model: probe.response.model,
          effort: probe.response.reasoningEffort,
          requestTimeoutMs: this.#options.requestTimeoutMs,
        })
        : deterministicTestToolInventoryCapture(
          probe.response.model,
          probe.response.reasoningEffort,
        )
      if (inventory.enabled_local_execution_features.length !== 0) {
        throw new NativeAdapterError(
          'unknown_capability',
          'context-only Production requires no enabled local execution features',
        )
      }
      if (
        toolInventoryCapture.tool_count !== 0
        || toolInventoryCapture.tools.length !== 0
      ) {
        throw new NativeAdapterError(
          'unknown_outbound_model_tool',
          'context-only Production requires an exact empty captured tool inventory',
        )
      }
      await this.#cleanupThread(probe.threadId, probe.rolloutPath)
      this.#assertNoInheritedNotifications()
      const admissionEvidence = {
        schema: 'studio-native-admission-evidence/v1',
        protocol: APP_SERVER_PROTOCOL,
        contract_stability: APP_SERVER_CONTRACT_STABILITY,
        experimental_api: true,
        version: this.#fingerprint.version,
        binary_digest: this.#fingerprint.binaryDigest,
        schema_digest: this.#fingerprint.schemaDigest,
        config_digest: this.#isolatedHome.config_digest,
        environment_digest: this.#fingerprint.environmentDigest,
        auth_snapshot_removed: true,
        system_skills_removed: true,
        model_tool_surface: 'context-only-empty',
        repository_mutation_allowed: false,
        agent_tool_network_access: false,
        sandbox_network_access: false,
        provider_model_transport: 'required-outside-agent-tool-sandbox',
        auth_snapshot_hygiene_only: true,
        credential_confidentiality_guaranteed: false,
        same_user_filesystem_read_confidentiality: 'out-of-scope',
        inventory,
        tool_inventory_capture: toolInventoryCapture,
      }
      this.#admissionEvidence = deepFreeze({
        ...admissionEvidence,
        evidence_digest: sha256(canonicalJson(admissionEvidence)),
      })
      this.#capability = deepFreeze({
        schema: NATIVE_CAPABILITY_SCHEMA,
        protocol: APP_SERVER_PROTOCOL,
        contract_stability: APP_SERVER_CONTRACT_STABILITY,
        experimental_api: true,
        verified: true,
        persistent_roles: true,
        structured_result: true,
        interrupt_cancel: true,
        adapter_owned: true,
        version: this.#fingerprint.version,
        binary_digest: this.#fingerprint.binaryDigest,
        schema_digest: this.#fingerprint.schemaDigest,
        config_digest: this.#isolatedHome.config_digest,
        auth_snapshot_removed: true,
        system_skills_removed: true,
        model_tool_surface: 'context-only-empty',
        repository_mutation_allowed: false,
        agent_tool_network_access: false,
        sandbox_network_access: false,
        provider_model_transport: 'required-outside-agent-tool-sandbox',
        auth_snapshot_hygiene_only: true,
        credential_confidentiality_guaranteed: false,
        same_user_filesystem_read_confidentiality: 'out-of-scope',
        admission_evidence_digest: this.#admissionEvidence.evidence_digest,
        inventory_evidence: this.#admissionEvidence.inventory,
        tool_inventory_capture: this.#admissionEvidence.tool_inventory_capture,
        environment_digest: this.#fingerprint.environmentDigest,
        verified_at: this.#fingerprint.verifiedAt,
        expires_at: this.#fingerprint.expiresAt,
      })
      authorityRegistry(
        this.#options.authority,
        PRODUCTION_CAPABILITIES,
        TEST_CAPABILITIES,
      ).add(this.#capability)
      return this.#capability
    } catch (error) {
      await this.close().catch(() => {})
      throw error
    }
  }

  #assertCapability(capability, { requiresFreshDispatch = false } = {}) {
    if (this.#closed) throw new NativeAdapterError('adapter_closed', 'native adapter is closed')
    if (!this.#capability || capability !== this.#capability) {
      throw new NativeAdapterError('capability_not_adapter_owned', 'capability was not minted by this adapter')
    }
    if (requiresFreshDispatch && this.#workflowLeaseClosed) {
      throw new NativeAdapterError(
        'workflow_lease_closed',
        'native adapter workflow lease was already closed',
      )
    }
    if (
      requiresFreshDispatch
      && !this.#workflowLeaseActive
      && this.#options.now() >= Date.parse(this.#capability.expires_at)
    ) {
      throw new NativeAdapterError('capability_stale', 'native capability freshness window expired')
    }
  }

  #threadParams(ephemeral, model = null) {
    const params = {
      ephemeral,
      cwd: this.#fingerprint.canonicalCwd,
      allowProviderModelFallback: false,
      approvalPolicy: 'never',
      permissions: ':read-only',
      environments: [],
      selectedCapabilityRoots: [],
      dynamicTools: [],
      runtimeWorkspaceRoots: [this.#fingerprint.canonicalCwd],
      serviceName: 'studio-persistent-native',
    }
    if (model !== null) params.model = model
    return params
  }

  #validateThreadResponse(response, ephemeral, {
    expectedModel = null,
    expectedEffort = undefined,
  } = {}) {
    const value = requireObject(response, 'thread_policy_invalid', 'thread/start returned no policy')
    const threadId = assertHostId(value.thread?.id, 'thread id')
    const rolloutPath = value.thread?.path
    if (this.#hostThreadIds.has(threadId)) {
      throw new NativeAdapterError('host_identity_reused', 'app-server reused a host thread id')
    }
    if (
      value.thread?.ephemeral !== ephemeral
      || (ephemeral
        ? rolloutPath !== null
        : (
          typeof rolloutPath !== 'string'
          || !pathWithin(this.#isolatedHome.path, rolloutPath)
        ))
      || value.cwd !== this.#fingerprint.canonicalCwd
      || typeof value.model !== 'string'
      || !value.model
      || (expectedModel !== null && value.model !== expectedModel)
      || !(
        value.reasoningEffort === null
        || value.reasoningEffort === undefined
        || (typeof value.reasoningEffort === 'string' && value.reasoningEffort)
      )
      || (expectedEffort !== undefined && (value.reasoningEffort ?? null) !== expectedEffort)
      || value.approvalPolicy !== 'never'
      || value.activePermissionProfile?.id !== ':read-only'
      || value.sandbox?.type !== 'readOnly'
      || value.sandbox?.networkAccess !== false
      || !safeRuntimeRoots(value.runtimeWorkspaceRoots, this.#fingerprint.canonicalCwd)
      || !Array.isArray(value.instructionSources)
      || value.instructionSources.length !== 0
    ) {
      throw new NativeAdapterError(
        'thread_policy_invalid',
        'host effective thread policy is not isolated read-only',
        {
          cwd_matches: value.cwd === this.#fingerprint.canonicalCwd,
          expected_model: expectedModel,
          actual_model: value.model ?? null,
          expected_effort: expectedEffort ?? null,
          actual_effort: value.reasoningEffort ?? null,
          approval_policy: value.approvalPolicy || null,
          permission_profile: value.activePermissionProfile?.id || null,
          sandbox_type: value.sandbox?.type || null,
          sandbox_network_access: value.sandbox?.networkAccess ?? null,
          runtime_roots_match: safeRuntimeRoots(
            value.runtimeWorkspaceRoots,
            this.#fingerprint.canonicalCwd,
          ),
          runtime_roots: Array.isArray(value.runtimeWorkspaceRoots)
            ? value.runtimeWorkspaceRoots
            : null,
          instruction_source_count: Array.isArray(value.instructionSources)
            ? value.instructionSources.length
            : null,
          ephemeral: value.thread?.ephemeral ?? null,
          rollout_path_present: typeof rolloutPath === 'string',
          rollout_path_confined: typeof rolloutPath === 'string'
            ? pathWithin(this.#isolatedHome.path, rolloutPath)
            : false,
        },
      )
    }
    this.#hostThreadIds.add(threadId)
    return { threadId, rolloutPath, response: value }
  }

  async #startThread(ephemeral = false, profile = null) {
    const expectedModel = profile?.model ?? null
    const response = await this.#transport.startThread(
      this.#threadParams(ephemeral, expectedModel),
    )
    return this.#validateThreadResponse(response, ephemeral, { expectedModel })
  }

  async #pagedInventory(method, params) {
    const data = []
    const cursors = new Set()
    let cursor = null
    for (let page = 0; page < 100; page += 1) {
      const response = await this.#transport.requestPreflight(method, {
        ...params,
        ...(cursor === null ? {} : { cursor }),
      })
      data.push(...inventoryArray(response, 'data', method))
      if (response.nextCursor === null || response.nextCursor === undefined) return data
      if (
        typeof response.nextCursor !== 'string'
        || !response.nextCursor
        || cursors.has(response.nextCursor)
      ) {
        throw new NativeAdapterError('inventory_invalid', `${method} returned an invalid cursor`)
      }
      cursors.add(response.nextCursor)
      cursor = response.nextCursor
    }
    throw new NativeAdapterError('inventory_invalid', `${method} exceeded the pagination bound`)
  }

  async #probeInventory(threadId) {
    const features = await this.#pagedInventory(
      'experimentalFeature/list',
      { threadId },
    )
    for (const feature of features) {
      if (
        feature?.enabled === true
        && feature?.stage !== 'removed'
        && !SAFE_ENABLED_FEATURES.has(feature.name)
      ) {
        throw new NativeAdapterError(
          'unknown_capability',
          'an unknown model capability is enabled',
          { feature: feature.name || 'unknown', stage: feature.stage || null },
        )
      }
    }

    const profiles = await this.#pagedInventory(
      'permissionProfile/list',
      { cwd: this.#fingerprint.canonicalCwd },
    )
    if (!profiles.some(profile => profile?.id === ':read-only' && profile.allowed === true)) {
      throw new NativeAdapterError('readonly_profile_unavailable', 'read-only permission profile is unavailable')
    }

    const hooks = inventoryArray(await this.#transport.requestPreflight(
      'hooks/list',
      { cwds: [this.#fingerprint.canonicalCwd] },
    ), 'data', 'hooks')
    if (hooks.some(entry => (
      entry?.hooks?.length || entry?.errors?.length || entry?.warnings?.length
    ))) {
      throw new NativeAdapterError('inherited_inventory', 'hook inventory is not empty')
    }

    const skills = inventoryArray(await this.#transport.requestPreflight(
      'skills/list',
      { cwds: [this.#fingerprint.canonicalCwd], forceReload: true },
    ), 'data', 'skills')
    if (skills.some(entry => entry?.skills?.length || entry?.errors?.length)) {
      throw new NativeAdapterError(
        'inherited_inventory',
        'skill inventory is not empty',
        {
          skill_entries: skills.flatMap(entry => (entry?.skills || []).map(skill => ({
            name: skill?.name || null,
            enabled: skill?.enabled ?? null,
            scope: skill?.scope || null,
            path: skill?.path || null,
          }))),
          error_count: skills.reduce((sum, entry) => sum + (entry?.errors?.length || 0), 0),
        },
      )
    }

    const plugins = await this.#transport.requestPreflight('plugin/list', {
      cwds: [this.#fingerprint.canonicalCwd],
      forceRefetch: false,
      marketplaceKinds: ['local'],
    })
    const marketplaces = inventoryArray(plugins, 'marketplaces', 'plugins')
    if (
      marketplaces.some(entry => entry?.plugins?.length)
      || plugins?.featuredPluginIds?.length
      || plugins?.marketplaceLoadErrors?.length
    ) {
      throw new NativeAdapterError('inherited_inventory', 'plugin inventory is not empty')
    }

    const apps = await this.#pagedInventory(
      'app/list',
      { threadId, forceRefetch: false },
    )
    if (apps.length) throw new NativeAdapterError('inherited_inventory', 'app inventory is not empty')

    const mcp = await this.#pagedInventory(
      'mcpServerStatus/list',
      { threadId, detail: 'full' },
    )
    if (mcp.length) throw new NativeAdapterError('inherited_inventory', 'MCP inventory is not empty')
    const enabledFeatures = features
      .filter(feature => feature?.enabled === true && feature?.stage !== 'removed')
      .map(feature => feature.name)
      .sort(unicodeCompare)
    const removedFeatures = features
      .filter(feature => feature?.stage === 'removed')
      .map(feature => feature.name)
      .sort(unicodeCompare)
    return {
      enabled_features: enabledFeatures,
      removed_features: removedFeatures,
      enabled_local_execution_features: enabledFeatures
        .filter(name => ['shell_tool', 'unified_exec'].includes(name)),
      permission_profiles: profiles
        .filter(profile => profile?.allowed === true)
        .map(profile => profile.id)
        .sort(unicodeCompare),
      hooks: hooks.reduce((sum, entry) => sum + (entry?.hooks?.length || 0), 0),
      hook_errors: hooks.reduce((sum, entry) => sum + (entry?.errors?.length || 0), 0),
      hook_warnings: hooks.reduce((sum, entry) => sum + (entry?.warnings?.length || 0), 0),
      skills: skills.reduce((sum, entry) => sum + (entry?.skills?.length || 0), 0),
      skill_errors: skills.reduce((sum, entry) => sum + (entry?.errors?.length || 0), 0),
      plugins: marketplaces.reduce((sum, entry) => sum + (entry?.plugins?.length || 0), 0),
      plugin_load_errors: plugins?.marketplaceLoadErrors?.length || 0,
      apps: apps.length,
      mcp_servers: mcp.length,
    }
  }

  #assertNoInheritedNotifications() {
    const inherited = this.#transport.notifications.find(message => (
      typeof message?.method === 'string' && FORBIDDEN_NOTIFICATION.test(message.method)
    ))
    if (inherited) {
      throw new NativeAdapterError(
        'inherited_capability_notification',
        'app-server announced an inherited capability',
        { method: inherited.method },
      )
    }
  }

  async startRole(capability, { actorId, profile }) {
    this.#assertCapability(capability, { requiresFreshDispatch: true })
    if (typeof actorId !== 'string' || !actorId.trim() || actorId.length > 256) {
      throw new NativeAdapterError('actor_invalid', 'actorId must be a bounded non-empty string')
    }
    const explicitPolicy = profile !== undefined
    const resolvedProfile = explicitPolicy
      ? validateResolvedProfile(profile, actorId)
      : inheritedResolvedProfile(actorId)
    if (this.#rolesByActor.has(actorId)) return this.#rolesByActor.get(actorId).handle
    if (this.#startingActors.has(actorId)) {
      throw new NativeAdapterError(
        'actor_already_bound',
        'actor role binding is already in progress',
      )
    }
    this.#startingActors.add(actorId)
    try {
      const thread = await this.#startThread(false, resolvedProfile)
      const handle = roleReference(actorId)
      const record = {
        actorId,
        handle,
        threadId: thread.threadId,
        rolloutPath: thread.rolloutPath,
        inheritedModel: this.#defaultProfile.model,
        inheritedEffort: this.#defaultProfile.effort,
        currentModel: thread.response.model,
        currentEffort: thread.response.reasoningEffort ?? null,
        policyDigest: resolvedProfile.policy_digest,
        explicitPolicy,
        initialProfile: resolvedProfile,
        activeTurns: new Set(),
        operation: null,
        cleaned: false,
      }
      this.#roles.set(handle, record)
      this.#rolesByActor.set(actorId, record)
      this.#workflowLeaseActive = true
      return handle
    } finally {
      this.#startingActors.delete(actorId)
    }
  }

  inspectAdmissionEvidence(capability) {
    this.#assertCapability(capability)
    return this.#admissionEvidence
  }

  inspectSecurityEvidence(capability) {
    this.#assertCapability(capability)
    return deepFreeze({
      schema: 'studio-native-security-evidence/v1',
      auth_snapshot_removed: this.#isolatedHome?.auth_snapshot_removed === true,
      system_skills_removed: this.#isolatedHome?.system_skills_removed === true,
      model_tool_surface: 'context-only-empty',
      repository_mutation_allowed: false,
      agent_tool_network_access: false,
      sandbox_network_access: false,
      provider_model_transport: 'required-outside-agent-tool-sandbox',
      auth_snapshot_hygiene_only: true,
      credential_confidentiality_guaranteed: false,
      same_user_filesystem_read_confidentiality: 'out-of-scope',
      forbidden_request: this.#transport?.forbiddenRequest || null,
      environment_digest: this.#fingerprint.environmentDigest,
      config_digest: this.#isolatedHome.config_digest,
    })
  }

  async observeAuthSnapshotAbsence(capability, { checkpoint }) {
    this.#assertCapability(capability)
    if (
      typeof checkpoint !== 'string'
      || !/^[a-z0-9][a-z0-9:_-]{0,127}$/i.test(checkpoint)
      || this.#observationCheckpoints.has(checkpoint)
    ) {
      throw new NativeAdapterError(
        'observation_checkpoint_invalid',
        'auth observation checkpoint must be unique and bounded',
      )
    }
    this.#observationCheckpoints.add(checkpoint)
    const authPath = join(this.#isolatedHome.path, 'auth.json')
    const absent = (await lstat(authPath).catch(() => null)) === null
    if (!absent) {
      throw new NativeAdapterError(
        'auth_snapshot_reappeared',
        'isolated auth snapshot reappeared after initialization',
      )
    }
    const base = {
      schema: 'studio-native-auth-absence-observation/v1',
      evidence_class: 'trusted-local-observation',
      checkpoint,
      absent: true,
      observed_at: new Date(this.#options.now()).toISOString(),
      auth_path_ref: sha256(`auth-path:${authPath}`),
      config_digest: this.#isolatedHome.config_digest,
      environment_digest: this.#fingerprint.environmentDigest,
    }
    const observation = deepFreeze({
      ...base,
      evidence_digest: sha256(canonicalJson(base)),
    })
    authorityRegistry(
      this.#options.authority,
      PRODUCTION_OBSERVATIONS,
      TEST_OBSERVATIONS,
    ).add(observation)
    return observation
  }

  async probeReadOnlyWriteDenial(capability, { target }) {
    this.#assertCapability(capability)
    if (
      typeof target !== 'string'
      || !isAbsolute(target)
      || !/^studio-live-canary-write-probe(?:-[a-z0-9]+)?\.txt$/i.test(basename(target))
    ) {
      throw new NativeAdapterError(
        'write_probe_target_invalid',
        'write probe target must be a dedicated synthetic canary file',
      )
    }
    const parent = await realpath(dirname(target)).catch(() => null)
    if (
      parent !== this.#fingerprint.canonicalCwd
      || await lstat(target).catch(() => null)
    ) {
      throw new NativeAdapterError(
        'write_probe_target_invalid',
        'write probe target must be absent directly below the admitted cwd',
      )
    }
    const argv = ['/usr/bin/touch', '--', target]
    const response = await this.#transport.commandExec({
      command: argv,
      cwd: this.#fingerprint.canonicalCwd,
      permissionProfile: ':read-only',
      env: {},
      timeoutMs: 5_000,
      outputBytesCap: 4_096,
      tty: false,
      streamStdin: false,
      streamStdoutStderr: false,
    })
    if (
      !Number.isInteger(response?.exitCode)
      || typeof response.stdout !== 'string'
      || typeof response.stderr !== 'string'
      || Buffer.byteLength(response.stdout, 'utf8') > 4_096
      || Buffer.byteLength(response.stderr, 'utf8') > 4_096
    ) {
      throw new NativeAdapterError(
        'write_probe_invalid',
        'command/exec returned invalid bounded write-denial evidence',
      )
    }
    const targetAbsent = (await lstat(target).catch(() => null)) === null
    const deniedAs = denialKind(response.stderr)
    if (
      response.exitCode === 0
      || !targetAbsent
      || !['eperm', 'permission_denied', 'readonly_filesystem', 'policy_denied']
        .includes(deniedAs)
    ) {
      throw new NativeAdapterError(
        'readonly_write_denial_unproven',
        'read-only command/exec did not prove a denied synthetic write',
        {
          exit_code: response.exitCode,
          target_absent: targetAbsent,
          denial_kind: deniedAs,
        },
      )
    }
    const base = {
      schema: 'studio-native-readonly-write-probe/v1',
      evidence_class: 'trusted-local-observation',
      command_argv: argv,
      command_digest: sha256(canonicalJson(argv)),
      cwd_ref: sha256(this.#fingerprint.canonicalCwd),
      target_ref: sha256(target),
      permission_profile: ':read-only',
      sandbox_mode: 'readOnly',
      sandbox_network_access: false,
      exit_code: response.exitCode,
      denial_kind: deniedAs,
      target_absent: true,
      stdout_digest: sha256(response.stdout),
      stderr_digest: sha256(response.stderr),
      config_digest: this.#isolatedHome.config_digest,
      environment_digest: this.#fingerprint.environmentDigest,
    }
    const observation = deepFreeze({
      ...base,
      evidence_digest: sha256(canonicalJson(base)),
    })
    authorityRegistry(
      this.#options.authority,
      PRODUCTION_OBSERVATIONS,
      TEST_OBSERVATIONS,
    ).add(observation)
    return observation
  }

  async resumeRole(capability, roleHandle) {
    this.#assertCapability(capability)
    const role = this.#requireRole(roleHandle)
    if (role.activeTurns.size || role.operation) {
      throw new NativeAdapterError('actor_turn_active', 'role thread has an active lifecycle operation')
    }
    role.operation = 'resume'
    try {
      const response = await this.#transport.resumeThread({
        threadId: role.threadId,
        ...this.#threadParams(false, role.currentModel),
      })
      const threadId = assertHostId(response?.thread?.id, 'resumed thread id')
      if (
        threadId !== role.threadId
        || response.thread?.ephemeral !== false
        || response.thread?.path !== role.rolloutPath
        || response.cwd !== this.#fingerprint.canonicalCwd
        || response.model !== role.currentModel
        || (response.reasoningEffort ?? null) !== role.currentEffort
        || response.approvalPolicy !== 'never'
        || response.activePermissionProfile?.id !== ':read-only'
        || response.sandbox?.type !== 'readOnly'
        || response.sandbox?.networkAccess !== false
        || !safeRuntimeRoots(response.runtimeWorkspaceRoots, this.#fingerprint.canonicalCwd)
        || response.instructionSources?.length
      ) {
        throw new NativeAdapterError('thread_policy_invalid', 'resumed thread policy changed')
      }
      return roleHandle
    } finally {
      role.operation = null
    }
  }

  #requireRole(roleHandle) {
    const role = this.#roles.get(roleHandle)
    if (!role || role.cleaned) {
      throw new NativeAdapterError('role_reference_invalid', 'role reference was not minted by this adapter')
    }
    return role
  }

  async beginTurn(capability, {
    role,
    actionId,
    prompt,
    outputSchema,
    profile,
  }) {
    this.#assertCapability(capability)
    const record = this.#requireRole(role)
    if (record.explicitPolicy && profile === undefined) {
      throw new NativeAdapterError(
        'agent_policy_missing',
        'controller-bound role turns require an explicit resolved profile',
      )
    }
    const resolvedProfile = profile === undefined
      ? record.initialProfile
      : validateResolvedProfile(profile, record.actorId)
    if (resolvedProfile.policy_digest !== record.policyDigest) {
      throw new NativeAdapterError(
        'agent_policy_rebound',
        'role policy digest cannot change during the persistent workflow',
      )
    }
    this.#assertCapability(capability, { requiresFreshDispatch: true })
    if (
      typeof actionId !== 'string' || !actionId.trim() || actionId.length > 256
      || typeof prompt !== 'string' || !prompt.trim()
    ) {
      throw new NativeAdapterError('turn_invalid', 'actionId and prompt must be bounded non-empty strings')
    }
    if (this.#actionIds.has(actionId)) {
      throw new NativeAdapterError('action_reused', 'actionId must be unique for the adapter lifetime')
    }
    this.#actionIds.add(actionId)
    assertStrictSchema(outputSchema)
    if (record.activeTurns.size || record.operation) {
      throw new NativeAdapterError(
        'actor_turn_active',
        'role thread already has an active lifecycle operation',
      )
    }
    record.operation = 'begin_turn'
    const mark = this.#transport.notificationMark()
    const effectiveModel = resolvedProfile.model ?? record.inheritedModel
    const effectiveEffort = resolvedProfile.effort ?? record.inheritedEffort
    const profileDigest = sha256(canonicalJson(resolvedProfile))
    const actionDigest = sha256(canonicalJson({
      actor_id: record.actorId,
      action_id: actionId,
      prompt_digest: sha256(prompt),
      schema_digest: sha256(canonicalJson(outputSchema)),
      policy_profile_digest: profileDigest,
      environment_digest: this.#fingerprint.environmentDigest,
    }))
    try {
      const response = await this.#transport.startTurn({
        threadId: record.threadId,
        input: [{ type: 'text', text: prompt }],
        outputSchema,
        clientUserMessageId: `studio-${actionDigest.slice(7)}`,
        model: effectiveModel,
        effort: effectiveEffort,
        approvalPolicy: 'never',
        permissions: ':read-only',
        environments: [],
        runtimeWorkspaceRoots: [this.#fingerprint.canonicalCwd],
      })
      const turnId = assertHostId(response?.turn?.id, 'turn id')
      if (this.#hostTurnIds.has(turnId)) {
        throw new NativeAdapterError('host_identity_reused', 'app-server reused a host turn id')
      }
      this.#hostTurnIds.add(turnId)
      await this.#transport.waitFor(
        'turn/started',
        params => params?.threadId === record.threadId && params?.turn?.id === turnId,
        mark,
        this.#options.requestTimeoutMs,
      )
      if (
        effectiveModel !== record.currentModel
        || effectiveEffort !== record.currentEffort
      ) {
        await this.#transport.waitFor(
          'thread/settings/updated',
          params => (
            params?.threadId === record.threadId
            && params?.threadSettings?.model === effectiveModel
            && (params.threadSettings.effort ?? null) === effectiveEffort
          ),
          mark,
          this.#options.requestTimeoutMs,
        )
        record.currentModel = effectiveModel
        record.currentEffort = effectiveEffort
      }
      const handle = deepFreeze({
        schema: 'studio-native-turn-reference/v1',
        action_ref: actionDigest,
      })
      const turn = {
        handle,
        role: record,
        threadId: record.threadId,
        turnId,
        outputSchema: structuredClone(outputSchema),
        resolvedProfile,
        effectiveProfile: deepFreeze({
          model: effectiveModel,
          effort: effectiveEffort,
        }),
        profileDigest,
        actionDigest,
        mark,
        state: 'active',
        terminal: null,
        receipt: null,
        error: null,
        operation: null,
      }
      this.#turns.set(handle, turn)
      record.activeTurns.add(handle)
      return handle
    } finally {
      record.operation = null
    }
  }

  async waitTurn(capability, turnHandle) {
    this.#assertCapability(capability)
    const turn = this.#requireTurn(turnHandle)
    if (turn.receipt) return turn.receipt
    if (
      turn.state !== 'active'
      && this.#transport.isTurnTombstoned(turn.threadId, turn.turnId)
    ) {
      throw new NativeAdapterError(
        'late_result',
        'a terminal or tombstoned turn cannot be integrated again',
      )
    }
    if (turn.error) throw turn.error
    if (turn.operation) throw new NativeAdapterError('turn_busy', 'turn lifecycle operation is already active')
    turn.operation = 'wait'
    let notification
    try {
      notification = await this.#transport.waitFor(
        'turn/completed',
        params => params?.threadId === turn.threadId && params?.turn?.id === turn.turnId,
        turn.mark,
        this.#options.turnTimeoutMs,
      )
    } catch (cause) {
      turn.state = 'recovery_required'
      if (cause.code !== 'server_request_forbidden') {
        this.#transport.poisonTurn(turn.threadId, turn.turnId, cause.code || 'terminal_event_missing')
      }
      turn.error = new NativeAdapterError('recovery_required', 'turn terminal event was not proven', {
        cause: cause.code || 'terminal_event_missing',
        cause_details: cause.details || {},
      })
      turn.role.activeTurns.delete(turnHandle)
      throw turn.error
    }
    try {
      this.#validateTerminalItems(notification.params.turn)
    } catch (cause) {
      turn.state = 'recovery_required'
      this.#transport.poisonTurn(turn.threadId, turn.turnId, cause.code || 'forbidden_terminal_item')
      turn.error = new NativeAdapterError(
        'recovery_required',
        'terminal items violated the context-only contract',
        { cause: cause.code || 'forbidden_terminal_item' },
      )
      turn.role.activeTurns.delete(turnHandle)
      turn.operation = null
      throw turn.error
    }
    if (notification.params.turn.status !== 'completed') {
      turn.state = notification.params.turn.status
      const failureReceipt = this.#failureReceipt(
        turn,
        notification.params.turn,
        'turn_not_completed',
      )
      turn.error = new NativeAdapterError(
        'turn_not_completed',
        'turn did not complete successfully',
        { status: notification.params.turn.status, receipt: failureReceipt },
      )
      turn.role.activeTurns.delete(turnHandle)
      turn.operation = null
      throw turn.error
    }
    let receipt
    try {
      receipt = this.#terminalReceipt(turn, notification.params.turn)
    } catch (cause) {
      const failureReceipt = this.#failureReceipt(
        turn,
        notification.params.turn,
        cause.code || 'terminal_validation_failed',
      )
      turn.state = 'terminal_failed'
      turn.error = new NativeAdapterError(
        cause.code || 'terminal_validation_failed',
        cause.message || 'terminal validation failed',
        { receipt: failureReceipt },
      )
      turn.role.activeTurns.delete(turnHandle)
      turn.operation = null
      throw turn.error
    }
    turn.state = 'completed'
    turn.terminal = notification.params.turn
    turn.receipt = receipt
    turn.role.activeTurns.delete(turnHandle)
    turn.operation = null
    return receipt
  }

  inspectTurnBinding(capability, turnHandle) {
    this.#assertCapability(capability)
    const turn = this.#requireTurn(turnHandle)
    const binding = deepFreeze({
      schema: 'studio-native-turn-binding/v1',
      action_ref: turn.actionDigest,
      actor_ref: sha256(`actor:${turn.role.actorId}`),
      host_thread_id: turn.threadId,
      host_turn_id: turn.turnId,
      environment_digest: this.#fingerprint.environmentDigest,
      config_digest: this.#isolatedHome.config_digest,
    })
    authorityRegistry(
      this.#options.authority,
      PRODUCTION_TURN_BINDINGS,
      TEST_TURN_BINDINGS,
    ).add(binding)
    return binding
  }

  inspectTurnLifecycle(capability, turnHandle) {
    this.#assertCapability(capability)
    const turn = this.#requireTurn(turnHandle)
    return deepFreeze({
      schema: 'studio-native-turn-lifecycle-evidence/v1',
      host_thread_id: turn.threadId,
      host_turn_id: turn.turnId,
      state: turn.state,
      terminal_status: turn.terminal?.status || null,
      late_result_tombstone: this.#transport.isTurnTombstoned(turn.threadId, turn.turnId),
    })
  }

  async runTurn(capability, input) {
    const handle = await this.beginTurn(capability, input)
    return this.waitTurn(capability, handle)
  }

  #requireTurn(handle) {
    const turn = this.#turns.get(handle)
    if (!turn) {
      throw new NativeAdapterError('turn_reference_invalid', 'turn reference was not minted by this adapter')
    }
    return turn
  }

  #terminalReceipt(turn, terminal) {
    const items = terminal.items
    this.#validateTerminalItems(terminal)
    const messages = items.filter(item => item?.type === 'agentMessage')
    if (messages.length !== 1 || typeof messages[0].text !== 'string') {
      throw new NativeAdapterError(
        'structured_output_missing',
        'terminal must contain exactly one final agent message',
      )
    }
    const [message] = messages
    let output
    try {
      output = JSON.parse(message.text)
    } catch {
      throw new NativeAdapterError('structured_output_invalid', 'terminal agent message is not JSON')
    }
    validateValue(output, turn.outputSchema)
    const base = {
      schema: NATIVE_ACTION_RECEIPT_SCHEMA,
      action_ref: turn.actionDigest,
      policy_profile_digest: turn.profileDigest,
      resolved_profile: structuredClone(turn.resolvedProfile),
      effective_profile: structuredClone(turn.effectiveProfile),
      actor_ref: sha256(`actor:${turn.role.actorId}`),
      host_thread_id: turn.threadId,
      host_turn_id: turn.turnId,
      terminal_status: terminal.status,
      output,
      tool_evidence: {
        command_executions: 0,
        command_actions: [],
        executions: [],
      },
      binary_digest: this.#fingerprint.binaryDigest,
      schema_digest: this.#fingerprint.schemaDigest,
      config_digest: this.#isolatedHome.config_digest,
      environment_digest: this.#fingerprint.environmentDigest,
    }
    const receipt = deepFreeze({ ...base, receipt_digest: sha256(canonicalJson(base)) })
    this.#receipts.add(receipt)
    authorityRegistry(
      this.#options.authority,
      PRODUCTION_RECEIPTS,
      TEST_RECEIPTS,
    ).add(receipt)
    this.#transport.tombstoneTurn(turn.threadId, turn.turnId)
    return receipt
  }

  #validateTerminalItems(terminal) {
    if (!Array.isArray(terminal?.items)) {
      throw new NativeAdapterError(
        'protocol_event_invalid',
        'turn terminal items must be an array',
      )
    }
    const items = terminal.items
    for (const item of items) {
      if (!SAFE_ITEM_TYPES.has(item?.type)) {
        throw new NativeAdapterError('forbidden_terminal_item', 'turn contains a forbidden host item', {
          type: item?.type || 'unknown',
        })
      }
    }
  }

  #failureReceipt(turn, terminal, errorCode) {
    const messages = Array.isArray(terminal.items)
      ? terminal.items.filter(item => item?.type === 'agentMessage' && typeof item.text === 'string')
      : []
    let output
    if (messages.length === 1) {
      try {
        output = JSON.parse(messages[0].text)
      } catch {
        output = undefined
      }
    }
    const base = {
      schema: 'studio-native-failure-receipt/v1',
      action_ref: turn.actionDigest,
      policy_profile_digest: turn.profileDigest,
      resolved_profile: structuredClone(turn.resolvedProfile),
      effective_profile: structuredClone(turn.effectiveProfile),
      actor_ref: sha256(`actor:${turn.role.actorId}`),
      host_thread_id: turn.threadId,
      host_turn_id: turn.turnId,
      terminal_status: terminal.status,
      error_code: errorCode,
      tool_evidence: {
        command_executions: 0,
        command_actions: [],
        executions: [],
      },
      binary_digest: this.#fingerprint.binaryDigest,
      schema_digest: this.#fingerprint.schemaDigest,
      environment_digest: this.#fingerprint.environmentDigest,
      config_digest: this.#isolatedHome.config_digest,
      ...(output === undefined ? {} : { output }),
    }
    const receipt = deepFreeze({ ...base, receipt_digest: sha256(canonicalJson(base)) })
    this.#receipts.add(receipt)
    authorityRegistry(
      this.#options.authority,
      PRODUCTION_RECEIPTS,
      TEST_RECEIPTS,
    ).add(receipt)
    this.#transport.tombstoneTurn(turn.threadId, turn.turnId)
    return receipt
  }

  verifyReceipt(capability, receipt) {
    this.#assertCapability(capability)
    return this.#receipts.has(receipt)
  }

  async interruptTurn(capability, turnHandle) {
    this.#assertCapability(capability)
    const turn = this.#requireTurn(turnHandle)
    if (turn.state !== 'active') {
      throw new NativeAdapterError('interrupt_unknown', 'turn is not active')
    }
    if (turn.operation) throw new NativeAdapterError('turn_busy', 'turn lifecycle operation is already active')
    turn.operation = 'interrupt'
    const mark = this.#transport.notificationMark()
    try {
      await this.#transport.interruptTurn(turn.threadId, turn.turnId)
      const notification = await this.#transport.waitFor(
        'turn/completed',
        params => params?.threadId === turn.threadId && params?.turn?.id === turn.turnId,
        mark,
        this.#options.interruptTimeoutMs,
      )
      if (notification.params.turn.status !== 'interrupted') {
        throw new NativeAdapterError('interrupt_unknown', 'host terminal status is not interrupted')
      }
      turn.state = 'interrupted'
      turn.terminal = notification.params.turn
      turn.role.activeTurns.delete(turnHandle)
      turn.operation = null
      this.#transport.tombstoneTurn(turn.threadId, turn.turnId)
      const base = {
        schema: 'studio-native-interrupt-receipt/v1',
        action_ref: turn.actionDigest,
        actor_ref: sha256(`actor:${turn.role.actorId}`),
        host_thread_id: turn.threadId,
        host_turn_id: turn.turnId,
        terminal_status: 'interrupted',
        binary_digest: this.#fingerprint.binaryDigest,
        schema_digest: this.#fingerprint.schemaDigest,
        config_digest: this.#isolatedHome.config_digest,
        environment_digest: this.#fingerprint.environmentDigest,
      }
      const receipt = deepFreeze({ ...base, receipt_digest: sha256(canonicalJson(base)) })
      this.#receipts.add(receipt)
      authorityRegistry(
        this.#options.authority,
        PRODUCTION_RECEIPTS,
        TEST_RECEIPTS,
      ).add(receipt)
      return receipt
    } catch (cause) {
      turn.state = 'recovery_required'
      this.#transport.poisonTurn(turn.threadId, turn.turnId, cause.code || 'interrupt_timeout')
      turn.error = new NativeAdapterError('interrupt_unknown', 'host terminal interruption was not proven', {
        cause: cause.code || 'unknown',
      })
      turn.role.activeTurns.delete(turnHandle)
      throw turn.error
    }
  }

  confirmRoleIdle(capability, roleHandle, { actionId }) {
    this.#assertCapability(capability)
    const role = this.#requireRole(roleHandle)
    if (typeof actionId !== 'string' || !actionId.trim() || actionId.length > 256) {
      throw new NativeAdapterError('turn_invalid', 'actionId must be a bounded non-empty string')
    }
    if (role.activeTurns.size || role.operation) {
      throw new NativeAdapterError('actor_busy', 'role still has an unresolved active turn')
    }
    if (this.#actionIds.has(actionId)) {
      throw new NativeAdapterError('action_reused', 'actionId must be unique for the adapter lifetime')
    }
    this.#actionIds.add(actionId)
    const actionDigest = sha256(canonicalJson({
      actor_id: role.actorId,
      action_id: actionId,
      operation: 'confirm-idle-cancel',
      environment_digest: this.#fingerprint.environmentDigest,
    }))
    const base = {
      schema: 'studio-native-idle-cancel-receipt/v1',
      action_ref: actionDigest,
      actor_ref: sha256(`actor:${role.actorId}`),
      host_thread_id: role.threadId,
      host_turn_id: null,
      terminal_status: 'already_terminal',
      output: { cancelled: true },
      environment_digest: this.#fingerprint.environmentDigest,
      config_digest: this.#isolatedHome.config_digest,
    }
    const receipt = deepFreeze({ ...base, receipt_digest: sha256(canonicalJson(base)) })
    this.#receipts.add(receipt)
    authorityRegistry(
      this.#options.authority,
      PRODUCTION_RECEIPTS,
      TEST_RECEIPTS,
    ).add(receipt)
    return receipt
  }

  async #cleanupThread(threadId, rolloutPath) {
    await this.#transport.cleanTerminals(threadId)
    const terminals = await this.#transport.listTerminals(threadId)
    if (!Array.isArray(terminals?.data) || terminals.data.length !== 0) {
      throw new NativeAdapterError('cleanup_incomplete', 'background terminals remain after cleanup')
    }
    if (
      typeof rolloutPath !== 'string'
      || !pathWithin(this.#isolatedHome.path, rolloutPath)
    ) {
      throw new NativeAdapterError(
        'cleanup_incomplete',
        'persisted role rollout path is unavailable or outside isolated CODEX_HOME',
      )
    }
    const mark = this.#transport.notificationMark()
    const deletion = await this.#transport.deleteThread(threadId)
    if (
      !deletion
      || typeof deletion !== 'object'
      || Array.isArray(deletion)
      || Object.keys(deletion).length !== 0
    ) {
      throw new NativeAdapterError(
        'cleanup_incomplete',
        'thread/delete returned an unexpected response',
      )
    }
    await this.#transport.waitFor(
      'thread/deleted',
      params => params?.threadId === threadId && Object.keys(params).length === 1,
      mark,
      this.#options.requestTimeoutMs,
    )
    if (await lstat(rolloutPath).catch(() => null)) {
      throw new NativeAdapterError(
        'cleanup_incomplete',
        'persisted rollout remains after thread deletion',
      )
    }
    this.#transport.clearThreadTombstones(threadId)
    return {
      background_terminals: 0,
      deleted: true,
      deletion_notified: true,
      rollout_absent: true,
      rollout_path_ref: sha256(rolloutPath),
    }
  }

  async cleanupRole(capability, roleHandle) {
    this.#assertCapability(capability)
    const role = this.#requireRole(roleHandle)
    if (role.activeTurns.size || role.operation) {
      throw new NativeAdapterError('cleanup_active_turn', 'role has an unresolved active turn')
    }
    role.operation = 'cleanup'
    let cleanup
    try {
      cleanup = await this.#cleanupThread(role.threadId, role.rolloutPath)
      role.cleaned = true
      this.#rolesByActor.delete(role.actorId)
      if (this.#rolesByActor.size === 0 && this.#startingActors.size === 0) {
        this.#workflowLeaseActive = false
        this.#workflowLeaseClosed = true
      }
    } finally {
      role.operation = null
    }
    const base = {
      schema: 'studio-native-cleanup-receipt/v1',
      actor_ref: sha256(`actor:${role.actorId}`),
      host_thread_id: role.threadId,
      background_terminals: cleanup.background_terminals,
      deleted: cleanup.deleted,
      deletion_notified: cleanup.deletion_notified,
      rollout_absent: cleanup.rollout_absent,
      rollout_path_ref: cleanup.rollout_path_ref,
      config_digest: this.#isolatedHome.config_digest,
      environment_digest: this.#fingerprint.environmentDigest,
    }
    const receipt = deepFreeze({ ...base, receipt_digest: sha256(canonicalJson(base)) })
    this.#receipts.add(receipt)
    authorityRegistry(
      this.#options.authority,
      PRODUCTION_RECEIPTS,
      TEST_RECEIPTS,
    ).add(receipt)
    return receipt
  }

  async close() {
    if (this.#closed) return
    this.#closed = true
    if (this.#transport) await this.#transport.close().catch(() => {})
    if (this.#isolatedHome?.path) {
      await rm(this.#isolatedHome.path, { recursive: true, force: true }).catch(() => {})
    }
  }
}

function normalizeOptions(options, trusted) {
  if (!options || typeof options !== 'object') {
    throw new NativeAdapterError('adapter_config_invalid', 'adapter options are required')
  }
  for (const [name, value] of [
    ['allowedVersions', trusted.allowedVersions],
    ['allowedBinaryDigests', trusted.allowedBinaryDigests],
    ['allowedSchemaDigests', trusted.allowedSchemaDigests],
  ]) {
    if (!Array.isArray(value) || !value.length || value.some(entry => typeof entry !== 'string')) {
      throw new NativeAdapterError('adapter_config_invalid', `${name} must be a non-empty pin set`)
    }
  }
  return {
    binary: trusted.binary,
    expectedBinary: trusted.expectedBinary,
    processEnvOverrides: trusted.processEnvOverrides || {},
    sourceCodexHome: trusted.sourceCodexHome,
    runtimeRoot: options.runtimeRoot,
    cwd: options.cwd,
    env: trusted.env,
    allowedVersions: [...trusted.allowedVersions],
    allowedBinaryDigests: [...trusted.allowedBinaryDigests],
    allowedSchemaDigests: [...trusted.allowedSchemaDigests],
    freshnessMs: trusted.freshnessMs,
    requestTimeoutMs: trusted.requestTimeoutMs,
    turnTimeoutMs: trusted.turnTimeoutMs,
    interruptTimeoutMs: trusted.interruptTimeoutMs,
    now: trusted.now,
    authority: trusted.authority,
  }
}

export function createPersistentNativeAppServer(options) {
  const forbidden = [
    'binary',
    'expectedBinary',
    'sourceCodexHome',
    'env',
    'processEnvOverrides',
    'allowedVersions',
    'allowedBinaryDigests',
    'allowedSchemaDigests',
    'freshnessMs',
    'requestTimeoutMs',
    'turnTimeoutMs',
    'interruptTimeoutMs',
    'now',
  ]
  if (forbidden.some(key => Object.hasOwn(options || {}, key))) {
    throw new NativeAdapterError(
      'adapter_config_forbidden',
      'Production binary, pins, environment, clock, and timeouts are adapter-owned',
    )
  }
  return new PersistentNativeAppServer(normalizeOptions(options, {
    binary: BUNDLED_CODEX_BINARY,
    expectedBinary: BUNDLED_CODEX_BINARY,
    sourceCodexHome: join(homedir(), '.codex'),
    env: process.env,
    allowedVersions: [PINNED_CODEX_VERSION],
    allowedBinaryDigests: [...SUPPORTED_BINARY_DIGESTS],
    allowedSchemaDigests: [PINNED_SCHEMA_DIGEST],
    freshnessMs: 5 * 60_000,
    requestTimeoutMs: 15_000,
    turnTimeoutMs: 120_000,
    interruptTimeoutMs: 10_000,
    now: Date.now,
    authority: 'production',
  }))
}

export function createPersistentNativeAppServerForTest(options) {
  if (!process.env.NODE_TEST_CONTEXT) {
    throw new NativeAdapterError('test_factory_forbidden', 'fake app-server injection is test-runner only')
  }
  return new PersistentNativeAppServer(normalizeOptions(options, {
    binary: options.binary,
    expectedBinary: options.binary,
    sourceCodexHome: options.sourceCodexHome,
    env: options.env || process.env,
    processEnvOverrides: options.processEnvOverrides || {},
    allowedVersions: options.allowedVersions,
    allowedBinaryDigests: options.allowedBinaryDigests,
    allowedSchemaDigests: options.allowedSchemaDigests,
    freshnessMs: options.freshnessMs ?? 5 * 60_000,
    requestTimeoutMs: options.requestTimeoutMs ?? 500,
    turnTimeoutMs: options.turnTimeoutMs ?? 500,
    interruptTimeoutMs: options.interruptTimeoutMs ?? 100,
    now: options.now || Date.now,
    authority: 'test',
  }))
}
