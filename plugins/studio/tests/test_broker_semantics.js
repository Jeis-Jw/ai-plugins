import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor

async function loadBroker(name) {
  const path = join(HERE, '..', 'broker', name)
  const source = (await readFile(path, 'utf8')).replace('export const meta', 'const meta')
  return new AsyncFunction('args', 'budget', 'phase', 'parallel', 'agent', 'log', source)
}

async function execute(name, args, responder, spentValues = [0, 0]) {
  const broker = await loadBroker(name)
  const phases = []
  const logs = []
  let spentIndex = 0
  return {
    output: await broker(
      args,
      { spent: () => spentValues[Math.min(spentIndex++, spentValues.length - 1)] },
      value => phases.push(value),
      jobs => Promise.all(jobs.map(job => job())),
      (_prompt, options) => Promise.resolve(responder(options.label, options)),
      value => logs.push(value),
    ),
    phases,
    logs,
  }
}

const brainstorm = await execute(
  'brainstorm.workflow.js',
  {
    agenda: 'choose a bounded parser contract',
    personas: [
      { name: 'a', role: 'planner', prior: 'small', body: 'prefer a narrow surface' },
      { name: 'b', role: 'reviewer', prior: 'safe', body: 'prefer explicit evidence' },
    ],
    maxRounds: 2,
    dryStop: 1,
  },
  label => {
    if (label.startsWith('diverge:')) return { utterance: `seed ${label}`, deltas: [] }
    if (label === 'debate:r1:a') return {
      utterance: 'drop implicit config',
      deltas: [{ changed_what: 'config removed from v1', anchor: 'rejected-alternative', evidence: 'scope.md#v1' }],
    }
    if (label === 'debate:r1:b') return {
      utterance: 'agreement only',
      deltas: [{ changed_what: 'we agree', anchor: 'artifact', evidence: 'no artifact' }],
    }
    if (label === 'critic:r1') {
      // Deliberately reverse verdict order: the broker must join by id.
      return { verified: [{ id: 1, valid: false, reason: 'agreement' }, { id: 0, valid: true, reason: 'anchored' }] }
    }
    if (label.startsWith('debate:r2:')) return { utterance: 'nothing new', deltas: [] }
    if (label === 'critic:r2') return { verified: [] }
    if (label === 'summarizer') return { synthesis: 'bounded parser', minority: 'none', proposals: [] }
    if (label === 'critic:final') return { alive: true, reason: 'one verified delta' }
    throw new Error(`unexpected brainstorm label: ${label}`)
  },
  [100, 137],
)
assert.equal(brainstorm.output.delta_log.filter(delta => !delta.dry).length, 1)
assert.equal(brainstorm.output.delta_log.find(delta => !delta.dry).changed_what, 'config removed from v1')
assert.equal(brainstorm.output.delta_log.filter(delta => delta.dry).length, 1)
assert.ok(brainstorm.logs.some(line => /DRY/.test(line)), brainstorm.logs)
assert.deepEqual(Object.keys(brainstorm.output.receipt).sort(), [
  'counters', 'elapsed_ms', 'emitter', 'finished_at', 'quality', 'run_id',
  'schema', 'started_at', 'token_coverage', 'tokens', 'workflow',
].sort())
assert.equal(brainstorm.output.receipt.schema, 'workflow-receipt/v1')
assert.equal(brainstorm.output.receipt.emitter, 'studio')
assert.equal(brainstorm.output.receipt.tokens, 37)
assert.equal(brainstorm.output.receipt.token_coverage, 'exact')
assert.equal(brainstorm.output.cost.tokens, 37)
assert.equal(brainstorm.output.cost.elapsed_ms, brainstorm.output.receipt.elapsed_ms)

