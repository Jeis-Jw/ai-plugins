export const meta = {
  name: 'studio-brainstorm',
  description: 'Brainstorm ritual broker — diverge → debate → judge(critic) → converge. Personas relay via transcript; an independent critic verifies each round\'s submitted deltas by the anchor rule; dry rounds close the meeting.',
  phases: [
    { title: 'Diverge', detail: 'each persona proposes independently, blind to the others' },
    { title: 'Debate', detail: 'personas rebut/refine/propose over the shared transcript' },
    { title: 'Converge', detail: 'broker summarizer synthesizes; critic verdicts the delta_log' },
  ],
}

// --- inputs (producer loads all disk I/O and passes them here; this script is
// --- pure orchestration — the Workflow sandbox has no filesystem access) -----
//   args = {
//     agenda: string,
//     personas: [{ name, role, prior, body }],   // body = the persona's prompt text
//     criticRubric: string,                       // critic/rubric.md contents
//     maxRounds?: number (default 4),
//     dryStop?: number  (default 2),
//   }
const A = args || {}
const AGENDA = A.agenda || '(no agenda provided)'
const PERSONAS = (A.personas || []).filter(Boolean)
const RUBRIC = A.criticRubric || 'Reject any delta whose changed_what has no concrete anchor.'
const MAX_ROUNDS = A.maxRounds || 4
const DRY_STOP = A.dryStop || 2
const ANCHORS = ['artifact', 'acceptance-criteria', 'risk', 'rejected-alternative', 'repro-test']

if (PERSONAS.length < 2) {
  return { ritual: 'brainstorm', error: 'brainstorm needs >=2 personas with distinct priors', participants: PERSONAS.map(p => p.name) }
}

// --- agent model/effort policy (from .studio.yml via the producer) ----------
// precedence: run override > rituals.brainstorm.<step> > roles.<role> > defaults
// > omit (inherit the session). Blank/null anywhere falls through.
const POLICY = A.agentPolicy || {}
const OVERRIDE = A.overrides || {}
function policyFor(role, step) {
  const d = POLICY.defaults || {}
  const r = (POLICY.roles || {})[role] || {}
  const s = (((POLICY.rituals || {}).brainstorm || {})[step]) || {}
  const pick = (k) => OVERRIDE[k] ?? s[k] ?? r[k] ?? d[k] ?? null
  const opts = {}
  const m = pick('model'); if (m) opts.model = m
  const e = pick('effort'); if (e) opts.effort = e
  return opts
}

const spentStart = budget.spent()

// Prompt layout is deliberately transcript-FIRST, persona-LAST so the long,
// append-only transcript stays a stable cache prefix across turns and personas.
const SYSTEM = [
  'You are a crew member in a studio brainstorm. Rules of the room:',
  '- Only rebut, refine, or propose something NEW. Agreement-summaries are not contributions.',
  '- When you claim your turn changed the shared state, log it as a delta with a concrete anchor.',
  `- A delta's anchor MUST be one of: ${ANCHORS.join(', ')}. No anchor = not a delta.`,
  `Agenda: ${AGENDA}`,
].join('\n')

function personaTurnPrompt(transcript, persona, instruction) {
  // SYSTEM + transcript first (cacheable prefix), persona + instruction last.
  return [
    SYSTEM,
    '\n--- transcript so far ---\n' + (transcript || '(empty — you are opening)'),
    '\n--- you ---',
    `name: ${persona.name} | role: ${persona.role} | prior: ${persona.prior}`,
    persona.body || '',
    '\n--- your task ---',
    instruction,
  ].join('\n')
}

const TURN_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['utterance', 'deltas'],
  properties: {
    utterance: { type: 'string', description: 'your contribution this turn (rebut/refine/propose-new)' },
    deltas: {
      type: 'array',
      description: 'state changes you claim this turn made; [] if none',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['changed_what', 'anchor'],
        properties: {
          changed_what: { type: 'string' },
          anchor: { type: 'string', enum: ANCHORS },
          evidence: { type: 'string' },
          rejected_alternative: { type: 'string' },
        },
      },
    },
  },
}

const CRITIC_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['verified'],
  properties: {
    verified: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['id', 'valid', 'reason'],   // id echoes the submitted delta it verifies
        properties: {
          id: { type: 'integer', description: 'the id of the submitted delta this verdict is for' },
          valid: { type: 'boolean' },
          reason: { type: 'string' },
        },
      },
    },
  },
}

function criticPrompt(submitted) {
  // Critic is VERIFICATION-ONLY: it never invents or upgrades a delta, only
  // checks the ones the participants submitted against the anchor rule. Verdicts
  // are joined back to submissions by `id`, never by position — so a reordered
  // or short critic response cannot mis-attribute validity.
  return [
    'You are the studio critic. You are NOT a participant and you do NOT propose ideas.',
    'Verify ONLY the deltas submitted below. Do not create or strengthen any delta.',
    'Rubric:\n' + RUBRIC,
    `A delta is valid only if changed_what has a real anchor in {${ANCHORS.join(', ')}}.`,
    'A restated agreement, a vibe, or an intention with no anchor is invalid.',
    'Return exactly one verdict per submitted delta, each echoing that delta\'s `id`.',
    '\n--- submitted deltas this round (each has an id) ---',
    JSON.stringify(submitted, null, 2),
  ].join('\n')
}

