import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { promisify } from 'node:util'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const execFileAsync = promisify(execFile)
const HERE = dirname(fileURLToPath(import.meta.url))
const SCRIPT = join(HERE, 'benchmark_production_profiles.js')
const CORPUS = join(HERE, 'fixtures', 'production_profile_replay_corpus.json')

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => (
      `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    )).join(',')}}`
  }
  return JSON.stringify(value)
}

function digest(value) {
  return `sha256:${createHash('sha256').update(canonicalJson(value), 'utf8').digest('hex')}`
}

function reseal(corpus) {
  const sealed = {
    schema: corpus.schema,
    provenance: corpus.provenance,
    sealed_at: corpus.sealed_at,
    source_refs: corpus.source_refs,
    scenarios: corpus.scenarios,
  }
  corpus.seal_digest = digest(sealed)
  corpus.review.seal_digest = corpus.seal_digest
  const review = structuredClone(corpus.review)
  delete review.review_digest
  corpus.review.review_digest = digest(review)
}

test('0.9 full-to-persistent-standard profile benchmark hard-gates calls and replay quality', async t => {
  const root = await mkdtemp(join(tmpdir(), 'studio-production-benchmark-'))
  t.after(async () => rm(root, { recursive: true, force: true }))
  const output = join(root, 'receipt.json')
  const { stdout } = await execFileAsync(process.execPath, [
    SCRIPT,
    '--representative-corpus',
    CORPUS,
    '--output',
    output,
  ])
  const receipt = JSON.parse(stdout)
  assert.deepEqual(JSON.parse(await readFile(output, 'utf8')), receipt)
  assert.equal(receipt.claim_scope, 'studio-0.9-profile-efficiency-floor-preservation')
  assert.equal(receipt.baseline.profile, 'full')
  assert.equal(receipt.variant.profile, 'standard')
  assert.equal(receipt.baseline.logical_model_calls, 21)
  assert.equal(receipt.baseline.receipt_model_calls, 21)
  assert.equal(receipt.variant.logical_model_calls, 13)
  assert.equal(receipt.variant.receipt_model_calls, 13)
  assert.equal(receipt.calculations.logical_model_call_reduction_percent, 38.1)
  assert.equal(receipt.calculations.quality_degradation_percent, 0)
  assert.equal(receipt.quality_replay.cases.length, 4)
  assert.equal(receipt.quality_replay.each_criterion_floor_passed, true)
  assert.ok(receipt.quality_replay.cases.every(item => (
    /^sha256:[0-9a-f]{64}$/.test(item.baseline.output_digest)
    && /^sha256:[0-9a-f]{64}$/.test(item.variant.output_digest)
    && item.criteria.every(criterion => (
      criterion.baseline_floor_passed && criterion.variant_floor_passed
    ))
  )))
  assert.ok(Object.values(receipt.gates).every(Boolean))
  assert.equal(receipt.telemetry.elapsed_coverage, 'unavailable')
  assert.equal(receipt.telemetry.token_coverage, 'unavailable')
  assert.equal(receipt.telemetry.physical_process_coverage, 'not-measured')
  assert.match(receipt.limits.join('\n'), /not a native adapter savings claim/)
})

test('corpus mutation without a new seal fails before replay', async t => {
  const root = await mkdtemp(join(tmpdir(), 'studio-production-benchmark-seal-'))
  t.after(async () => rm(root, { recursive: true, force: true }))
  const corpus = JSON.parse(await readFile(CORPUS, 'utf8'))
  corpus.scenarios[0].criteria[0].expected = false
  const forgedCorpus = join(root, 'forged-corpus.json')
  await writeFile(forgedCorpus, `${JSON.stringify(corpus)}\n`, { mode: 0o600 })
  await assert.rejects(
    execFileAsync(process.execPath, [
      SCRIPT,
      '--representative-corpus',
      forgedCorpus,
    ]),
    error => (
      error.code === 1
      && /representative corpus seal digest mismatch/.test(error.stderr)
    ),
  )
})

test('resealed wrong expectation still fails the per-criterion quality floor', async t => {
  const root = await mkdtemp(join(tmpdir(), 'studio-production-benchmark-floor-'))
  t.after(async () => rm(root, { recursive: true, force: true }))
  const corpus = JSON.parse(await readFile(CORPUS, 'utf8'))
  corpus.scenarios[0].criteria[0].expected = false
  reseal(corpus)
  const forgedCorpus = join(root, 'forged-corpus.json')
  await writeFile(forgedCorpus, `${JSON.stringify(corpus)}\n`, { mode: 0o600 })
  await assert.rejects(
    execFileAsync(process.execPath, [
      SCRIPT,
      '--representative-corpus',
      forgedCorpus,
    ]),
    error => (
      error.code === 1
      && /"each_quality_criterion_floor_passed": false/.test(error.stderr)
    ),
  )
})
