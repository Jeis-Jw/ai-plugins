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
      (_prompt, options) => Promise.resolve(responder(options.label)),
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

console.log('all broker semantic checks passed')
