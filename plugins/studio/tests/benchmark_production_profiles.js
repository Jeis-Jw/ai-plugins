import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { dirname, isAbsolute, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  applyPersistentBarrier,
  createPersistentBrainstorm,
} from '../broker/persistent_brainstorm_broker.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const isolatedSource = (
  await readFile(join(HERE, '..', 'broker', 'brainstorm.workflow.js'), 'utf8')
).replace('export const meta', 'const meta')
const isolatedBroker = new AsyncFunction(
  'args',
  'budget',
  'phase',
  'parallel',
  'agent',
  'log',
  isolatedSource,
)

const corpusIndex = process.argv.indexOf('--representative-corpus')
const corpusPath = corpusIndex >= 0 ? process.argv[corpusIndex + 1] : null
const outputIndex = process.argv.indexOf('--output')
const outputPath = outputIndex >= 0 ? process.argv[outputIndex + 1] : null
if (!corpusPath) throw new Error('--representative-corpus is required')
if (outputPath && !isAbsolute(outputPath)) throw new Error('--output must be an absolute path')

const SCENARIO_IDS = Object.freeze([
  'accepted-delta',
  'rejected-delta',
  'dry-close',
  'minority-preserved',
])

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

function digest(value) {
  return `sha256:${createHash('sha256').update(canonicalJson(value), 'utf8').digest('hex')}`
}

function exactKeys(value, expected) {
  return (
    value
    && typeof value === 'object'
    && !Array.isArray(value)
    && canonicalJson(Object.keys(value).sort(unicodeCompare))
      === canonicalJson([...expected].sort(unicodeCompare))
  )
}

function reduction(before, after) {
  return Number((((before - after) / before) * 100).toFixed(2))
}

function scenarioTurn(scenario, round) {
  const turn = scenario.tape.participant_a_rounds[round - 1]
  if (!turn) throw new Error(`sealed tape lacks participant a round ${round}: ${scenario.id}`)
  return structuredClone(turn)
}

function scriptedOutput(scenario, label, submitted = []) {
  if (label.startsWith('diverge:')) {
    return structuredClone(scenario.tape.diverge)
  }
  if (label.startsWith('debate:')) {
    const round = Number(label.match(/^debate:r(\d+):/)?.[1])
    return label.endsWith(':a')
      ? scenarioTurn(scenario, round)
      : structuredClone(scenario.tape.other_participant)
  }
  if (label.startsWith('critic:r')) {
    return {
      verified: submitted.map(item => ({
        id: item.id,
        valid: scenario.tape.critic.valid,
        outcome_linked: scenario.tape.critic.outcome_linked,
        reason: scenario.tape.critic.reason,
      })),
    }
  }
  if (label === 'summarizer') return structuredClone(scenario.tape.summarizer)
  if (label === 'critic:final') return structuredClone(scenario.tape.final_verdict)
  throw new Error(`unexpected scripted label: ${label}`)
}

async function runIsolated(scenario, productionProfile) {
  let calls = 0
  const submittedByRound = new Map()
  const output = await isolatedBroker(
    {
      agenda: scenario.input.agenda,
      personas: scenario.input.personas,
      productionProfile,
      criticRubric: scenario.input.critic_rubric,
    },
    { spent: () => null },
    () => {},
    jobs => Promise.all(jobs.map(job => job())),
    async (_prompt, options) => {
      calls += 1
      if (options.label.startsWith('debate:')) {
        const round = Number(options.label.match(/^debate:r(\d+):/)?.[1])
        const result = scriptedOutput(scenario, options.label)
        if (result.deltas.length) {
          const submitted = submittedByRound.get(round) || []
          submitted.push(...result.deltas.map((delta, index) => ({
            id: submitted.length + index,
            ...delta,
          })))
          submittedByRound.set(round, submitted)
        }
        return result
      }
      if (options.label.startsWith('critic:r')) {
        const round = Number(options.label.match(/^critic:r(\d+)/)?.[1])
        return scriptedOutput(scenario, options.label, submittedByRound.get(round) || [])
      }
      return scriptedOutput(scenario, options.label)
    },
    () => {},
  )
  if (output.error) throw new Error(`isolated broker failed: ${output.error}`)
  if (output.receipt.counters.model_calls !== calls) {
    throw new Error('isolated broker model-call receipt is incomplete')
  }
  return { output, logicalModelCalls: calls }
}