// --- diverge: blind parallel proposals -------------------------------------
phase('Diverge')
const seeds = await parallel(
  PERSONAS.map((p, i) => () =>
    agent(personaTurnPrompt('', p, 'Open the room: give your independent take on the agenda. You cannot see the others yet.'),
      { schema: TURN_SCHEMA, label: `diverge:${p.name}`, phase: 'Diverge', ...policyFor(p.name, 'diverge') })
      .then(r => ({ name: p.name, ...r }))
  )
)
let transcript = seeds
  .filter(Boolean)
  .map(s => `[diverge] ${s.name}: ${s.utterance}`)
  .join('\n\n')

const deltaLog = []   // critic-verified deltas (drive the alive verdict)
const dryLog = []     // rejected submissions, kept for the minutes audit trail
let dryCount = 0
let roundsRun = 0

// --- debate: sequential turns over the shared transcript -------------------
phase('Debate')
for (let round = 1; round <= MAX_ROUNDS; round++) {
  roundsRun = round
  const roundSubmitted = []
  for (const p of PERSONAS) {
    const turn = await agent(
      personaTurnPrompt(transcript, p,
        `Round ${round}. React to the transcript: rebut, refine, or propose something new — no agreement-summaries. Log any real delta with its anchor.`),
      { schema: TURN_SCHEMA, label: `debate:r${round}:${p.name}`, phase: 'Debate', ...policyFor(p.name, 'debate') })
    if (!turn) continue
    transcript += `\n\n[r${round}] ${p.name}: ${turn.utterance}`
    // stable id = position in roundSubmitted; the critic echoes it back so
    // verdicts join by identity, never by array position.
    for (const d of turn.deltas || []) roundSubmitted.push({ id: roundSubmitted.length, round, by: p.name, ...d })
  }

  const critique = await agent(criticPrompt(roundSubmitted),
    { schema: CRITIC_SCHEMA, label: `critic:r${round}`, phase: 'Debate', ...policyFor('critic', 'critic') })
  const byId = new Map(((critique && critique.verified) || []).map(v => [v.id, v]))
  let validThisRound = 0
  for (const s of roundSubmitted) {
    const v = byId.get(s.id)
    // defence-in-depth: accept only when THIS delta's own verdict is valid AND
    // its anchor is genuinely in the allowed set (TURN_SCHEMA enum-guards it,
    // but re-assert so a hollow submission can never slip through).
    if (v && v.valid && ANCHORS.includes(s.anchor)) {
      deltaLog.push({ round, changed_what: s.changed_what, anchor: s.anchor, evidence: s.evidence, rejected_alternative: s.rejected_alternative })
      validThisRound++
    } else {
      dryLog.push({ round, changed_what: s.changed_what, anchor: s.anchor, dry: true })
    }
  }

  const roundDry = validThisRound === 0
  log(`round ${round}: ${roundSubmitted.length} submitted, ${validThisRound} valid${roundDry ? ' — DRY' : ''}`)
  if (roundDry) {
    if (++dryCount >= DRY_STOP) { log(`dry x${dryCount} → closing`); break }
  } else {
    dryCount = 0
  }
}

// --- converge: broker summarizer (NOT a persona, NOT the producer) ---------
phase('Converge')
const SYNTH_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['synthesis', 'minority', 'proposals'],
  properties: {
    synthesis: { type: 'string' },
    minority: { type: 'string', description: 'dissent worth preserving, or "none"' },
    proposals: { type: 'array', items: { type: 'string' }, description: 'backlog proposals raised, [] if none' },
  },
}
const synth = await agent([
  'You are the broker summarizer. You are neutral — not a persona, not the producer.',
  'Summarize the transcript into a consensus + preserved minority. Do NOT invent new positions.',
  'List any backlog proposals the crew raised (spontaneous initiatives).',
  '\n--- transcript ---\n' + transcript,
  '\n--- verified deltas (do not add to these) ---\n' + JSON.stringify(deltaLog, null, 2),
].join('\n'), { schema: SYNTH_SCHEMA, label: 'summarizer', phase: 'Converge', ...policyFor('summarizer', 'converge') }) || { synthesis: '(summarizer failed)', minority: 'none', proposals: [] }

// final critic verdict on the accumulated delta_log
const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['alive', 'reason'],
  properties: { alive: { type: 'boolean' }, reason: { type: 'string' } },
}
const verdict = await agent([
  'You are the studio critic giving the final verdict. Verification only.',
  'alive=true only if the verified delta_log below shows the debate actually moved the state',
  '(new/changed acceptance-criteria, risks, rejected alternatives, artifacts, or repro-tests).',
  'An empty or anchor-less delta_log means theatre: alive=false.',
  '\n--- verified delta_log ---\n' + JSON.stringify(deltaLog, null, 2),
].join('\n'), { schema: VERDICT_SCHEMA, label: 'critic:final', phase: 'Converge', ...policyFor('critic', 'verdict') }) || { alive: deltaLog.length > 0, reason: 'critic unavailable; fell back to delta count' }

// output delta_log = verified deltas + dry-marked rejects (audit trail for the
// minutes); studio.py counts only the non-dry, anchored ones as evidence.
const outDeltas = [...deltaLog, ...dryLog].sort((a, b) => (a.round || 0) - (b.round || 0))
return {
  ritual: 'brainstorm',
  participants: PERSONAS.map(p => p.name),
  synthesis: synth.synthesis,
  minority: synth.minority,
  delta_log: outDeltas,
  verdict,
  proposals: synth.proposals || [],
  cost: { tokens: budget.spent() - spentStart, rounds: roundsRun },
}
