import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile, realpath } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  controllerRequestFromProductionWorkload,
  liveCanaryReceiptDigest,
  validateCanaryFixture,
  validateLiveCanaryReceipt,
} from '../scripts/persistent_native_live_canary.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const FIXTURE_PATH = join(HERE, 'fixtures', 'persistent_native_live_canary.json')
const SCRIPT_PATH = join(HERE, '..', 'scripts', 'persistent_native_live_canary.mjs')

async function fixture() {
  return JSON.parse(await readFile(await realpath(FIXTURE_PATH), 'utf8'))
}

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
  return `sha256:${createHash('sha256').update(canonicalJson(value)).digest('hex')}`
}

function deterministicLiveReceipt(value) {
  const hash = suffix => digest(suffix)
  const cwd = '/private/tmp/studio-native-live-canary-fixture/synthetic-workspace'
  const target = `${cwd}/${value.synthetic.write_probe_name}`
  const executionScope = {
    evidence_class: 'trusted-local-observation',
    workspace_kind: 'dedicated-synthetic-temp',
    agent_cwd: cwd,
    agent_cwd_ref: digest(cwd),
    repository_cwd_used_by_agent: false,
    workspace_entries: [],
    instruction_source_files: [],
    sensitive_input_supplied: false,
    model_tool_surface: 'context-only-empty',
    repository_mutation_allowed: false,
    agent_tool_network_access: false,
    sandbox_network_access: false,
    provider_model_transport: 'required-outside-agent-tool-sandbox',
    auth_snapshot_hygiene_only: true,
    credential_confidentiality_guaranteed: false,
    same_user_filesystem_read_confidentiality: 'out-of-scope',
  }
  const emptyTools = {
    command_executions: 0,
    command_actions: [],
    executions: [],
  }
  const action = (ordinal, thread, output, overrides = {}) => ({
    ordinal,
    schema: 'studio-native-action-receipt/v1',
    action_ref: hash(`action-${ordinal}`),
    actor_ref: hash(`actor-${thread}`),
    host_thread_id: thread,
    host_turn_id: `turn-${ordinal}`,
    terminal_status: 'completed',
    error_code: null,
    output,
    tool_evidence: structuredClone(emptyTools),
    binary_digest: value.contract.binary_digest,
    schema_digest: value.contract.schema_digest,
    config_digest: value.contract.config_digest,
    environment_digest: hash('environment'),
    receipt_digest: hash(`receipt-${ordinal}`),
    ...overrides,
  })
  const actions = [
    action(1, 'thread-context', { nonce: value.synthetic.context_nonce }),
    action(2, 'thread-barrier', { answer: value.synthetic.role_b_answer }),
    action(3, 'thread-context', { remembered_nonce: value.synthetic.context_nonce }),
    action(4, 'thread-context', { candidate: value.synthetic.malformed_candidate }),
    action(5, 'thread-context', {
      answer: value.synthetic.repaired_answer,
      context_nonce: value.synthetic.context_nonce,
    }),
    action(6, 'thread-interrupt', null, {
      schema: 'studio-native-interrupt-receipt/v1',
      terminal_status: 'interrupted',
      output: null,
      tool_evidence: null,
    }),
  ]
  const observations = Array.from({ length: 8 }, (_, index) => {
    const base = {
      schema: 'studio-native-auth-absence-observation/v1',
      evidence_class: 'trusted-local-observation',
      checkpoint: `checkpoint-${index + 1}`,
      absent: true,
      observed_at: `2026-07-28T00:00:${String(index).padStart(2, '0')}.000Z`,
      auth_path_ref: hash(`auth-path-${index}`),
      config_digest: value.contract.config_digest,
      environment_digest: hash('environment'),
    }
    return { ...base, evidence_digest: digest(base) }
  })
  const cleanup = [
    'thread-context', 'thread-barrier', 'thread-interrupt',
  ].map(thread => {
    const base = {
      schema: 'studio-native-cleanup-receipt/v1',
      actor_ref: hash(`actor-${thread}`),
      host_thread_id: thread,
      background_terminals: 0,
      deleted: true,
      deletion_notified: true,
      rollout_absent: true,
      rollout_path_ref: hash(`rollout-${thread}`),
      config_digest: value.contract.config_digest,
      environment_digest: hash('environment'),
    }
    return { ...base, receipt_digest: digest(base) }
  })
  const writeBase = {
    schema: 'studio-native-readonly-write-probe/v1',
    evidence_class: 'trusted-local-observation',
    command_argv: ['/usr/bin/touch', '--', target],
    command_digest: hash(['/usr/bin/touch', '--', target]),
    cwd_ref: hash('synthetic-cwd'),
    target_ref: `sha256:${createHash('sha256').update(target).digest('hex')}`,
    permission_profile: ':read-only',
    sandbox_mode: 'readOnly',
    sandbox_network_access: false,
    exit_code: 1,
    denial_kind: 'eperm',
    target_absent: true,
    stdout_digest: hash('stdout'),
    stderr_digest: hash('stderr'),
    config_digest: value.contract.config_digest,
    environment_digest: hash('environment'),
  }
  const writeObservation = { ...writeBase, evidence_digest: digest(writeBase) }
  const captureBase = {
    schema: 'studio-native-tool-inventory-capture/v1',
    evidence_class: 'live-loopback-raw-request',
    captured: true,
    provider_scope: 'loopback-only',
    model: 'fixture-model',
    reasoning_effort: 'medium',
    tool_count: 0,
    tools: [],
    raw_tools_digest: digest([]),
    capture_ref: digest([]),
    request_projection_digest: hash('request-projection'),
    base_config_digest: value.contract.config_digest,
    capture_config_digest: hash('capture-config'),
    provider_delta_digest: hash('provider-delta'),
  }
  const capture = { ...captureBase, evidence_digest: digest(captureBase) }
  const controllerCleanup = ['controller-a', 'controller-b', 'controller-critic', 'controller-summary']
    .map(thread => ({
      schema: 'studio-native-cleanup-receipt/v1',
      actor_ref: hash(`actor-${thread}`),
      host_thread_id: thread,
      deleted: true,
      deletion_notified: true,
      rollout_absent: true,
      rollout_path_ref: hash(`rollout-${thread}`),
      config_digest: value.contract.config_digest,
      environment_digest: hash('controller-environment'),
      receipt_digest: hash(`cleanup-${thread}`),
    }))
  const controllerActionPlan = [
    ['participant:alpha', 'spawn', 'controller-a'],
    ['participant:beta', 'spawn', 'controller-b'],
    ['participant:alpha', 'followup', 'controller-a'],
    ['participant:beta', 'followup', 'controller-b'],
    ['critic:critic', 'spawn', 'controller-critic'],
    ['summarizer:summarizer', 'spawn', 'controller-summary'],
    ['critic:critic', 'followup', 'controller-critic'],
  ]
  const controllerActions = controllerActionPlan.map(([actorId, kind, thread], index) => {
    const ordinal = index + 1
    return {
    action_id: `LIVE-CONTROLLER:a${String(ordinal).padStart(4, '0')}`,
    ordinal,
    actor_id: actorId,
    kind,
    stage: 'terminal_event',
    action_ref: hash(`controller-action-${ordinal}`),
    host_thread_id: thread,
    host_turn_id: `controller-turn-${ordinal}`,
    receipt_schema: 'studio-native-action-receipt/v1',
    receipt_digest: hash(`controller-receipt-${ordinal}`),
    result_status: 'succeeded',
    applied_state_revision: ordinal + 2,
    }
  })
  const stateRef = {
    run_id: 'LIVE-CONTROLLER',
    state_revision: 9,
    state_digest: hash('controller-state'),
  }
  const workflowBase = {
    schema: 'studio-persistent-production-workflow-receipt/v1',
    evidence_class: 'adapter-owned-production-chain',
    run_id: 'LIVE-CONTROLLER',
    admission: {
      evidence_class: 'adapter-owned-production-admission',
      admission_evidence_digest: hash('controller-admission'),
      tool_inventory_evidence_digest: hash('controller-tool-inventory'),
      tool_inventory_capture_ref: hash('controller-tool-capture'),
      actual_model: 'controller-model',
      actual_reasoning_effort: 'medium',
    },
    execution_input: {
      request_digest: digest(controllerRequestFromProductionWorkload(
        value.production_workload,
        'LIVE-CONTROLLER',
      )),
      concurrency: value.production_workload.max_concurrency,
      cwd_ref: digest(cwd),
    },
    state_ref: stateRef,
    envelope_digest: hash('controller-envelope'),
    journal: {
      schema: 'studio-native-dispatch-journal/v1',
      status: 'tombstoned',
      journal_revision: 17,
      journal_digest: hash('controller-journal'),
      state_ref: stateRef,
      dispatch_started: true,
      native_response_received: true,
      tombstone: {
        at: '2026-07-28T00:00:40.000Z',
        cleanup: 'complete',
        cleanup_receipts: controllerCleanup,
      },
    },
    action_receipts: controllerActions,
    cleanup_receipts: controllerCleanup,
    raw_state_exposed: false,
    fallback_allowed: false,
  }
  const workflowReceipt = {
    ...workflowBase,
    receipt_digest: digest(workflowBase),
  }
  const actionReceipts = [
    ...actions.map((item, index) => ({
      source: 'manual-probe',
      action_id: null,
      action_ref: item.action_ref,
      host_thread_id: item.host_thread_id,
      host_turn_id: item.host_turn_id,
      receipt_schema: item.schema,
      receipt_digest: item.receipt_digest,
      ordinal: index + 1,
    })),
    ...controllerActions.map((item, index) => ({
      source: 'production-controller',
      action_id: item.action_id,
      action_ref: item.action_ref,
      host_thread_id: item.host_thread_id,
      host_turn_id: item.host_turn_id,
      receipt_schema: item.receipt_schema,
      receipt_digest: item.receipt_digest,
      ordinal: actions.length + index + 1,
    })),
  ]
  const raw = {
    admission: {
      inventory: {
        enabled_features: [],
        removed_features: [],
        enabled_local_execution_features: [],
        permission_profiles: [':read-only'],
        hooks: 0,
        hook_errors: 0,
        hook_warnings: 0,
        skills: 0,
        skill_errors: 0,
        plugins: 0,
        plugin_load_errors: 0,
        apps: 0,
        mcp_servers: 0,
      },
      tool_inventory_capture: capture,
    },
    execution_scope: executionScope,
    roles: [
      { actor_id: 'canary:context-a', host_thread_id: 'thread-context' },
      { actor_id: 'canary:barrier-b', host_thread_id: 'thread-barrier' },
      { actor_id: 'canary:interrupt', host_thread_id: 'thread-interrupt' },
    ],
    barrier: { width: 2, elapsed_ms: 1, results: [actions[0], actions[1]] },
    context: { first: actions[0], followup: actions[2] },
    repair: {
      initial: actions[3],
      initial_semantic_valid: false,
      repaired: actions[4],
      same_thread: true,
      repair_attempts: 1,
    },
    auth: {
      auth_snapshot_removed: true,
      auth_snapshot_hygiene_only: true,
      content_read: false,
      credential_confidentiality_guaranteed: false,
      same_user_filesystem_read_confidentiality: 'out-of-scope',
      filesystem_observations: observations,
    },
    interrupt: {
      binding: {
        host_thread_id: 'thread-interrupt',
        host_turn_id: 'turn-6',
        action_ref: actions[5].action_ref,
      },
      receipt: actions[5],
      lifecycle: {
        schema: 'studio-native-turn-lifecycle-evidence/v1',
        host_thread_id: 'thread-interrupt',
        host_turn_id: 'turn-6',
        state: 'interrupted',
        terminal_status: 'interrupted',
        late_result_tombstone: true,
      },
    },
    cleanup,
    late_result: {
      rejected: true,
      code: 'late_result',
      tombstoned: true,
      host_thread_id: 'thread-interrupt',
      host_turn_id: 'turn-6',
    },
    write_denial: {
      target,
      observation: writeObservation,
    },
    production_chain: {
      branded: true,
      ok: true,
      status: 'completed',
      execution_path: 'persistent-native-app-server',
      fallback_allowed: false,
      projection: {
        state_ref: stateRef,
        envelope_schema: 'studio-persistent-brainstorm-envelope/v2',
        status: 'completed',
        native_started: true,
        fallback_allowed: false,
        workload_binding: {
          workload_digest: digest(value.production_workload),
          controller_request_digest: workflowReceipt.execution_input.request_digest,
          controller_run_id: workflowReceipt.run_id,
          concurrency: workflowReceipt.execution_input.concurrency,
          cwd_ref: workflowReceipt.execution_input.cwd_ref,
          actual_model: workflowReceipt.admission.actual_model,
          actual_reasoning_effort: workflowReceipt.admission.actual_reasoning_effort,
          model_evidence: 'controller-workflow-admission-receipt',
        },
        controller_counters: {
          model_calls: controllerActions.length,
          terminal_action_count: controllerActions.length,
          fresh_role_threads: 4,
          same_thread_followups: 3,
          rounds: 1,
          participants: 2,
        },
        broker_output: {
          delta_log_count: 2,
          verdict: { alive: true },
          receipt: {
            counters: {
              valid_deltas: 2,
              dry_deltas: 0,
            },
            quality: {
              alive: true,
              theatre: false,
            },
          },
        },
        raw_state_exposed: false,
      },
      workflow_receipt: workflowReceipt,
    },
    action_receipts: actionReceipts,
  }
  const contract = {
    ...value.contract,
    executable: '/Applications/ChatGPT.app/Contents/Resources/codex',
    admission_evidence_digest: hash('admission'),
    environment_digest: hash('environment'),
    tool_inventory_capture_ref: capture.capture_ref,
    tool_inventory_evidence_digest: capture.evidence_digest,
    tool_inventory_provider_delta_digest: capture.provider_delta_digest,
  }
  const receipt = {
    schema: 'studio-native-live-canary-receipt/v1',
    evidence_class: 'live-bundled-app-server',
    attestation_scope: 'trusted-local-observation-bound-to-adapter-receipts',
    run_id: 'LIVE-deterministic-shape',
    fixture_digest: digest(value),
    synthetic_input: true,
    execution_scope: executionScope,
    started_at: '2026-07-28T00:00:00.000Z',
    finished_at: '2026-07-28T00:01:00.000Z',
    contract,
    limits: structuredClone(value.limits),
    checks: value.required_checks.map(name => ({
      name,
      passed: true,
      raw_evidence: { source: 'deterministic-live-shape' },
    })),
    raw_evidence: raw,
    telemetry: {
      model_turns: actionReceipts.length,
      model_turn_coverage: 'exact',
      tokens: null,
      token_coverage: 'unavailable',
      elapsed_ms: 60_000,
      wall_time_coverage: 'exact',
    },
    passed: true,
    receipt_digest: null,
  }
  receipt.receipt_digest = liveCanaryReceiptDigest(receipt)
  return receipt
}