function canaryCapability() {
  return {
    schema: 'studio-native-persistent-capability/v1',
    verified: true,
    spawn: true,
    followup: true,
    wait_barrier: true,
    interrupt_cancel: true,
    structured_result: true,
    card_title_projection: false,
  }
}

function persistentActionOutput(scenario, state, action) {
  if (action.actor_id.startsWith('participant:')) {
    if (action.phase === 'Diverge') {
      return structuredClone(scenario.tape.diverge)
    }
    return action.actor_id === 'participant:a'
      ? scenarioTurn(scenario, action.round)
      : structuredClone(scenario.tape.other_participant)
  }
  if (action.actor_id === 'critic:critic' && action.phase === 'Debate') {
    return scriptedOutput(scenario, `critic:r${action.round}`, state.round_submitted)
  }
  if (action.actor_id === 'summarizer:summarizer') {
    return scriptedOutput(scenario, 'summarizer')
  }
  if (action.actor_id === 'critic:critic' && action.phase === 'Verdict') {
    return scriptedOutput(scenario, 'critic:final')
  }
  throw new Error(`unexpected persistent action: ${action.actor_id}/${action.phase}`)
}

function runPersistent(scenario, productionProfile) {
  let state = createPersistentBrainstorm({
    run_id: `RUN-benchmark-persistent-${scenario.id}-${productionProfile}`,
    workflow_name: 'Studio production profile quality replay',
    agenda: scenario.input.agenda,
    admission: 'canary',
    capability: canaryCapability(),
    productionProfile,
    criticRubric: scenario.input.critic_rubric,
    personas: scenario.input.personas,
  })
  let barriers = 0
  while (state.status === 'running') {
    if (!state.pending || barriers >= 64) {
      throw new Error('persistent broker exceeded its bounded barrier contract')
    }
    const pending = state.pending
    state = applyPersistentBarrier(state, {
      schema: 'studio-crew-barrier-result/v2',
      run_id: state.run_id,
      state_revision: state.state_revision,
      state_digest: state.state_digest,
      barrier_id: pending.barrier_id,
      results: pending.actions.map(action => ({
        action_id: action.action_id,
        status: 'succeeded',
        host_handle: action.kind === 'spawn'
          ? `host-${action.actor_id}`
          : action.host_handle,
        output: persistentActionOutput(scenario, state, action),
        tokens: null,
        token_coverage: 'unavailable',
        error: null,
      })),
    })
    barriers += 1
  }
  if (state.status !== 'completed' || !state.output) {
    throw new Error(`persistent broker did not complete: ${state.status}`)
  }
  const logicalModelCalls = state.ledger.filter(entry => entry.event === 'result').length
  if (state.output.receipt.counters.model_calls !== logicalModelCalls) {
    throw new Error('persistent broker model-call receipt is incomplete')
  }
  return { output: state.output, logicalModelCalls }
}

function projection(output) {
  const valid = output.delta_log.filter(item => !item.dry)
  const dry = output.delta_log.filter(item => item.dry)
  const maxRounds = output.production_profile === 'full' ? 4 : 2
  return {
    alive: output.verdict.alive,
    theatre: output.receipt.quality.theatre,
    has_valid_delta: valid.length > 0,
    rejected_alternative_preserved: valid.some(
      item => item.rejected_alternative === 'implicit configuration',
    ),
    rejected_submission_audited: dry.length > 0,
    no_delta_logged: output.delta_log.length === 0,
    closed_before_profile_max: output.receipt.counters.rounds < maxRounds,
    minority: output.minority,
    minority_preserved: output.minority === 'retain the streaming-parser risk',
    valid_delta_count: valid.length,
    dry_delta_count: dry.length,
    rounds: output.receipt.counters.rounds,
  }
}

