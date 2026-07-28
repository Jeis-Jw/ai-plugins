#!/usr/bin/env node
import {
  lstat, mkdir, readFile, rm, writeFile,
} from 'node:fs/promises'
import { appendFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import readline from 'node:readline'

const SCHEMA_BYTES = '{"protocol":"fake-codex-app-server-v2","version":1}\n'
const scenario = process.env.FAKE_APP_SERVER_SCENARIO || 'success'
const callLog = process.env.FAKE_APP_SERVER_CALL_LOG || ''
const denialLog = process.env.FAKE_APP_SERVER_DENIAL_LOG || ''
const envLog = process.env.FAKE_APP_SERVER_ENV_LOG || ''

if (envLog) await writeFile(envLog, JSON.stringify(Object.keys(process.env).sort()))

function emit(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`)
}

async function record(message) {
  if (callLog) appendFileSync(callLog, `${JSON.stringify(message)}\n`)
}

function uuid(sequence) {
  const tail = (BigInt(process.pid) * 1_000_000n + BigInt(sequence))
    .toString()
    .slice(-12)
    .padStart(12, '0')
  return `019fa77e-a668-7a50-b3e8-${tail}`
}

if (process.argv[2] === '--version') {
  process.stdout.write(`${process.env.FAKE_APP_SERVER_VERSION || 'codex-cli 0.146.0-alpha.3.1'}\n`)
  process.exit(0)
}

if (process.argv[2] === 'app-server' && process.argv[3] === 'generate-json-schema') {
  const outIndex = process.argv.indexOf('--out')
  if (outIndex < 0 || !process.argv[outIndex + 1]) process.exit(2)
  await mkdir(process.argv[outIndex + 1], { recursive: true })
  await writeFile(
    join(process.argv[outIndex + 1], 'codex_app_server_protocol.v2.schemas.json'),
    scenario === 'schema-drift'
      ? '{"protocol":"fake-codex-app-server-v2","version":2}\n'
      : SCHEMA_BYTES,
  )
  process.exit(0)
}

if (process.argv[2] !== 'app-server' || !process.argv.includes('--stdio')) process.exit(2)

let threadSequence = 0
let turnSequence = 100
let deletedCount = 0
const threads = new Map()
const pendingInterrupts = new Map()
const backgroundProcesses = new Map()

function threadResult(params, id, rolloutPath) {
  return {
    thread: {
      id,
      turns: [],
      status: { type: 'idle' },
      ephemeral: params.ephemeral,
      path: rolloutPath,
      threadSource: params.threadSource ?? null,
    },
    model: 'fake-model',
    modelProvider: 'fake-provider',
    cwd: params.cwd,
    approvalPolicy: scenario === 'unsafe-policy' ? 'on-request' : 'never',
    approvalsReviewer: 'user',
    sandbox: {
      type: scenario === 'unsafe-policy' ? 'workspaceWrite' : 'readOnly',
      networkAccess: scenario === 'unsafe-policy',
      writableRoots: scenario === 'unsafe-policy' ? [params.cwd] : undefined,
    },
    activePermissionProfile: {
      id: scenario === 'unsafe-policy' ? ':workspace' : ':read-only',
    },
    instructionSources: scenario === 'inherited-capability' ? ['/private/inherited/AGENTS.md'] : [],
    runtimeWorkspaceRoots: params.runtimeWorkspaceRoots,
  }
}

async function persistThread(threadId, persisted) {
  if (!persisted.rolloutPath) return
  await mkdir(join(process.env.CODEX_HOME, 'sessions'), { recursive: true })
  await writeFile(
    persisted.rolloutPath,
    `${JSON.stringify({
      id: threadId,
      params: persisted.params,
      createdAt: persisted.createdAt,
    })}\n`,
  )
}

function completed(threadId, turnId, status = 'completed', outputOverride = null) {
  const output = outputOverride || (scenario === 'schema-fail'
    ? { answer: 7, extra: true }
    : { answer: `turn-${turnId}` })
  const items = status !== 'completed'
    ? []
    : [{
      type: scenario === 'forbidden-item' ? 'fileChange' : 'agentMessage',
      id: `item-${turnId}`,
      text: JSON.stringify(output),
      changes: scenario === 'forbidden-item' ? [] : undefined,
    }]
  if (['command-item', 'failed-command-item'].includes(scenario)) {
    items.unshift({
      type: 'commandExecution',
      id: `command-${turnId}`,
      command: '/usr/bin/true',
      cwd: process.cwd(),
      status: 'completed',
      exitCode: 0,
      aggregatedOutput: '',
      commandActions: [{ type: 'read', path: '/tmp/synthetic' }],
    })
  }
  emit({
    method: 'turn/completed',
    params: {
      threadId,
      turn: {
        id: turnId,
        status,
        items,
      },
    },
  })
}

async function handle(message) {
  await record(message)
  if (message.method === 'initialized' && scenario === 'startup-capability') {
    emit({ method: 'mcpServer/startupProgress', params: { status: 'starting' } })
    return
  }
  if (message.id === 'server-request-1' && !message.method) {
    if (denialLog) writeFileSync(denialLog, JSON.stringify(message))
    return
  }
  const { id, method, params = {} } = message
  if (id === undefined) return
  if (method === 'initialize') {
    emit({ id, result: { userAgent: 'fake', protocolVersion: 2 } })
    return
  }
  if (method === 'thread/start') {
    if (await lstat(join(process.env.CODEX_HOME, 'auth.json')).catch(() => null)) {
      emit({ id, error: { code: -32090, message: 'auth snapshot remained readable' } })
      return
    }
    const threadId = uuid(++threadSequence)
    const rolloutPath = params.ephemeral
      ? null
      : join(process.env.CODEX_HOME, 'sessions', `${threadId}.jsonl`)
    if (rolloutPath) {
      await mkdir(join(process.env.CODEX_HOME, 'sessions'), { recursive: true })
    }
    const persisted = {
      params,
      rolloutPath,
      createdAt: Math.floor(Date.now() / 1000),
    }
    threads.set(threadId, persisted)
    if (rolloutPath) await persistThread(threadId, persisted)
    emit({ id, result: threadResult(params, threadId, rolloutPath) })
    return
  }
  if (method === 'thread/list') {
    const cwdFilters = Array.isArray(params.cwd)
      ? params.cwd
      : params.cwd ? [params.cwd] : null
    const data = [...threads.entries()]
      .filter(([, persisted]) => (
        !cwdFilters || cwdFilters.includes(persisted.params.cwd)
      ))
      .map(([threadId, persisted]) => ({
        id: threadId,
        sessionId: threadId,
        preview: '',
        modelProvider: 'fake-provider',
        createdAt: persisted.createdAt,
        updatedAt: persisted.createdAt,
        cwd: persisted.params.cwd,
        source: 'appServer',
        threadSource: persisted.params.threadSource ?? null,
        status: { type: 'idle' },
        ephemeral: persisted.params.ephemeral,
        path: persisted.rolloutPath,
        cliVersion: 'fake',
        turns: [],
      }))
    emit({
      id,
      result: {
        data,
        nextCursor: null,
        backwardsCursor: data.length ? 'fake-start' : null,
      },
    })
    return
  }
  if (method === 'thread/resume') {
    let persisted = threads.get(params.threadId)
    if (!persisted && params.path) {
      const stored = JSON.parse(await readFile(params.path, 'utf8').catch(() => 'null'))
      if (stored?.params) {
        persisted = {
          params: stored.params,
          rolloutPath: params.path,
          createdAt: stored.createdAt,
        }
        threads.set(params.threadId, persisted)
      }
    }
    if (!persisted) {
      emit({ id, error: { code: -32001, message: 'unknown thread' } })
      return
    }
    emit({
      id,
      result: threadResult(persisted.params, params.threadId, persisted.rolloutPath),
    })
    return
  }
  if (method === 'thread/read') {
    const persisted = threads.get(params.threadId)
    if (!persisted) {
      emit({
        id,
        error: {
          code: -32600,
          message: `thread not loaded: ${params.threadId}`,
        },
      })
      return
    }
    emit({
      id,
      result: {
        thread: {
          id: params.threadId,
          turns: [],
          cwd: persisted.params.cwd,
          ephemeral: persisted.params.ephemeral,
          path: persisted.rolloutPath,
          threadSource: persisted.params.threadSource ?? null,
        },
      },
    })
    return
  }
  if (method === 'experimentalFeature/list') {
    const data = [
      { name: 'shell_tool', enabled: false, defaultEnabled: true, stage: 'stable' },
      { name: 'unified_exec', enabled: false, defaultEnabled: true, stage: 'stable' },
    ]
    if (scenario === 'unknown-capability') {
      data.push({ name: 'mystery_surface', enabled: true, defaultEnabled: false, stage: 'beta' })
    }
    emit({ id, result: { data, nextCursor: null } })
    return
  }
  if (method === 'permissionProfile/list') {
    emit({ id, result: { data: [{ id: ':read-only', allowed: true }], nextCursor: null } })
    return
  }
  if (method === 'hooks/list') {
    emit({
      id,
      result: {
        data: [{
          cwd: params.cwds?.[0] || process.cwd(),
          hooks: scenario === 'nonempty-inventory' ? [{ enabled: true }] : [],
          errors: [],
          warnings: [],
        }],
      },
    })
    return
  }
  if (method === 'skills/list') {
    emit({
      id,
      result: {
        data: [{
          cwd: params.cwds?.[0] || process.cwd(),
          skills: scenario === 'nonempty-skill' ? [{ enabled: true }] : [],
          errors: [],
        }],
      },
    })
    return
  }
  if (method === 'plugin/list') {
    emit({
      id,
      result: {
        marketplaces: scenario === 'nonempty-plugin'
          ? [{ name: 'local', path: '/private/plugin', plugins: [{}] }]
          : [],
        featuredPluginIds: [],
        marketplaceLoadErrors: [],
      },
    })
    return
  }
  if (method === 'app/list') {
    emit({
      id,
      result: {
        data: scenario === 'nonempty-app' ? [{ id: 'app', name: 'app' }] : [],
        nextCursor: null,
      },
    })
    return
  }
  if (method === 'mcpServerStatus/list') {
    emit({
      id,
      result: {
        data: scenario === 'nonempty-mcp'
          ? [{ name: 'mcp', authStatus: 'unsupported', tools: {}, resources: [], resourceTemplates: [] }]
          : [],
        nextCursor: null,
      },
    })
    return
  }
  if (method === 'turn/start') {
    const turnId = uuid(++turnSequence)
    if (scenario === 'turn-missing-id') {
      emit({ id, result: { turn: { status: 'inProgress', items: [] } } })
      return
    }
    emit({ id, result: { turn: { id: turnId, status: 'inProgress', items: [] } } })
    emit({ method: 'turn/started', params: { threadId: params.threadId, turn: { id: turnId } } })
    if (scenario === 'server-request') {
      emit({
        id: 'server-request-1',
        method: 'item/commandExecution/requestApproval',
        params: { threadId: params.threadId, turnId },
      })
      return
    }
    if (scenario === 'eof') {
      setTimeout(() => process.exit(0), 5)
      return
    }
    if (['interrupt', 'interrupt-unknown', 'late-interrupt'].includes(scenario)) {
      pendingInterrupts.set(turnId, params.threadId)
      return
    }
    setTimeout(
      () => completed(
        params.threadId,
        turnId,
        scenario === 'failed-command-item' ? 'failed' : 'completed',
      ),
      5,
    )
    return
  }
  if (method === 'turn/interrupt') {
    if (scenario === 'interrupt-unknown') {
      emit({ id, error: { code: -32002, message: 'unknown turn' } })
      return
    }
    emit({ id, result: {} })
    const threadId = pendingInterrupts.get(params.turnId)
    if (threadId) {
      const delay = scenario === 'late-interrupt' ? 200 : 5
      setTimeout(() => completed(threadId, params.turnId, 'interrupted'), delay)
    }
    return
  }
  if (method === 'command/exec') {
    emit({
      id,
      result: {
        exitCode: 1,
        stdout: '',
        stderr: 'EPERM: operation not permitted by read-only fixture sandbox',
      },
    })
    return
  }
  if (method === 'thread/backgroundTerminals/clean') {
    for (const [processId, child] of backgroundProcesses) {
      if (child.exitCode !== null || child.signalCode !== null) {
        backgroundProcesses.delete(processId)
      }
    }
    emit({ id, result: {} })
    return
  }
  if (method === 'thread/backgroundTerminals/list') {
    emit({
      id,
      result: {
        data: scenario === 'cleanup-fail' && deletedCount >= 1
          ? [{ processId: 'unsafe' }]
          : [...backgroundProcesses.keys()].map(processId => ({ processId })),
        nextCursor: null,
      },
    })
    return
  }
  if (method === 'command/exec/terminate') {
    const child = backgroundProcesses.get(params.processId)
    if (!child) {
      emit({ id, result: { terminated: true } })
      return
    }
    const exited = new Promise(resolveExit => child.once('exit', resolveExit))
    child.kill('SIGTERM')
    await Promise.race([
      exited,
      new Promise(resolveTimeout => setTimeout(resolveTimeout, 500)),
    ])
    const terminated = child.exitCode !== null || child.signalCode !== null
    if (terminated) backgroundProcesses.delete(params.processId)
    emit({ id, result: { terminated } })
    return
  }
  if (method === 'thread/delete') {
    const persisted = threads.get(params.threadId)
    if (persisted?.rolloutPath) await rm(persisted.rolloutPath, { force: true })
    threads.delete(params.threadId)
    deletedCount += 1
    emit({ id, result: {} })
    emit({
      method: 'thread/deleted',
      params: scenario === 'bad-delete-notification'
        ? { threadId: params.threadId, unexpected: true }
        : { threadId: params.threadId },
    })
    return
  }
  emit({ id, error: { code: -32601, message: `unsupported ${method}` } })
}

const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity })
for await (const line of input) {
  await handle(JSON.parse(line))
}
