export const meta = {
  name: 'studio-pairing',
  description: 'Pairing ritual broker — dev↔qa adversarial loop over a track worktree. dev implements/defends, qa produces reproducible failures, exit when qa cannot break within budget. Evidence = repro-failure ↔ defense-test pairs, not rebuttal count.',
  phases: [
    { title: 'Build', detail: 'dev implements against fixed acceptance criteria' },
    { title: 'Attack', detail: 'qa tries to produce a reproducible failure' },
    { title: 'Verdict', detail: 'critic scores defended tests vs reproduced failures' },
  ],
}

// --- inputs (producer prepares the track worktree and passes its path; this
// --- script orchestrates turns but does no filesystem I/O itself) -----------
//   args = {
//     taskSpec: string,
//     acceptanceCriteria: [string],   // FIXED for this run; changing = re-convene
//     worktreePath: string,           // track worktree the agents operate inside
//     personas: { dev: {body}, qa: {body} },
//     criticRubric: string,
//     maxRounds?: number (default 3),
//   }
const A = args || {}
const SPEC = A.taskSpec || '(no task spec)'
const CRITERIA = A.acceptanceCriteria || []
const WT = A.worktreePath
const DEV = (A.personas && A.personas.dev) || { body: 'You are the developer. Build the smallest thing that works.' }
const QA = (A.personas && A.personas.qa) || { body: 'You are QA. Your job is to break it with a reproducible failure.' }
const RUBRIC = A.criticRubric || ''
const MAX_ROUNDS = A.maxRounds || 3

if (!WT) {
  return { ritual: 'pairing', error: 'pairing needs a producer-prepared worktreePath (track isolation)', participants: ['dev', 'qa'] }
}

// --- agent model/effort policy (from .studio.yml via the producer) ----------
// precedence: run override > rituals.pairing.<step> > roles.<role> > defaults
// > omit (inherit the session). agentType stays 'general-purpose' regardless.
const POLICY = A.agentPolicy || {}
const OVERRIDE = A.overrides || {}
function policyFor(role, step) {
  const d = POLICY.defaults || {}
  const r = (POLICY.roles || {})[role] || {}
  const s = (((POLICY.rituals || {}).pairing || {})[step]) || {}
  const pick = (k) => OVERRIDE[k] ?? s[k] ?? r[k] ?? d[k] ?? null
  const opts = {}
  const m = pick('model'); if (m) opts.model = m
  const e = pick('effort'); if (e) opts.effort = e
  return opts
}

const spentStart = budget.spent()
const criteriaBlock = CRITERIA.length ? CRITERIA.map((c, i) => `  ${i + 1}. ${c}`).join('\n') : '  (none supplied)'

const CONTEXT = [
  `Task: ${SPEC}`,
  'Acceptance criteria (FIXED — do not renegotiate; a change requires re-convening):',
  criteriaBlock,
  `Work ONLY inside this worktree: ${WT}`,
].join('\n')

const DEV_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['summary', 'defended', 'unresolved'],
  properties: {
    summary: { type: 'string', description: 'what you implemented/changed this turn' },
    defended: {
      type: 'array',
      description: 'each qa failure you fixed, with the test that now guards it',
      items: {
        type: 'object', additionalProperties: false, required: ['failure_title', 'test_added'],
        properties: { failure_title: { type: 'string' }, test_added: { type: 'string' }, how: { type: 'string' } },
      },
    },
    unresolved: { type: 'array', items: { type: 'string' }, description: 'failures you could not fix this turn' },
  },
}

const QA_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['broke', 'failures'],
  properties: {
    broke: { type: 'boolean', description: 'true if you produced at least one NEW reproducible failure' },
    failures: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false, required: ['title', 'repro'],
        properties: {
          title: { type: 'string' },
          repro: { type: 'string', description: 'exact command / input that reproduces the failure' },
          severity: { type: 'string' },
        },
      },
    },
  },
}

const delta_log = []
let round = 0
let openFailures = []       // qa failures dev has not yet defended
const defendedAll = []