function validTurnTape(value) {
  return (
    exactKeys(value, ['utterance', 'deltas'])
    && typeof value.utterance === 'string'
    && Array.isArray(value.deltas)
    && value.deltas.every(delta => (
      exactKeys(delta, [
        'changed_what',
        'anchor',
        'evidence',
        'rejected_alternative',
      ])
      && ['artifact', 'acceptance-criteria', 'risk', 'rejected-alternative', 'repro-test']
        .includes(delta.anchor)
      && ['changed_what', 'evidence', 'rejected_alternative'].every(
        key => typeof delta[key] === 'string',
      )
    ))
  )
}

function validateCorpus(corpus) {
  if (!exactKeys(corpus, [
    'schema',
    'provenance',
    'sealed_at',
    'source_refs',
    'review',
    'scenarios',
    'seal_digest',
  ])) throw new Error('representative corpus root fields are invalid')
  if (
    corpus.schema !== 'studio-production-profile-replay-corpus/v3'
    || corpus.provenance !== 'sealed-independent-review'
    || !Array.isArray(corpus.source_refs)
    || corpus.source_refs.length < 1
    || !Array.isArray(corpus.scenarios)
    || canonicalJson(corpus.scenarios.map(item => item.id)) !== canonicalJson(SCENARIO_IDS)
  ) throw new Error('representative corpus is invalid')
  for (const scenario of corpus.scenarios) {
    if (
      !exactKeys(scenario, ['id', 'outcome_kind', 'input', 'tape', 'criteria'])
      || typeof scenario.outcome_kind !== 'string'
      || !exactKeys(scenario.input, ['agenda', 'critic_rubric', 'personas'])
      || typeof scenario.input.agenda !== 'string'
      || typeof scenario.input.critic_rubric !== 'string'
      || !Array.isArray(scenario.input.personas)
      || scenario.input.personas.length !== 3
      || scenario.input.personas.some(persona => (
        !exactKeys(persona, ['name', 'crew', 'role', 'prior', 'body'])
        || persona.name !== persona.crew
        || Object.values(persona).some(value => typeof value !== 'string' || !value)
      ))
      || !exactKeys(scenario.tape, [
        'diverge',
        'participant_a_rounds',
        'other_participant',
        'critic',
        'summarizer',
        'final_verdict',
      ])
      || !validTurnTape(scenario.tape.diverge)
      || !Array.isArray(scenario.tape.participant_a_rounds)
      || scenario.tape.participant_a_rounds.length !== 4
      || !scenario.tape.participant_a_rounds.every(validTurnTape)
      || !validTurnTape(scenario.tape.other_participant)
      || !exactKeys(scenario.tape.critic, ['valid', 'outcome_linked', 'reason'])
      || typeof scenario.tape.critic.valid !== 'boolean'
      || typeof scenario.tape.critic.outcome_linked !== 'boolean'
      || typeof scenario.tape.critic.reason !== 'string'
      || !exactKeys(scenario.tape.summarizer, ['synthesis', 'minority', 'proposals'])
      || typeof scenario.tape.summarizer.synthesis !== 'string'
      || typeof scenario.tape.summarizer.minority !== 'string'
      || !Array.isArray(scenario.tape.summarizer.proposals)
      || !exactKeys(scenario.tape.final_verdict, ['alive', 'reason'])
      || typeof scenario.tape.final_verdict.alive !== 'boolean'
      || typeof scenario.tape.final_verdict.reason !== 'string'
      || !Array.isArray(scenario.criteria)
      || scenario.criteria.length < 2
      || scenario.criteria.some(criterion => (
        !exactKeys(criterion, ['id', 'field', 'expected', 'minimum_score'])
        || typeof criterion.id !== 'string'
        || typeof criterion.field !== 'string'
        || !Number.isFinite(criterion.minimum_score)
        || criterion.minimum_score < 0
        || criterion.minimum_score > 100
      ))
    ) throw new Error(`representative scenario is invalid: ${scenario.id}`)
  }
  const sealed = {
    schema: corpus.schema,
    provenance: corpus.provenance,
    sealed_at: corpus.sealed_at,
    source_refs: corpus.source_refs,
    scenarios: corpus.scenarios,
  }
  if (corpus.seal_digest !== digest(sealed)) {
    throw new Error('representative corpus seal digest mismatch')
  }
  if (
    !exactKeys(corpus.review, [
      'reviewer_ref',
      'method',
      'verdict',
      'seal_digest',
      'review_digest',
    ])
    || corpus.review.method !== 'independent-semantic-review'
    || corpus.review.verdict !== 'approved'
    || corpus.review.seal_digest !== corpus.seal_digest
  ) throw new Error('representative corpus independent review is invalid')
  const review = structuredClone(corpus.review)
  delete review.review_digest
  if (corpus.review.review_digest !== digest(review)) {
    throw new Error('representative corpus review digest mismatch')
  }
  return corpus.scenarios
}