let qaRound = 0
const pairing = await execute(
  'pairing.workflow.js',
  {
    taskSpec: 'implement guarded parser',
    acceptanceCriteria: ['reject unsafe ids'],
    worktreePath: '/tmp/track',
    branch: 'task/track',
    personas: { dev: { body: 'build' }, qa: { body: 'attack' } },
    maxRounds: 2,
  },
  label => {
    if (label === 'dev:r1') return {
      summary: 'implemented parser', defended: [], unresolved: [],
      changedFiles: ['parser.py'], verification: [{ command: 'python test.py', result: 'pass' }], blockedChecks: [],
    }
    if (label === 'qa:r1') {
      qaRound++
      return {
        broke: true,
        failures: [{ title: 'path escape', repro: 'python test.py unsafe', severity: 'high' }],
        verification: [{ command: 'python test.py unsafe', result: 'fail: escaped' }], blockedChecks: [],
      }
    }
    if (label === 'dev:r2') return {
      summary: 'fenced path', defended: [{ failure_id: 0, test_added: 'test_unsafe_id', how: 'allowlist' }], unresolved: [],
      changedFiles: ['parser.py', 'test_parser.py'], verification: [{ command: 'python test.py', result: 'pass' }], blockedChecks: [],
    }
    if (label === 'qa:r2') {
      qaRound++
      return { broke: false, failures: [], verification: [{ command: 'python test.py', result: 'pass' }], blockedChecks: [] }
    }
    if (label === 'critic:verdict') return { alive: true, reason: 'defended', defended_count: 1, open_count: 0 }
    throw new Error(`unexpected pairing label: ${label}`)
  },
  [250, 315],
)
assert.equal(qaRound, 2)
assert.equal(pairing.output.readyForIntegration, true)
assert.equal(pairing.output.delta_log.filter(delta => delta.anchor === 'repro-test').length, 1)
assert.deepEqual(pairing.output.changedFiles.sort(), ['parser.py', 'test_parser.py'])
assert.equal(pairing.output.receipt.tokens, 65)
assert.equal(pairing.output.receipt.token_coverage, 'exact')
assert.equal(pairing.output.receipt.quality.ready_for_integration, true)
assert.equal(pairing.output.cost.elapsed_ms, pairing.output.receipt.elapsed_ms)

const falseReady = await execute(
  'pairing.workflow.js',
  {
    taskSpec: 'unchecked build', acceptanceCriteria: ['must be verified'],
    worktreePath: '/tmp/track', personas: { dev: {}, qa: {} }, maxRounds: 1,
  },
  label => {
    if (label === 'dev:r1') return {
      summary: 'changed code', defended: [], unresolved: [], changedFiles: ['x.py'],
      verification: [], blockedChecks: ['runtime unavailable'],
    }
    if (label === 'qa:r1') return { broke: false, failures: [], verification: [], blockedChecks: ['runtime unavailable'] }
    if (label === 'critic:verdict') return { alive: true, reason: 'looks fine', defended_count: 0, open_count: 0 }
    throw new Error(`unexpected false-ready label: ${label}`)
  },
)
assert.equal(falseReady.output.readyForIntegration, false)

const cyclePairing = await execute(
  'pairing.workflow.js',
  {
    taskSpec: 'continue one logical review cycle', acceptanceCriteria: ['reject unsafe ids'],
    worktreePath: '/tmp/track', personas: { dev: {}, qa: {} }, maxRounds: 1,
    reviewCycle: {
      cycleId: 'RC-issue-58', qaMode: 'delta', nextFindingSeq: 4,
      openFindings: [{ id: 'F-0003', title: 'path escape', repro: 'python test.py unsafe', severity: 'high' }],
    },
  },
  label => {
    if (label === 'dev:r1') return {
      summary: 'fenced path', defended: [{ failure_id: 'F-0003', test_added: 'test_unsafe_id' }], unresolved: [],
      changedFiles: ['parser.py'], verification: [{ command: 'python test.py', result: 'pass' }], blockedChecks: [],
    }
    if (label === 'qa:r1') return {
      broke: true,
      failures: [{ title: 'unicode escape', repro: 'python test.py unicode', severity: 'medium' }],
      verification: [{ command: 'python test.py unicode', result: 'fail: escaped' }], blockedChecks: [],
    }
    if (label === 'critic:verdict') return { alive: false, reason: 'one open', defended_count: 1, open_count: 1 }
    throw new Error(`unexpected cycle-pairing label: ${label}`)
  },
)
assert.equal(cyclePairing.output.developmentReady, false)
assert.equal(cyclePairing.output.readyForIntegration, false)
assert.equal(cyclePairing.output.receipt.quality.ready_for_integration, false)
assert.equal(cyclePairing.output.reviewFeedback.schema, 'studio-review-feedback/v1')
assert.equal(cyclePairing.output.reviewFeedback.cycle_id, 'RC-issue-58')
assert.deepEqual(cyclePairing.output.reviewFeedback.findings_defended, ['F-0003'])
assert.deepEqual(cyclePairing.output.reviewFeedback.findings_opened.map(f => f.id), ['F-0004'])
assert.deepEqual(cyclePairing.output.reviewFeedback.findings_open, ['F-0004'])
assert.equal(cyclePairing.output.reviewFeedback.result, 'findings-open')

