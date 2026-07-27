import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const source = (await readFile(join(HERE, '..', 'broker', 'brainstorm.workflow.js'), 'utf8'))
  .replace('export const meta', 'const meta')
const broker = new AsyncFunction('args', 'budget', 'phase', 'parallel', 'agent', 'log', source)
const corpusIndex = process.argv.indexOf('--representative-corpus')
const corpusPath = corpusIndex >= 0 ? process.argv[corpusIndex + 1] : null

async function run(profile, personas) {
  let calls = 0
  const output = await broker(
    {
      agenda: 'Choose one bounded parser contract',
      personas,
      productionProfile: profile,
      criticRubric: 'Only the fixed acceptance criterion AC-1 and its rejected alternative count.',
    },
    { spent: () => null },
    () => {},
    jobs => Promise.all(jobs.map(job => job())),
    async (_prompt, options) => {
      calls += 1
      if (options.label.startsWith('diverge:')) return { utterance: 'independent preparation', deltas: [] }
      if (options.label === 'debate:r1:a') return {
        utterance: 'reject implicit configuration',
        deltas: [{ changed_what: 'implicit configuration rejected', anchor: 'rejected-alternative', evidence: 'AC-1' }],
      }
      if (options.label.startsWith('debate:')) return { utterance: 'no outcome change', deltas: [] }
      if (options.label === 'critic:r1') return {
        verified: [{ id: 0, valid: true, outcome_linked: true, reason: 'changes AC-1 decision' }],
      }
      if (options.label.startsWith('critic:r')) return { verified: [] }
      if (options.label === 'summarizer') return { synthesis: 'explicit configuration only', minority: 'none', proposals: [] }
      if (options.label === 'critic:final') return { alive: true, reason: 'AC-1 decision changed' }
      throw new Error(`unexpected label: ${options.label}`)
    },
    () => {},
  )
  const uniqueOutcomes = new Set(output.delta_log.filter(item => !item.dry).map(item => `${item.anchor}:${item.changed_what}`))
  return {
    profile,
    calls,
    elapsed_ms: output.receipt.elapsed_ms,
    receipt: output.receipt,
    quality: {
      criterion_pass: output.verdict.alive === true,
      outcome_linked_delta_score: uniqueOutcomes.has('rejected-alternative:implicit configuration rejected') ? 100 : 0,
    },
  }
}

const baseline = await run('full', [
  { name: 'a' }, { name: 'b' }, { name: 'c' },
])
const variant = await run('standard', [
  { name: 'a' }, { name: 'b' },
])
const reduction = (before, after) => Number((((before - after) / before) * 100).toFixed(2))
const callReduction = reduction(baseline.calls, variant.calls)
let representative = null
if (corpusPath) {
  const corpus = JSON.parse(await readFile(corpusPath, 'utf8'))
  const cases = Array.isArray(corpus.cases) ? corpus.cases : []
  const outcomes = new Set(cases.map(item => item.outcome_kind))
  const valid = corpus.schema === 'studio-production-profile-replay-corpus/v1'
    && corpus.provenance === 'reviewed-representative-fixture'
    && cases.length >= 3 && outcomes.size >= 3
  const scored = cases.map(item => ({
    id: item.id,
    baseline_pass: JSON.stringify(item.baseline_observed) === JSON.stringify(item.expected),
    variant_pass: JSON.stringify(item.variant_observed) === JSON.stringify(item.expected),
  }))
  const baselineScore = scored.filter(item => item.baseline_pass).length / Math.max(scored.length, 1) * 100
  const variantScore = scored.filter(item => item.variant_pass).length / Math.max(scored.length, 1) * 100
  representative = {
    coverage: valid ? 'representative-fixture' : 'invalid',
    source_refs: corpus.source_refs || [],
    cases: scored,
    baseline_quality_score: baselineScore,
    variant_quality_score: variantScore,
    quality_drop_percent: Number((baselineScore - variantScore).toFixed(2)),
    live_wall_time_coverage: 'unavailable',
  }
}
const result = {
  schema: 'studio-production-profile-benchmark/v1',
  workload: 'bounded-parser-contract',
  fixed_criterion: 'AC-1',
  fixed_rubric: true,
  baseline,
  variant,
  calculations: {
    call_reduction_percent: callReduction,
    deterministic_elapsed_reduction_percent: null,
    deterministic_quality_drop_percent: null,
  },
  representative,
  telemetry: {
    model_call_coverage: 'exact',
    elapsed_coverage: 'synthetic-control-only',
    token_coverage: 'unavailable',
    token_savings_claim_eligible: false,
  },
  gates: {
    deterministic_calls_at_least_30_percent: callReduction >= 30,
    representative_quality_at_most_5_percent: Boolean(
      representative && representative.coverage === 'representative-fixture'
      && representative.quality_drop_percent <= 5
    ),
    live_wall_time_at_least_30_percent: false,
    owner_gate_complete: false,
    token_savings_claimed: false,
  },
  pending: [
    'live/cost-matched baseline and variant wall-time evidence',
    'independent review of representative quality evidence',
  ],
}
if (!result.gates.deterministic_calls_at_least_30_percent
  || result.gates.owner_gate_complete
  || result.gates.live_wall_time_at_least_30_percent
  || result.gates.token_savings_claimed) {
  process.stderr.write(`${JSON.stringify(result, null, 2)}\n`)
  process.exit(1)
}
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