function replayReceipt(corpus, scenario, profile, implementation, run) {
  const base = {
    schema: 'studio-production-profile-replay-receipt/v1',
    evidence_class: 'sealed-scripted-broker-semantic-replay',
    corpus_seal_digest: corpus.seal_digest,
    scenario_id: scenario.id,
    scenario_input_digest: digest(scenario.input),
    scripted_response_tape_digest: digest(scenario.tape),
    implementation,
    profile,
    logical_model_calls: run.logicalModelCalls,
    broker_receipt_model_calls: run.output.receipt.counters.model_calls,
    broker_output_digest: digest(run.output),
  }
  return { ...base, receipt_digest: digest(base) }
}

function scoreScenario(corpus, scenario, baseline, variant) {
  const baselineObserved = projection(baseline.output)
  const variantObserved = projection(variant.output)
  const criteria = scenario.criteria.map(criterion => {
    if (
      !Object.hasOwn(baselineObserved, criterion.field)
      || !Object.hasOwn(variantObserved, criterion.field)
    ) throw new Error(`unknown quality criterion field: ${criterion.field}`)
    const baselineScore = canonicalJson(baselineObserved[criterion.field])
      === canonicalJson(criterion.expected) ? 100 : 0
    const variantScore = canonicalJson(variantObserved[criterion.field])
      === canonicalJson(criterion.expected) ? 100 : 0
    return {
      ...criterion,
      baseline_score: baselineScore,
      variant_score: variantScore,
      baseline_floor_passed: baselineScore >= criterion.minimum_score,
      variant_floor_passed: variantScore >= criterion.minimum_score,
    }
  })
  return {
    id: scenario.id,
    outcome_kind: scenario.outcome_kind,
    baseline: {
      profile: 'full',
      logical_model_calls: baseline.logicalModelCalls,
      output_digest: digest(baseline.output),
      observation: baselineObserved,
      replay_receipt: replayReceipt(
        corpus,
        scenario,
        'full',
        'studio-0.9-isolated-brainstorm-broker',
        baseline,
      ),
    },
    variant: {
      profile: 'standard',
      logical_model_calls: variant.logicalModelCalls,
      output_digest: digest(variant.output),
      observation: variantObserved,
      replay_receipt: replayReceipt(
        corpus,
        scenario,
        'standard',
        'persistent-brainstorm-broker',
        variant,
      ),
    },
    criteria,
  }
}

const corpus = JSON.parse(await readFile(corpusPath, 'utf8'))
const scenarios = validateCorpus(corpus)
const efficiencyScenario = scenarios.find(item => item.id === 'accepted-delta')
const efficiencyBaseline = await runIsolated(efficiencyScenario, 'full')
const efficiencyVariant = runPersistent(efficiencyScenario, 'standard')
const logicalCallReduction = reduction(
  efficiencyBaseline.logicalModelCalls,
  efficiencyVariant.logicalModelCalls,
)
const replayCases = []
for (const scenario of scenarios) {
  replayCases.push(scoreScenario(
    corpus,
    scenario,
    await runIsolated(scenario, 'full'),
    runPersistent(scenario, 'standard'),
  ))
}
const criterionResults = replayCases.flatMap(item => item.criteria)
const baselineQuality = (
  criterionResults.reduce((total, item) => total + item.baseline_score, 0)
  / criterionResults.length
)
const variantQuality = (
  criterionResults.reduce((total, item) => total + item.variant_score, 0)
  / criterionResults.length
)
const qualityDegradation = Number((baselineQuality - variantQuality).toFixed(2))
const eachCriterionFloorPassed = criterionResults.every(
  item => item.baseline_floor_passed && item.variant_floor_passed,
)