async function resolvedBrainstormOption(agentPolicy, overrides = {}) {
  let captured = null
  await execute(
    'brainstorm.workflow.js',
    {
      agenda: 'policy precedence', agentRuntime: 'codex', agentPolicy, overrides,
      personas: [
        { name: 'a', agentId: 'planner-a', role: 'planner', prior: 'one', body: 'one' },
        { name: 'b', agentId: 'planner-b', role: 'reviewer', prior: 'two', body: 'two' },
      ],
      maxRounds: 1, dryStop: 1,
    },
    (label, options) => {
      if (label === 'diverge:a') captured = options
      if (label.startsWith('diverge:') || label.startsWith('debate:')) return { utterance: 'dry', deltas: [] }
      if (label === 'critic:r1') return { verified: [] }
      if (label === 'summarizer') return { synthesis: 'done', minority: 'none', proposals: [] }
      if (label === 'critic:final') return { alive: false, reason: 'dry' }
      throw new Error(`unexpected policy label: ${label}`)
    },
  )
  return captured
}

const commonDefault = { defaults: { model: 'common-default' } }
const providerDefault = { defaults: { model: 'common-default' }, providers: { codex: { defaults: { model: 'provider-default' } } } }
const commonRole = { ...providerDefault, roles: { planner: { model: 'common-role' } } }
const providerRole = { ...commonRole, providers: { codex: { ...providerDefault.providers.codex, roles: { planner: { model: 'provider-role' } } } } }
const commonAgent = { ...providerRole, agents: { 'planner-a': { model: 'common-agent' } } }
const providerAgent = { ...commonAgent, providers: { codex: { ...providerRole.providers.codex, agents: { 'planner-a': { model: 'provider-agent' } } } } }
const commonRitual = { ...providerAgent, rituals: { brainstorm: { diverge: { model: 'common-ritual' } } } }
const providerRitual = { ...commonRitual, providers: { codex: { ...providerAgent.providers.codex, rituals: { brainstorm: { diverge: { model: 'provider-ritual' } } } } } }

const precedenceCases = [
  [commonDefault, {}, 'common-default'],
  [providerDefault, {}, 'provider-default'],
  [commonRole, {}, 'common-role'],
  [providerRole, {}, 'provider-role'],
  [commonAgent, {}, 'common-agent'],
  [providerAgent, {}, 'provider-agent'],
  [commonRitual, {}, 'common-ritual'],
  [providerRitual, {}, 'provider-ritual'],
  [providerRitual, { model: 'run-override' }, 'run-override'],
  [providerRitual, { model: '' }, 'provider-ritual'],
]
for (const [policy, overrides, expected] of precedenceCases) {
  const options = await resolvedBrainstormOption(policy, overrides)
  assert.equal(options.model, expected)
  assert.equal(options.agentRuntime, 'codex')
  assert.equal(options.agentId, 'planner-a')
}

let pairingDevOptions = null
await execute(
  'pairing.workflow.js',
  {
    taskSpec: 'runtime policy', acceptanceCriteria: ['verified'], worktreePath: '/tmp/track',
    agentRuntime: 'claude',
    personas: { dev: { agentId: 'builder-7' }, qa: { agentId: 'qa-7' } },
    agentPolicy: {
      agents: { 'builder-7': { model: 'common-agent' } },
      providers: { claude: { agents: { 'builder-7': { model: 'provider-agent' } } } },
    },
    maxRounds: 1,
  },
  (label, options) => {
    if (label === 'dev:r1') {
      pairingDevOptions = options
      return {
        summary: 'done', defended: [], unresolved: [], changedFiles: ['x'],
        verification: [{ command: 'test', result: 'pass' }], blockedChecks: [],
      }
    }
    if (label === 'qa:r1') return { broke: false, failures: [], verification: [{ command: 'test', result: 'pass' }], blockedChecks: [] }
    if (label === 'critic:verdict') return { alive: true, reason: 'done', defended_count: 0, open_count: 0 }
    throw new Error(`unexpected pairing policy label: ${label}`)
  },
)
assert.equal(pairingDevOptions.model, 'provider-agent')
assert.equal(pairingDevOptions.agentRuntime, 'claude')
assert.equal(pairingDevOptions.agentId, 'builder-7')
assert.equal(pairingDevOptions.agentType, 'general-purpose')

const badRuntime = await execute(
  'brainstorm.workflow.js',
  {
    agenda: 'bad runtime', agentRuntime: 'other',
    personas: [{ name: 'a', role: 'planner' }, { name: 'b', role: 'reviewer' }],
  },
  () => { throw new Error('invalid runtime must not dispatch agents') },
)
assert.match(badRuntime.output.error, /agentRuntime/)

console.log('all broker semantic checks passed')