test('canary fixture is exact pinned synthetic input and never live evidence', async () => {
  const value = await fixture()
  assert.equal(validateCanaryFixture(value), value)
  assert.equal(value.evidence_class, 'synthetic-non-sensitive-input-only')
  assert.throws(
    () => validateLiveCanaryReceipt(value, value),
    /live receipt root fields differ/,
  )
})

test('canary fixture pin drift and required-check reorder fail closed', async () => {
  const pinDrift = await fixture()
  pinDrift.contract.version = 'codex-cli unpinned'
  assert.throws(
    () => validateCanaryFixture(pinDrift),
    /exact bundled app-server pins/,
  )

  const reordered = await fixture()
  reordered.required_checks.reverse()
  assert.throws(
    () => validateCanaryFixture(reordered),
    /required_checks order or membership drifted/,
  )
})

test('default live path imports only the Production adapter and writes no repository receipt', async () => {
  const source = await readFile(SCRIPT_PATH, 'utf8')
  assert.match(source, /createPersistentNativeAppServer/)
  assert.match(source, /executeProductionBrainstorm/)
  assert.match(source, /isProductionBrainstormResult/)
  assert.match(source, /live-bundled-app-server/)
  assert.match(source, /mkdtemp\(join\('\/private\/tmp'/)
  assert.doesNotMatch(source, /createPersistentNativeAppServerForTest|fake_persistent_app_server/)
  assert.doesNotMatch(source, /tests\/fixtures\/.*receipt/)
})

test('live-shaped receipt requires empty outbound tools and exact action-derived turn coverage', async () => {
  const value = await fixture()
  const receipt = deterministicLiveReceipt(value)
  assert.equal(validateLiveCanaryReceipt(receipt, value), receipt)

  const forgedCapture = structuredClone(receipt)
  forgedCapture.raw_evidence.admission.tool_inventory_capture.capture_ref = digest('forged')
  forgedCapture.receipt_digest = liveCanaryReceiptDigest(forgedCapture)
  assert.throws(
    () => validateLiveCanaryReceipt(forgedCapture, value),
    /raw outbound model tool capture is unsafe/,
  )

  const forgedCount = structuredClone(receipt)
  forgedCount.telemetry.model_turns = 6
  forgedCount.receipt_digest = liveCanaryReceiptDigest(forgedCount)
  assert.throws(
    () => validateLiveCanaryReceipt(forgedCount, value),
    /model turn telemetry is not derived/,
  )

  const forgedControllerCounter = structuredClone(receipt)
  forgedControllerCounter.raw_evidence.production_chain.projection
    .controller_counters.model_calls += 1
  forgedControllerCounter.receipt_digest = liveCanaryReceiptDigest(forgedControllerCounter)
  assert.throws(
    () => validateLiveCanaryReceipt(forgedControllerCounter, value),
    /controller model-call counter is not action-receipt-derived/,
  )

  const forgedQuality = structuredClone(receipt)
  forgedQuality.raw_evidence.production_chain.projection
    .broker_output.receipt.quality.theatre = true
  forgedQuality.receipt_digest = liveCanaryReceiptDigest(forgedQuality)
  assert.throws(
    () => validateLiveCanaryReceipt(forgedQuality, value),
    /synthetic positive Production output quality was not proven/,
  )
})