const result = {
  schema: 'studio-production-profile-benchmark/v3',
  claim_scope: 'studio-0.9-profile-efficiency-floor-preservation',
  comparison_basis: 'isolated-full-versus-persistent-standard-with-identical-scripted-scenarios',
  workload: {
    personas: efficiencyScenario.input.personas.length,
    agenda_digest: digest(efficiencyScenario.input.agenda),
    rubric_digest: digest(efficiencyScenario.input.critic_rubric),
    scenario_input_digest: digest(efficiencyScenario.input),
    scripted_response_tape_digest: digest(efficiencyScenario.tape),
  },
  baseline: {
    implementation: 'studio-0.9-isolated-brainstorm-broker',
    profile: 'full',
    logical_model_calls: efficiencyBaseline.logicalModelCalls,
    receipt_model_calls: efficiencyBaseline.output.receipt.counters.model_calls,
    output_digest: digest(efficiencyBaseline.output),
    replay_receipt: replayReceipt(
      corpus,
      efficiencyScenario,
      'full',
      'studio-0.9-isolated-brainstorm-broker',
      efficiencyBaseline,
    ),
  },
  variant: {
    implementation: 'persistent-brainstorm-broker',
    profile: 'standard',
    logical_model_calls: efficiencyVariant.logicalModelCalls,
    receipt_model_calls: efficiencyVariant.output.receipt.counters.model_calls,
    output_digest: digest(efficiencyVariant.output),
    replay_receipt: replayReceipt(
      corpus,
      efficiencyScenario,
      'standard',
      'persistent-brainstorm-broker',
      efficiencyVariant,
    ),
  },
  calculations: {
    logical_model_call_reduction_percent: logicalCallReduction,
    quality_degradation_percent: qualityDegradation,
  },
  quality_replay: {
    evidence_class: 'sealed-scripted-broker-semantic-replay',
    seal_digest: corpus.seal_digest,
    independent_review: corpus.review,
    cases: replayCases,
    baseline_quality_score: baselineQuality,
    variant_quality_score: variantQuality,
    quality_degradation_percent: qualityDegradation,
    each_criterion_floor_passed: eachCriterionFloorPassed,
  },
  telemetry: {
    logical_model_call_coverage: 'exact-broker-receipt-and-result-ledger',
    elapsed_coverage: 'unavailable',
    token_coverage: 'unavailable',
    physical_process_coverage: 'not-measured',
  },
  gates: {
    baseline_full_exactly_21_logical_calls:
      efficiencyBaseline.logicalModelCalls === 21,
    variant_standard_exactly_13_logical_calls:
      efficiencyVariant.logicalModelCalls === 13,
    studio_0_9_profile_logical_call_reduction_at_least_30_percent:
      logicalCallReduction >= 30,
    quality_degradation_at_most_5_percent:
      qualityDegradation <= 5,
    each_quality_criterion_floor_passed: eachCriterionFloorPassed,
  },
  limits: [
    'the 38.10 percent result compares full and standard profiles; it is not a native adapter savings claim',
    'scripted broker replay tests orchestration semantics, not live model quality',
    'live app-server lifecycle evidence is produced by the separate native live canary',
    'wall-time, token, and physical-process savings are not claimed',
  ],
}

if (!Object.values(result.gates).every(Boolean)) {
  process.stderr.write(`${JSON.stringify(result, null, 2)}\n`)
  process.exit(1)
}
const encoded = `${JSON.stringify(result, null, 2)}\n`
if (outputPath) await writeFile(outputPath, encoded, { mode: 0o600 })
process.stdout.write(encoded)
