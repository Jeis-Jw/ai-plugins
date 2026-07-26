import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const source = (await readFile(join(HERE, '..', 'broker', 'brainstorm.workflow.js'), 'utf8'))
  .replace('export const meta', 'const meta')
const broker = new AsyncFunction('args', 'budget', 'phase', 'parallel', 'agent', 'log', source)
const delayMs = 15

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
      await new Promise(resolve => setTimeout(resolve, delayMs))
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
const elapsedReduction = reduction(baseline.elapsed_ms, variant.elapsed_ms)
const qualityDrop = baseline.quality.outcome_linked_delta_score - variant.quality.outcome_linked_delta_score
const result = {
  schema: 'studio-production-profile-benchmark/v1',
  workload: 'bounded-parser-contract',
  fixed_criterion: 'AC-1',
  fixed_rubric: true,
  baseline,
  variant,
  calculations: {
    call_reduction_percent: callReduction,
    elapsed_reduction_percent: elapsedReduction,
    criterion_pass_drop_percent: baseline.quality.criterion_pass === variant.quality.criterion_pass ? 0 : 100,
    outcome_linked_delta_drop_percent: qualityDrop,
  },
  telemetry: {
    model_call_coverage: 'exact',
    elapsed_coverage: 'exact',
    token_coverage: 'unavailable',
    token_savings_claim_eligible: false,
  },
  gates: {
    calls_at_least_30_percent: callReduction >= 30,
    elapsed_at_least_30_percent: elapsedReduction >= 30,
    quality_drop_at_most_5_percent: qualityDrop <= 5,
    token_savings_claimed: false,
  },
}
if (!Object.values(result.gates).every(value => value === true || value === false)
  || !result.gates.calls_at_least_30_percent
  || !result.gates.elapsed_at_least_30_percent
  || !result.gates.quality_drop_at_most_5_percent
  || result.gates.token_savings_claimed) {
  process.stderr.write(`${JSON.stringify(result, null, 2)}\n`)
  process.exit(1)
}
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