phase('Build')
for (round = 1; round <= MAX_ROUNDS; round++) {
  // ---- dev turn: implement, and defend any open failures with tests --------
  const devPrompt = [
    CONTEXT,
    round === 1
      ? 'Round 1. Implement the smallest thing that satisfies every acceptance criterion. Add tests for the criteria.'
      : 'Defend against QA. For EACH open failure below, fix it and add a test that now passes and guards it.',
    openFailures.length ? '\n--- open failures from QA ---\n' + JSON.stringify(openFailures, null, 2) : '',
    '\n--- you (dev) ---\n' + (DEV.body || ''),
  ].join('\n')
  const dev = await agent(devPrompt, {
    schema: DEV_SCHEMA, agentType: 'general-purpose', label: `dev:r${round}`, phase: round === 1 ? 'Build' : 'Attack', ...policyFor('dev', 'dev'),
  })
  if (dev) {
    // implementing against the criteria is itself an artifact delta — otherwise
    // a clean build qa can't break would leave delta_log empty and read as theatre.
    if (dev.summary) delta_log.push({ round, changed_what: `implemented: ${dev.summary}`, anchor: 'artifact', evidence: dev.summary })
    const defendedThisRound = new Set()
    for (const d of dev.defended || []) {
      defendedAll.push(d.failure_title)
      defendedThisRound.add(d.failure_title)
      delta_log.push({ round, changed_what: `defended: ${d.failure_title}`, anchor: 'repro-test', evidence: d.test_added })
    }
    // DEFAULT-OPEN: a reproduced failure stays open until it is explicitly
    // defended. Never trust dev.unresolved to re-enumerate everything still
    // broken — an omitted failure must not silently vanish.
    openFailures = openFailures.filter(f => !defendedThisRound.has(f.title))
  }

  // ---- qa turn: attack the current code -----------------------------------
  phase('Attack')
  const qaPrompt = [
    CONTEXT,
    'Attack the current implementation in the worktree. Produce NEW reproducible failures only — each with an exact repro command/input. Do not repeat already-open failures.',
    openFailures.length ? '\n--- already-open failures (do not repeat) ---\n' + JSON.stringify(openFailures.map(f => f.title)) : '',
    '\n--- you (qa) ---\n' + (QA.body || ''),
  ].join('\n')
  const qa = await agent(qaPrompt, {
    schema: QA_SCHEMA, agentType: 'general-purpose', label: `qa:r${round}`, phase: 'Attack', ...policyFor('qa', 'qa'),
  })
  const newFailures = qa && qa.broke ? (qa.failures || []) : []
  for (const f of newFailures) {
    openFailures.push(f)
    delta_log.push({ round, changed_what: `reproduced failure: ${f.title}`, anchor: 'risk', evidence: f.repro })
  }
  log(`round ${round}: qa produced ${newFailures.length} new failure(s), ${openFailures.length} open`)

  if (!newFailures.length) { log(`qa could not break within round ${round} → defended`); break }
}

// --- verdict: critic scores defended vs reproduced -------------------------
phase('Verdict')
const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['alive', 'reason', 'defended_count', 'open_count'],
  properties: {
    alive: { type: 'boolean' },
    reason: { type: 'string' },
    defended_count: { type: 'integer' },
    open_count: { type: 'integer' },
  },
}
const verdict = await agent([
  'You are the studio critic scoring a pairing run. Verification only — do not run the code yourself, judge the recorded evidence.',
  RUBRIC ? 'Rubric:\n' + RUBRIC : '',
  'Score by defended repro-tests vs still-open failures. Pairing evidence is repro-failure↔defense-test pairs, NOT how much talking happened.',
  'alive=true only if the acceptance criteria are met AND every reproduced failure is either defended by a test or explicitly accepted as out-of-scope.',
  '\n--- defended (failure → test) ---\n' + JSON.stringify(defendedAll, null, 2),
  '\n--- still open ---\n' + JSON.stringify(openFailures.map(f => f.title), null, 2),
  '\n--- acceptance criteria ---\n' + criteriaBlock,
].join('\n'), { schema: VERDICT_SCHEMA, label: 'critic:verdict', phase: 'Verdict', ...policyFor('critic', 'verdict') })
  || { alive: openFailures.length === 0, reason: 'critic unavailable; fell back to open-failure count', defended_count: defendedAll.length, open_count: openFailures.length }

return {
  ritual: 'pairing',
  participants: ['dev', 'qa'],
  synthesis: `Implemented against ${CRITERIA.length} criteria in ${WT}. Defended ${defendedAll.length} failure(s); ${openFailures.length} open.`,
  minority: openFailures.length ? `open failures: ${openFailures.map(f => f.title).join('; ')}` : 'none',
  delta_log,
  verdict,
  proposals: openFailures.map(f => `follow-up: resolve open failure "${f.title}"`),
  cost: { tokens: budget.spent() - spentStart, rounds: round },
}
