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
//     branch?: string,                 // track branch, passed through for integration
//     personas: { dev: {body}, qa: {body} },
//     criticRubric: string,
//     maxRounds?: number (default 3),
//   }
// defensive: a stringified args (caller passed JSON text instead of an object)
// would otherwise silently drop every field — parse it back.
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const SPEC = A.taskSpec || '(no task spec)'
const CRITERIA = A.acceptanceCriteria || []
const WT = A.worktreePath
const BRANCH = A.branch || null
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
  BRANCH ? `Track branch: ${BRANCH}` : '',
].join('\n')

const DEV_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['summary', 'defended', 'unresolved', 'changedFiles', 'verification', 'blockedChecks'],
  properties: {
    summary: { type: 'string', description: 'what you implemented/changed this turn' },
    changedFiles: { type: 'array', items: { type: 'string' }, description: 'repo-relative files changed in the track worktree' },
    verification: {
      type: 'array',
      description: 'checks you actually ran',
      items: {
        type: 'object', additionalProperties: false, required: ['command', 'result'],
        properties: {
          command: { type: 'string' },
          result: { type: 'string', description: 'pass/fail/blocked plus the short reason' },
        },
      },
    },
    blockedChecks: { type: 'array', items: { type: 'string' }, description: 'checks you could not run and why' },
    defended: {
      type: 'array',
      description: 'each open qa failure you fixed, keyed by its id, with the test that now guards it',
      items: {
        type: 'object', additionalProperties: false, required: ['failure_id', 'test_added'],
        properties: {
          failure_id: { type: 'integer', description: 'the id of the open failure you defended (from the open-failures list)' },
          test_added: { type: 'string' },
          how: { type: 'string' },
        },
      },
    },
    unresolved: { type: 'array', items: { type: 'integer' }, description: 'ids of failures you could not fix this turn' },
  },
}

const QA_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['broke', 'failures', 'verification', 'blockedChecks'],
  properties: {
    broke: { type: 'boolean', description: 'true if you produced at least one NEW reproducible failure' },
    verification: {
      type: 'array',
      description: 'attack/check commands you actually ran',
      items: {
        type: 'object', additionalProperties: false, required: ['command', 'result'],
        properties: {
          command: { type: 'string' },
          result: { type: 'string', description: 'pass/fail/blocked plus the short reason' },
        },
      },
    },
    blockedChecks: { type: 'array', items: { type: 'string' }, description: 'checks you could not run and why' },
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
let openFailures = []       // qa failures dev has not yet defended; each has a stable id
const defendedAll = []      // titles of defended failures (for the verdict prompt)
const changedFiles = new Set()
const verification = []
const blockedChecks = []
let failureSeq = 0          // monotonic id source — join key between qa and dev

phase('Build')
for (round = 1; round <= MAX_ROUNDS; round++) {
  // ---- dev turn: implement, and defend any open failures with tests --------
  const devPrompt = [
    CONTEXT,
    round === 1
      ? 'Round 1. Implement the smallest thing that satisfies every acceptance criterion. Add tests for the criteria.'
      : 'Defend against QA. For EACH open failure below, fix it and add a test that now passes and guards it. Reference each failure you fixed by its `id`.',
    'Return repo-relative changedFiles, exact verification commands you ran, and blockedChecks. Use [] when none.',
    openFailures.length ? '\n--- open failures from QA (defend by id) ---\n' + JSON.stringify(openFailures, null, 2) : '',
    '\n--- you (dev) ---\n' + (DEV.body || ''),
  ].join('\n')
  const dev = await agent(devPrompt, {
    schema: DEV_SCHEMA, agentType: 'general-purpose', label: `dev:r${round}`, phase: round === 1 ? 'Build' : 'Attack', ...policyFor('dev', 'dev'),
  })
  if (dev) {
    // implementing against the criteria is itself an artifact delta — otherwise
    // a clean build qa can't break would leave delta_log empty and read as theatre.
    if (dev.summary) delta_log.push({ round, changed_what: `implemented: ${dev.summary}`, anchor: 'artifact', evidence: dev.summary })
    for (const f of dev.changedFiles || []) changedFiles.add(f)
    for (const v of dev.verification || []) verification.push(v)
    for (const b of dev.blockedChecks || []) blockedChecks.push(b)
    // JOIN BY ID, not title: dev and qa phrase a failure differently, so an
    // exact-string join silently fails and a defended failure stays "open"
    // forever (defended and open both grow → contradictory evidence). The id is
    // the broker's own key, immune to either agent's wording.
    const openById = new Map(openFailures.map(f => [f.id, f]))
    const defendedIds = new Set()
    for (const d of dev.defended || []) {
      const f = openById.get(d.failure_id)
      if (!f) continue   // dev cited an id that isn't open — ignore, don't fabricate a defense
      defendedIds.add(d.failure_id)
      defendedAll.push(f.title)
      delta_log.push({ round, changed_what: `defended: ${f.title}`, anchor: 'repro-test', evidence: d.test_added })
    }
    // DEFAULT-OPEN: a reproduced failure stays open until its id is explicitly
    // defended — never inferred from unresolved or from title matching.
    openFailures = openFailures.filter(f => !defendedIds.has(f.id))
  }

  // ---- qa turn: attack the current code -----------------------------------
  phase('Attack')
  const qaPrompt = [
    CONTEXT,
    'Attack the current implementation in the worktree. Produce NEW reproducible failures only — each with an exact repro command/input. Do not repeat already-open failures.',
    'Return exact attack/check commands you ran and blockedChecks. Use [] when none.',
    openFailures.length ? '\n--- already-open failures (do not repeat) ---\n' + JSON.stringify(openFailures.map(f => ({ id: f.id, title: f.title }))) : '',
    '\n--- you (qa) ---\n' + (QA.body || ''),
  ].join('\n')
  const qa = await agent(qaPrompt, {
    schema: QA_SCHEMA, agentType: 'general-purpose', label: `qa:r${round}`, phase: 'Attack', ...policyFor('qa', 'qa'),
  })
  const newFailures = qa && qa.broke ? (qa.failures || []) : []
  if (qa) {
    for (const v of qa.verification || []) verification.push(v)
    for (const b of qa.blockedChecks || []) blockedChecks.push(b)
  }
  for (const f of newFailures) {
    openFailures.push({ id: failureSeq++, ...f })   // broker-assigned id = the join key
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

const readyForIntegration = Boolean(verdict.alive && openFailures.length === 0 && blockedChecks.length === 0)

return {
  ritual: 'pairing',
  participants: ['dev', 'qa'],
  synthesis: `Implemented against ${CRITERIA.length} criteria in ${WT}. Defended ${defendedAll.length} failure(s); ${openFailures.length} open.`,
  minority: openFailures.length ? `open failures: ${openFailures.map(f => f.title).join('; ')}` : 'none',
  delta_log,
  verdict,
  proposals: openFailures.map(f => `follow-up: resolve open failure "${f.title}"`),
  cost: { tokens: budget.spent() - spentStart, rounds: round },
  worktreePath: WT,
  branch: BRANCH,
  changedFiles: [...changedFiles],
  verification,
  blockedChecks,
  readyForIntegration,
}
