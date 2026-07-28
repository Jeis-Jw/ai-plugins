#!/usr/bin/env node
import { createHash, randomUUID } from 'node:crypto'
import {
  lstat, mkdir, mkdtemp, readFile, readdir, realpath, rm, writeFile,
} from 'node:fs/promises'
import {
  dirname, isAbsolute, join, resolve,
} from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  APP_SERVER_CONTRACT_STABILITY,
  APP_SERVER_PROTOCOL,
  BUNDLED_CODEX_BINARY,
  PINNED_BINARY_DIGEST,
  PINNED_CODEX_VERSION,
  PINNED_CONFIG_DIGEST,
  PINNED_SCHEMA_DIGEST,
  createPersistentNativeAppServer,
  isAdapterOwnedNativeObservation,
  isAdapterOwnedNativeReceipt,
} from './persistent_native_app_server.mjs'
import {
  executeProductionBrainstorm,
  isProductionBrainstormResult,
} from './persistent_brainstorm_controller.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const DEFAULT_FIXTURE = join(
  HERE,
  '..',
  'tests',
  'fixtures',
  'persistent_native_live_canary.json',
)
const LIVE_RECEIPT_SCHEMA = 'studio-native-live-canary-receipt/v1'
const FIXTURE_SCHEMA = 'studio-native-live-canary-fixture/v1'
const REQUIRED_CHECKS = Object.freeze([
  'exact_pinned_contract',
  'isolated_inventory',
  'distinct_role_threads',
  'same_thread_context_followup',
  'exact_structured_output',
  'same_thread_single_repair',
  'bounded_barrier',
  'readonly_write_denial',
  'auth_snapshot_absent',
  'matching_interrupt',
  'cleanup_delete',
  'late_result_fence',
  'first_dispatch_fallback_fence',
  'production_output_quality',
  'telemetry_truthful',
  'producer_state_opaque',
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
  return `sha256:${createHash('sha256').update(
    Buffer.isBuffer(value) ? value : Buffer.from(canonicalJson(value), 'utf8'),
  ).digest('hex')}`
}

function scalarDigest(value) {
  return `sha256:${createHash('sha256').update(String(value), 'utf8').digest('hex')}`
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

function assertCondition(condition, message) {
  if (!condition) throw new Error(message)
}

export function validateCanaryFixture(fixture) {
  assertCondition(exactKeys(
    fixture,
    [
      'schema',
      'evidence_class',
      'production_workload',
      'contract',
      'synthetic',
      'limits',
      'required_checks',
    ],
  ), 'live canary fixture fields differ from the exact contract')
  assertCondition(fixture.schema === FIXTURE_SCHEMA, 'live canary fixture schema drift')
  assertCondition(
    fixture.evidence_class === 'synthetic-non-sensitive-input-only',
    'fixture must never claim live evidence',
  )
  const expectedContract = {
    protocol: APP_SERVER_PROTOCOL,
    contract_stability: APP_SERVER_CONTRACT_STABILITY,
    experimental_api: true,
    version: PINNED_CODEX_VERSION,
    binary_digest: PINNED_BINARY_DIGEST,
    schema_digest: PINNED_SCHEMA_DIGEST,
    config_digest: PINNED_CONFIG_DIGEST,
  }
  assertCondition(
    canonicalJson(fixture.contract) === canonicalJson(expectedContract),
    'fixture contract differs from the exact bundled app-server pins',
  )
  assertCondition(
    canonicalJson(fixture.required_checks) === canonicalJson(REQUIRED_CHECKS),
    'fixture required_checks order or membership drifted',
  )
  const workload = fixture.production_workload
  assertCondition(
    exactKeys(workload, [
      'schema',
      'workflow_name',
      'agenda',
      'production_profile',
      'max_rounds',
      'dry_stop',
      'critic_rubric',
      'max_concurrency',
      'cwd_contract',
      'personas',
    ])
      && workload.schema === 'studio-production-live-workload/v1'
      && workload.production_profile === 'standard'
      && workload.max_rounds === 1
      && workload.dry_stop === 1
      && workload.max_concurrency === 2
      && workload.cwd_contract === 'dedicated-synthetic-empty-temp-directory'
      && typeof workload.workflow_name === 'string'
      && workload.workflow_name.length > 0
      && typeof workload.agenda === 'string'
      && workload.agenda.length > 0
      && typeof workload.critic_rubric === 'string'
      && workload.critic_rubric.length > 0
      && Array.isArray(workload.personas)
      && workload.personas.length === 2
      && workload.personas.every(persona => (
        exactKeys(persona, ['crew', 'name', 'role', 'body'])
        && persona.crew === persona.name
        && ['crew', 'name', 'role', 'body'].every(key => (
          typeof persona[key] === 'string' && persona[key].length > 0
        ))
      )),
    'fixture Production A/B workload is invalid',
  )
  assertCondition(exactKeys(fixture.synthetic, [
    'context_nonce',
    'role_a_answer',
    'role_b_answer',
    'malformed_candidate',
    'repaired_answer',
    'write_probe_name',
    'expected_production_output',
  ]), 'fixture synthetic fields differ from the exact contract')
  assertCondition(
    Number.isInteger(fixture.limits?.barrier_width)
      && fixture.limits.barrier_width === 2
      && fixture.limits.repair_attempts === 1
      && fixture.limits.max_model_turns === 32,
    'fixture bounds are invalid',
  )
  for (const key of [
    'context_nonce',
    'role_a_answer',
    'role_b_answer',
    'malformed_candidate',
    'repaired_answer',
    'write_probe_name',
  ]) {
    assertCondition(
      typeof fixture.synthetic?.[key] === 'string'
        && fixture.synthetic[key].length > 0
        && fixture.synthetic[key].length <= 128,
      `fixture synthetic.${key} is invalid`,
    )
  }
  assertCondition(
    canonicalJson(fixture.synthetic.expected_production_output) === canonicalJson({
      status: 'completed',
      verdict_alive: true,
      theatre: false,
      min_valid_deltas: 1,
    }),
    'fixture synthetic Production output expectation is invalid',
  )
  return fixture
}

export function controllerRequestFromProductionWorkload(workload, runId) {
  assertCondition(
    typeof runId === 'string' && runId.length > 0,
    'Production controller run id is required',
  )
  return {
    run_id: runId,
    workflow_name: workload.workflow_name,
    agenda: workload.agenda,
    productionProfile: workload.production_profile,
    maxRounds: workload.max_rounds,
    dryStop: workload.dry_stop,
    criticRubric: workload.critic_rubric,
    personas: workload.personas.map(persona => ({
      crew: persona.crew,
      name: persona.name,
      role: persona.role,
      body: persona.body,
    })),
  }
}

export function liveCanaryReceiptDigest(receipt) {
  const value = structuredClone(receipt)
  delete value.receipt_digest
  return digest(value)
}

export function validateLiveCanaryReceipt(receipt, fixture) {
  validateCanaryFixture(fixture)
  assertCondition(exactKeys(receipt, [
    'schema',
    'evidence_class',
    'attestation_scope',
    'run_id',
    'fixture_digest',
    'synthetic_input',
    'execution_scope',
    'started_at',
    'finished_at',
    'contract',
    'limits',
    'checks',
    'raw_evidence',
    'telemetry',
    'passed',
    'receipt_digest',
  ]), 'live receipt root fields differ from the exact contract')
  assertCondition(receipt.schema === LIVE_RECEIPT_SCHEMA, 'live receipt schema drift')
  assertCondition(
    receipt.evidence_class === 'live-bundled-app-server',
    'deterministic or synthetic fixture evidence cannot be promoted to live',
  )
  assertCondition(
    receipt.attestation_scope
      === 'trusted-local-observation-bound-to-adapter-receipts',
    'live receipt must not claim host or remote attestation',
  )
  assertCondition(receipt.synthetic_input === true, 'canary input must be synthetic')
  assertCondition(receipt.passed === true, 'live canary contains a failed check')
  assertCondition(
    receipt.receipt_digest === liveCanaryReceiptDigest(receipt),
    'live receipt digest mismatch',
  )
  assertCondition(
    receipt.fixture_digest === digest(fixture),
    'live receipt is not bound to the canary fixture',
  )
  assertCondition(
    canonicalJson(receipt.limits) === canonicalJson(fixture.limits),
    'live receipt limits differ from the fixture',
  )
  assertCondition(
    canonicalJson(receipt.contract) === canonicalJson({
      ...fixture.contract,
      executable: BUNDLED_CODEX_BINARY,
      admission_evidence_digest: receipt.contract.admission_evidence_digest,
      environment_digest: receipt.contract.environment_digest,
      tool_inventory_capture_ref: receipt.contract.tool_inventory_capture_ref,
      tool_inventory_evidence_digest: receipt.contract.tool_inventory_evidence_digest,
      tool_inventory_provider_delta_digest:
        receipt.contract.tool_inventory_provider_delta_digest,
    }),
    'live receipt contract differs from the exact pinned executable',
  )
  assertCondition(
    [
      'admission_evidence_digest',
      'environment_digest',
      'tool_inventory_capture_ref',
      'tool_inventory_evidence_digest',
      'tool_inventory_provider_delta_digest',
    ].every(key => /^sha256:[0-9a-f]{64}$/.test(receipt.contract[key] || '')),
    'live receipt contract evidence digest is invalid',
  )
  assertCondition(
    exactKeys(receipt.execution_scope, [
      'evidence_class',
      'workspace_kind',
      'agent_cwd',
      'agent_cwd_ref',
      'repository_cwd_used_by_agent',
      'workspace_entries',
      'instruction_source_files',
      'sensitive_input_supplied',
      'model_tool_surface',
      'repository_mutation_allowed',
      'agent_tool_network_access',
      'sandbox_network_access',
      'provider_model_transport',
      'auth_snapshot_hygiene_only',
      'credential_confidentiality_guaranteed',
      'same_user_filesystem_read_confidentiality',
    ])
      && receipt.execution_scope.evidence_class === 'trusted-local-observation'
      && receipt.execution_scope.workspace_kind === 'dedicated-synthetic-temp'
      && receipt.execution_scope.repository_cwd_used_by_agent === false
      && Array.isArray(receipt.execution_scope.workspace_entries)
      && receipt.execution_scope.workspace_entries.length === 0
      && Array.isArray(receipt.execution_scope.instruction_source_files)
      && receipt.execution_scope.instruction_source_files.length === 0
      && receipt.execution_scope.sensitive_input_supplied === false
      && receipt.execution_scope.model_tool_surface === 'context-only-empty'
      && receipt.execution_scope.repository_mutation_allowed === false
      && receipt.execution_scope.agent_tool_network_access === false
      && receipt.execution_scope.sandbox_network_access === false
      && receipt.execution_scope.provider_model_transport
        === 'required-outside-agent-tool-sandbox'
      && receipt.execution_scope.auth_snapshot_hygiene_only === true
      && receipt.execution_scope.credential_confidentiality_guaranteed === false
      && receipt.execution_scope.same_user_filesystem_read_confidentiality === 'out-of-scope'
      && receipt.execution_scope.agent_cwd.startsWith('/private/tmp/studio-native-live-canary-')
      && receipt.execution_scope.agent_cwd_ref === digest(receipt.execution_scope.agent_cwd),
    'canary execution was not confined to a dedicated synthetic workspace',
  )
  const checkNames = receipt.checks?.map(check => check.name)
  assertCondition(
    canonicalJson(checkNames) === canonicalJson(REQUIRED_CHECKS)
      && receipt.checks.every(check => (
        exactKeys(check, ['name', 'passed', 'raw_evidence'])
        &&
        check.passed === true
        && check.raw_evidence
        && typeof check.raw_evidence === 'object'
      )),
    'live receipt checks are incomplete, reordered, or failed',
  )
  const raw = receipt.raw_evidence
  assertCondition(exactKeys(raw, [
    'admission',
    'execution_scope',
    'roles',
    'barrier',
    'context',
    'repair',
    'auth',
    'interrupt',
    'cleanup',
    'late_result',
    'write_denial',
    'production_chain',
    'action_receipts',
  ]), 'raw live evidence fields differ from the exact contract')
  assertCondition(
    canonicalJson(raw.execution_scope) === canonicalJson(receipt.execution_scope),
    'root and raw execution scope differ',
  )
  const roleThreads = raw.roles.map(role => role.host_thread_id)
  assertCondition(
    roleThreads.length === 3
      && raw.roles.every(role => exactKeys(role, ['actor_id', 'host_thread_id']))
      && new Set(roleThreads).size === roleThreads.length,
    'live roles do not have distinct physical threads',
  )
  assertCondition(
    raw.context.first.host_thread_id === raw.context.followup.host_thread_id
      && raw.context.first.host_turn_id !== raw.context.followup.host_turn_id
      && raw.context.followup.output.remembered_nonce === fixture.synthetic.context_nonce,
    'same-thread context follow-up was not proven',
  )
  assertCondition(
    raw.repair.same_thread === true
      && raw.repair.repair_attempts === 1
      && raw.repair.initial_semantic_valid === false
      && raw.repair.repaired.output.answer === fixture.synthetic.repaired_answer,
    'same-thread bounded repair was not proven',
  )
  assertCondition(
    raw.barrier.width === fixture.limits.barrier_width
      && raw.barrier.results.length === fixture.limits.barrier_width
      && raw.barrier.results.every((result, index) => result.ordinal === index + 1),
    'bounded ordered barrier was not proven',
  )
  const writeObservation = raw.write_denial.observation
  const writeObservationWithoutDigest = structuredClone(writeObservation)
  delete writeObservationWithoutDigest.evidence_digest
  assertCondition(
    exactKeys(raw.write_denial, ['target', 'observation'])
      && writeObservation.schema === 'studio-native-readonly-write-probe/v1'
      && writeObservation.evidence_class === 'trusted-local-observation'
      && writeObservation.target_absent === true
      && writeObservation.exit_code !== 0
      && ['eperm', 'permission_denied', 'readonly_filesystem', 'policy_denied']
        .includes(writeObservation.denial_kind)
      && writeObservation.target_ref === scalarDigest(raw.write_denial.target)
      && raw.write_denial.target.startsWith(receipt.execution_scope.agent_cwd)
      && canonicalJson(writeObservation.command_argv)
        === canonicalJson(['/usr/bin/touch', '--', raw.write_denial.target])
      && writeObservation.permission_profile === ':read-only'
      && writeObservation.sandbox_mode === 'readOnly'
      && writeObservation.sandbox_network_access === false
      && writeObservation.evidence_digest === digest(writeObservationWithoutDigest),
    'actual read-only write denial was not proven',
  )
  assertCondition(
    raw.auth.auth_snapshot_removed === true
      && raw.auth.auth_snapshot_hygiene_only === true
      && raw.auth.content_read === false
      && raw.auth.credential_confidentiality_guaranteed === false
      && raw.auth.same_user_filesystem_read_confidentiality === 'out-of-scope'
      && raw.auth.filesystem_observations.length === 8
      && raw.auth.filesystem_observations.every(observation => {
        if (
          !exactKeys(observation, [
            'schema',
            'evidence_class',
            'checkpoint',
            'absent',
            'observed_at',
            'auth_path_ref',
            'config_digest',
            'environment_digest',
            'evidence_digest',
          ])
          || observation.schema !== 'studio-native-auth-absence-observation/v1'
          || observation.evidence_class !== 'trusted-local-observation'
          || observation.absent !== true
        ) return false
        const value = structuredClone(observation)
        delete value.evidence_digest
        return observation.evidence_digest === digest(value)
      })
      && new Set(
        raw.auth.filesystem_observations.map(observation => observation.checkpoint),
      ).size === 8,
    'auth snapshot operational hygiene was not proven',
  )
  assertCondition(
    raw.interrupt.receipt.terminal_status === 'interrupted'
      && raw.interrupt.receipt.host_thread_id === raw.interrupt.binding.host_thread_id
      && raw.interrupt.receipt.host_turn_id === raw.interrupt.binding.host_turn_id
      && raw.interrupt.lifecycle.late_result_tombstone === true,
    'matching interrupted terminal was not proven',
  )
  assertCondition(
    raw.cleanup.length === 3
      && raw.cleanup.every(item => {
        if (
          !exactKeys(item, [
            'schema',
            'actor_ref',
            'host_thread_id',
            'background_terminals',
            'deleted',
            'deletion_notified',
            'rollout_absent',
            'rollout_path_ref',
            'config_digest',
            'environment_digest',
            'receipt_digest',
          ])
          || item.schema !== 'studio-native-cleanup-receipt/v1'
          || item.deleted !== true
          || item.deletion_notified !== true
          || item.rollout_absent !== true
          || item.background_terminals !== 0
          || !/^sha256:[0-9a-f]{64}$/.test(item.rollout_path_ref || '')
        ) return false
        const value = structuredClone(item)
        delete value.receipt_digest
        return item.receipt_digest === digest(value)
      }),
    'role cleanup/delete was not proven',
  )
  assertCondition(
    raw.late_result.rejected === true
      && raw.late_result.code === 'late_result'
      && raw.late_result.tombstoned === true
      && raw.late_result.host_thread_id === raw.interrupt.binding.host_thread_id
      && raw.late_result.host_turn_id === raw.interrupt.binding.host_turn_id,
    'late-result fence was not proven',
  )
  const workflow = raw.production_chain.workflow_receipt
  const workflowWithoutDigest = structuredClone(workflow)
  delete workflowWithoutDigest.receipt_digest
  const productionProjection = raw.production_chain.projection
  const controllerCounters = productionProjection.controller_counters
  const brokerOutput = productionProjection.broker_output
  const expectedProduction = fixture.synthetic.expected_production_output
  assertCondition(
    exactKeys(raw.production_chain, [
      'branded',
      'ok',
      'status',
      'execution_path',
      'fallback_allowed',
      'projection',
      'workflow_receipt',
    ])
      && exactKeys(productionProjection, [
        'state_ref',
        'envelope_schema',
        'status',
        'native_started',
        'fallback_allowed',
        'workload_binding',
        'controller_counters',
        'broker_output',
        'raw_state_exposed',
      ])
      && exactKeys(controllerCounters, [
        'model_calls',
        'terminal_action_count',
        'fresh_role_threads',
        'same_thread_followups',
        'rounds',
        'participants',
      ])
      && exactKeys(brokerOutput, [
        'delta_log_count',
        'verdict',
        'receipt',
      ])
      && exactKeys(brokerOutput.verdict, ['alive'])
      && exactKeys(brokerOutput.receipt, ['counters', 'quality'])
      && exactKeys(brokerOutput.receipt.counters, ['valid_deltas', 'dry_deltas'])
      && exactKeys(brokerOutput.receipt.quality, ['alive', 'theatre'])
      && raw.production_chain.branded === true
      && raw.production_chain.ok === true
      && raw.production_chain.status === 'completed'
      && raw.production_chain.execution_path === 'persistent-native-app-server'
      && raw.production_chain.fallback_allowed === false
      && productionProjection.status === 'completed'
      && productionProjection.native_started === true
      && productionProjection.fallback_allowed === false
      && workflow.schema === 'studio-persistent-production-workflow-receipt/v1'
      && workflow.evidence_class === 'adapter-owned-production-chain'
      && exactKeys(workflow.admission, [
        'evidence_class',
        'admission_evidence_digest',
        'tool_inventory_evidence_digest',
        'tool_inventory_capture_ref',
        'actual_model',
        'actual_reasoning_effort',
      ])
      && workflow.admission.evidence_class === 'adapter-owned-production-admission'
      && /^sha256:[0-9a-f]{64}$/.test(
        workflow.admission.admission_evidence_digest || '',
      )
      && /^sha256:[0-9a-f]{64}$/.test(
        workflow.admission.tool_inventory_evidence_digest || '',
      )
      && /^sha256:[0-9a-f]{64}$/.test(
        workflow.admission.tool_inventory_capture_ref || '',
      )
      && typeof workflow.admission.actual_model === 'string'
      && workflow.admission.actual_model.length > 0
      && (
        workflow.admission.actual_reasoning_effort === null
        || typeof workflow.admission.actual_reasoning_effort === 'string'
      )
      && exactKeys(workflow.execution_input, [
        'request_digest',
        'concurrency',
        'cwd_ref',
      ])
      && /^sha256:[0-9a-f]{64}$/.test(workflow.execution_input.request_digest || '')
      && Number.isInteger(workflow.execution_input.concurrency)
      && /^sha256:[0-9a-f]{64}$/.test(workflow.execution_input.cwd_ref || '')
      && workflow.journal.status === 'tombstoned'
      && workflow.journal.dispatch_started === true
      && workflow.journal.native_response_received === true
      && workflow.journal.tombstone.cleanup === 'complete'
      && workflow.action_receipts.length >= 1
      && workflow.action_receipts.every(item => (
        item.stage === 'terminal_event'
        && Number.isInteger(item.applied_state_revision)
        && /^sha256:[0-9a-f]{64}$/.test(item.receipt_digest || '')
      ))
      && workflow.cleanup_receipts.length === 4
      && workflow.cleanup_receipts.every(item => (
        item.deleted === true
        && item.deletion_notified === true
        && item.rollout_absent === true
        && /^sha256:[0-9a-f]{64}$/.test(item.receipt_digest || '')
      ))
      && workflow.receipt_digest === digest(workflowWithoutDigest),
    'first-dispatch fallback fence was not proven',
  )
  const workloadBinding = productionProjection.workload_binding
  const expectedControllerRequest = controllerRequestFromProductionWorkload(
    fixture.production_workload,
    workflow.run_id,
  )
  assertCondition(
    exactKeys(workloadBinding, [
      'workload_digest',
      'controller_request_digest',
      'controller_run_id',
      'concurrency',
      'cwd_ref',
      'actual_model',
      'actual_reasoning_effort',
      'model_evidence',
    ])
      && workloadBinding.workload_digest === digest(fixture.production_workload)
      && workloadBinding.controller_request_digest === digest(expectedControllerRequest)
      && workloadBinding.controller_request_digest
        === workflow.execution_input.request_digest
      && workloadBinding.controller_run_id === workflow.run_id
      && workloadBinding.concurrency === fixture.production_workload.max_concurrency
      && workloadBinding.concurrency === workflow.execution_input.concurrency
      && workloadBinding.cwd_ref === receipt.execution_scope.agent_cwd_ref
      && workloadBinding.cwd_ref === workflow.execution_input.cwd_ref
      && workloadBinding.actual_model === workflow.admission.actual_model
      && workloadBinding.actual_reasoning_effort
        === workflow.admission.actual_reasoning_effort
      && workloadBinding.model_evidence === 'controller-workflow-admission-receipt',
    'fixture Production workload is not exactly bound to the controller execution',
  )
  const spawnActions = workflow.action_receipts.filter(item => item.kind === 'spawn')
  const followupActions = workflow.action_receipts.filter(item => item.kind === 'followup')
  const spawnThreadByActor = new Map(
    spawnActions.map(item => [item.actor_id, item.host_thread_id]),
  )
  assertCondition(
    controllerCounters.model_calls === workflow.action_receipts.length
      && controllerCounters.terminal_action_count === workflow.action_receipts.length
      && controllerCounters.fresh_role_threads === 4
      && controllerCounters.same_thread_followups === 3
      && workflow.action_receipts.length === 7
      && spawnActions.length === 4
      && followupActions.length === 3
      && new Set(spawnActions.map(item => item.actor_id)).size === 4
      && new Set(spawnActions.map(item => item.host_thread_id)).size === 4
      && followupActions.every(item => (
        spawnThreadByActor.get(item.actor_id) === item.host_thread_id
      ))
      && new Set(workflow.action_receipts.map(item => item.host_turn_id)).size === 7
      && workflow.action_receipts.every(item => item.stage === 'terminal_event'),
    'controller model-call counter is not action-receipt-derived',
  )
  assertCondition(
    raw.production_chain.status === expectedProduction.status
      && productionProjection.status === expectedProduction.status
      && brokerOutput.verdict.alive === expectedProduction.verdict_alive
      && brokerOutput.receipt.quality.alive === expectedProduction.verdict_alive
      && brokerOutput.receipt.quality.theatre === expectedProduction.theatre
      && Number.isInteger(brokerOutput.receipt.counters.valid_deltas)
      && brokerOutput.receipt.counters.valid_deltas >= expectedProduction.min_valid_deltas
      && Number.isInteger(brokerOutput.receipt.counters.dry_deltas)
      && brokerOutput.receipt.counters.dry_deltas >= 0
      && Number.isInteger(brokerOutput.delta_log_count)
      && brokerOutput.delta_log_count
        === brokerOutput.receipt.counters.valid_deltas
          + brokerOutput.receipt.counters.dry_deltas,
    'synthetic positive Production output quality was not proven',
  )
  assertCondition(
    workflow.raw_state_exposed === false
      && productionProjection.raw_state_exposed === false,
    'Producer projection exposed canonical state',
  )
  assertCondition(
    receipt.telemetry.tokens === null
      && receipt.telemetry.token_coverage === 'unavailable'
      && receipt.telemetry.wall_time_coverage === 'exact'
      && Number.isInteger(receipt.telemetry.elapsed_ms)
      && receipt.telemetry.elapsed_ms >= 0,
    'telemetry coverage is not truthful',
  )
  const inventory = raw.admission.inventory
  const capture = raw.admission.tool_inventory_capture
  const captureWithoutDigest = structuredClone(capture)
  delete captureWithoutDigest.evidence_digest
  assertCondition(
    inventory.hooks === 0
      && inventory.hook_errors === 0
      && inventory.hook_warnings === 0
      && inventory.skills === 0
      && inventory.skill_errors === 0
      && inventory.plugins === 0
      && inventory.plugin_load_errors === 0
      && inventory.apps === 0
      && inventory.mcp_servers === 0
      && Array.isArray(inventory.enabled_local_execution_features)
      && inventory.enabled_local_execution_features.length === 0
      && capture.captured === true
      && capture.evidence_class === 'live-loopback-raw-request'
      && capture.provider_scope === 'loopback-only'
      && typeof capture.model === 'string'
      && capture.model.length > 0
      && (capture.reasoning_effort === null || typeof capture.reasoning_effort === 'string')
      && capture.capture_ref === capture.raw_tools_digest
      && capture.capture_ref === receipt.contract.tool_inventory_capture_ref
      && capture.evidence_digest === receipt.contract.tool_inventory_evidence_digest
      && capture.provider_delta_digest
        === receipt.contract.tool_inventory_provider_delta_digest
      && capture.evidence_digest === digest(captureWithoutDigest)
      && capture.tool_count === 0
      && Array.isArray(capture.tools)
      && capture.tools.length === 0
      && capture.raw_tools_digest === digest([]),
    'admitted inventory or raw outbound model tool capture is unsafe',
  )
  assertCondition(
    raw.action_receipts.length <= fixture.limits.max_model_turns
      && raw.action_receipts.length >= 1
      && exactKeys(receipt.telemetry, [
        'model_turns',
        'model_turn_coverage',
        'tokens',
        'token_coverage',
        'elapsed_ms',
        'wall_time_coverage',
      ])
      && receipt.telemetry.model_turns === raw.action_receipts.length
      && receipt.telemetry.model_turn_coverage === 'exact'
      && new Set(raw.action_receipts.map(item => item.host_turn_id)).size
        === raw.action_receipts.length
      && raw.action_receipts.every((item, index) => (
        exactKeys(item, [
          'ordinal',
          'source',
          'action_id',
          'action_ref',
          'host_thread_id',
          'host_turn_id',
          'receipt_schema',
          'receipt_digest',
        ])
        && item.ordinal === index + 1
        && ['manual-probe', 'production-controller'].includes(item.source)
        && (item.action_id === null || typeof item.action_id === 'string')
        && typeof item.host_thread_id === 'string'
        && typeof item.host_turn_id === 'string'
        && /^sha256:[0-9a-f]{64}$/.test(item.receipt_digest || '')
        && /^sha256:[0-9a-f]{64}$/.test(item.action_ref || '')
      )),
    'model turn telemetry is not derived from exact action receipts',
  )
  return receipt
}

const STRING_SCHEMA = property => ({
  type: 'object',
  additionalProperties: false,
  required: [property],
  properties: { [property]: { type: 'string', minLength: 1 } },
})

function receiptEvidence(receipt) {
  return {
    schema: receipt.schema,
    action_ref: receipt.action_ref,
    actor_ref: receipt.actor_ref,
    host_thread_id: receipt.host_thread_id,
    host_turn_id: receipt.host_turn_id,
    terminal_status: receipt.terminal_status,
    error_code: receipt.error_code || null,
    output: Object.hasOwn(receipt, 'output') ? structuredClone(receipt.output) : null,
    tool_evidence: receipt.tool_evidence
      ? structuredClone(receipt.tool_evidence)
      : null,
    binary_digest: receipt.binary_digest || null,
    schema_digest: receipt.schema_digest || null,
    config_digest: receipt.config_digest || null,
    environment_digest: receipt.environment_digest || null,
    receipt_digest: receipt.receipt_digest,
  }
}

function namedCheck(name, passed, rawEvidence) {
  return { name, passed: Boolean(passed), raw_evidence: rawEvidence }
}

async function loadFixture(path) {
  const info = await lstat(path).catch(() => null)
  assertCondition(info?.isFile() && !info.isSymbolicLink() && info.size < 64 * 1024, 'fixture must be a bounded regular file')
  return validateCanaryFixture(JSON.parse(await readFile(path, 'utf8')))
}

export async function runLiveCanary({
  fixturePath = DEFAULT_FIXTURE,
} = {}) {
  const fixture = await loadFixture(fixturePath)
  const runtimeRoot = await mkdtemp(join('/private/tmp', 'studio-native-live-canary-'))
  const startedAt = new Date().toISOString()
  const startedMs = Date.now()
  const mainRuntime = join(runtimeRoot, 'main-runtime')
  const syntheticWorkspace = join(runtimeRoot, 'synthetic-workspace')
  await mkdir(mainRuntime, { mode: 0o700 })
  await mkdir(syntheticWorkspace, { mode: 0o700 })
  const canonicalCwd = await realpath(syntheticWorkspace)
  const workspaceEntries = (await readdir(canonicalCwd)).sort(unicodeCompare)
  assertCondition(
    workspaceEntries.length === 0,
    'synthetic canary workspace must be empty',
  )
  const adapter = createPersistentNativeAppServer({ runtimeRoot: mainRuntime, cwd: canonicalCwd })
  const cleanup = []
  const authObservations = []
  const actionReceipts = []
  try {
    const capability = await adapter.admit()
    const admission = adapter.inspectAdmissionEvidence(capability)
    const security = adapter.inspectSecurityEvidence(capability)
    authObservations.push(await adapter.observeAuthSnapshotAbsence(capability, {
      checkpoint: 'main:before-role-start',
    }))

    const roleA = await adapter.startRole(capability, { actorId: 'canary:context-a' })
    const roleB = await adapter.startRole(capability, { actorId: 'canary:barrier-b' })
    const roleInterrupt = await adapter.startRole(capability, { actorId: 'canary:interrupt' })

    const barrierStarted = Date.now()
    const [turnA, turnB] = await Promise.all([
      adapter.beginTurn(capability, {
        role: roleA,
        actionId: 'live-canary-barrier-a',
        prompt: `Return exactly {"nonce":"${fixture.synthetic.context_nonce}"}. This is synthetic and non-sensitive.`,
        outputSchema: STRING_SCHEMA('nonce'),
      }),
      adapter.beginTurn(capability, {
        role: roleB,
        actionId: 'live-canary-barrier-b',
        prompt: `Return exactly {"answer":"${fixture.synthetic.role_b_answer}"}. This is synthetic and non-sensitive.`,
        outputSchema: STRING_SCHEMA('answer'),
      }),
    ])
    const bindingA = adapter.inspectTurnBinding(capability, turnA)
    const bindingB = adapter.inspectTurnBinding(capability, turnB)
    const [firstA, firstB] = await Promise.all([
      adapter.waitTurn(capability, turnA),
      adapter.waitTurn(capability, turnB),
    ])
    actionReceipts.push(firstA, firstB)
    authObservations.push(await adapter.observeAuthSnapshotAbsence(capability, {
      checkpoint: 'main:after-barrier-a',
    }))
    authObservations.push(await adapter.observeAuthSnapshotAbsence(capability, {
      checkpoint: 'main:after-barrier-b',
    }))
    const barrierElapsedMs = Date.now() - barrierStarted

    await adapter.resumeRole(capability, roleA)
    const contextFollowup = await adapter.runTurn(capability, {
      role: roleA,
      actionId: 'live-canary-context-followup',
      prompt: 'Return the synthetic nonce from your immediately preceding turn as {"remembered_nonce":"..."}.',
      outputSchema: STRING_SCHEMA('remembered_nonce'),
    })
    actionReceipts.push(contextFollowup)
    authObservations.push(await adapter.observeAuthSnapshotAbsence(capability, {
      checkpoint: 'main:after-context-followup',
    }))

    await adapter.resumeRole(capability, roleA)
    const malformed = await adapter.runTurn(capability, {
      role: roleA,
      actionId: 'live-canary-malformed-candidate',
      prompt: `Return exactly {"candidate":"${fixture.synthetic.malformed_candidate}"}.`,
      outputSchema: STRING_SCHEMA('candidate'),
    })
    actionReceipts.push(malformed)
    authObservations.push(await adapter.observeAuthSnapshotAbsence(capability, {
      checkpoint: 'main:after-malformed',
    }))
    const initialSemanticValid = (
      malformed.output?.answer === fixture.synthetic.repaired_answer
      && malformed.output?.context_nonce === fixture.synthetic.context_nonce
    )
    assertCondition(initialSemanticValid === false, 'malformed canary candidate unexpectedly passed semantic validation')
    await adapter.resumeRole(capability, roleA)
    const repaired = await adapter.runTurn(capability, {
      role: roleA,
      actionId: 'live-canary-repair',
      prompt: [
        'Your previous structured candidate failed the application semantic contract.',
        `Return exactly {"answer":"${fixture.synthetic.repaired_answer}","context_nonce":"${fixture.synthetic.context_nonce}"}.`,
      ].join('\n'),
      outputSchema: {
        type: 'object',
        additionalProperties: false,
        required: ['answer', 'context_nonce'],
        properties: {
          answer: { type: 'string', minLength: 1 },
          context_nonce: { type: 'string', minLength: 1 },
        },
      },
    })
    actionReceipts.push(repaired)
    authObservations.push(await adapter.observeAuthSnapshotAbsence(capability, {
      checkpoint: 'main:after-repair',
    }))

    const interruptTurn = await adapter.beginTurn(capability, {
      role: roleInterrupt,
      actionId: 'live-canary-interrupt',
      prompt: 'Begin a long analysis of 10,000 synthetic integers, then return {"status":"finished"}.',
      outputSchema: STRING_SCHEMA('status'),
    })
    const interruptBinding = adapter.inspectTurnBinding(capability, interruptTurn)
    const interruptReceipt = await adapter.interruptTurn(capability, interruptTurn)
    actionReceipts.push(interruptReceipt)
    authObservations.push(await adapter.observeAuthSnapshotAbsence(capability, {
      checkpoint: 'main:after-interrupt',
    }))
    let lateResultRejected = false
    let lateResultCode = null
    try {
      await adapter.waitTurn(capability, interruptTurn)
    } catch (error) {
      lateResultCode = error.code || 'unknown'
      lateResultRejected = lateResultCode === 'late_result'
    }
    const interruptLifecycle = adapter.inspectTurnLifecycle(capability, interruptTurn)

    const writeTarget = join(canonicalCwd, fixture.synthetic.write_probe_name)
    const writeDenial = await adapter.probeReadOnlyWriteDenial(capability, {
      target: writeTarget,
    })
    authObservations.push(await adapter.observeAuthSnapshotAbsence(capability, {
      checkpoint: 'main:before-cleanup',
    }))
    for (const role of [roleA, roleB, roleInterrupt]) {
      cleanup.push(await adapter.cleanupRole(capability, role))
    }

    const controllerRuntime = join(runtimeRoot, 'controller-runtime')
    const controllerState = join(runtimeRoot, 'controller-state')
    await mkdir(controllerRuntime, { mode: 0o700 })
    const productionRequest = controllerRequestFromProductionWorkload(
      fixture.production_workload,
      `LIVE-CONTROLLER-${randomUUID()}`,
    )
    const productionResult = await executeProductionBrainstorm(productionRequest, {
      stateRoot: controllerState,
      runtimeRoot: controllerRuntime,
      cwd: canonicalCwd,
      concurrency: fixture.production_workload.max_concurrency,
    })
    assertCondition(
      isProductionBrainstormResult(productionResult)
        && productionResult.ok === true
        && productionResult.execution_path === 'persistent-native-app-server'
        && productionResult.fallback_allowed === false,
      `public Production controller did not complete the native chain: ${JSON.stringify({
        branded: isProductionBrainstormResult(productionResult),
        ok: productionResult.ok,
        status: productionResult.status,
        reason: productionResult.reason || null,
        execution_path: productionResult.execution_path,
        fallback_allowed: productionResult.fallback_allowed,
      })}`,
    )
    const productionOutput = productionResult.envelope?.output
    const outputReceipt = productionOutput?.receipt
    assertCondition(
      productionResult.status === 'completed'
        && productionResult.envelope?.status === 'completed'
        && productionOutput
        && outputReceipt?.schema === 'workflow-receipt/v1'
        && productionOutput.verdict
        && Array.isArray(productionOutput.delta_log),
      'public Production controller did not return a completed broker output',
    )

    assertCondition(
      actionReceipts.length === 6
        && actionReceipts.every(isAdapterOwnedNativeReceipt),
      'every model turn must have an adapter-owned receipt',
    )
    assertCondition(
      authObservations.length === 8
        && authObservations.every(isAdapterOwnedNativeObservation),
      'auth filesystem observations are incomplete or not adapter-owned',
    )
    assertCondition(
      isAdapterOwnedNativeObservation(writeDenial),
      'write denial must be an adapter-owned command/exec observation',
    )
    const manualActionEvidence = actionReceipts.map(item => ({
      source: 'manual-probe',
      action_id: null,
      action_ref: item.action_ref,
      host_thread_id: item.host_thread_id,
      host_turn_id: item.host_turn_id,
      receipt_schema: item.schema,
      receipt_digest: item.receipt_digest,
    }))
    const controllerActionEvidence = productionResult.workflow_receipt.action_receipts
      .filter(item => typeof item.host_turn_id === 'string')
      .map(item => ({
        source: 'production-controller',
        action_id: item.action_id,
        action_ref: item.action_ref,
        host_thread_id: item.host_thread_id,
        host_turn_id: item.host_turn_id,
        receipt_schema: item.receipt_schema,
        receipt_digest: item.receipt_digest,
      }))
    const controllerCounters = {
      model_calls: outputReceipt.counters.model_calls,
      terminal_action_count: productionResult.workflow_receipt.action_receipts.length,
      fresh_role_threads: productionResult.workflow_receipt.action_receipts
        .filter(item => item.kind === 'spawn').length,
      same_thread_followups: productionResult.workflow_receipt.action_receipts
        .filter(item => item.kind === 'followup').length,
      rounds: outputReceipt.counters.rounds,
      participants: outputReceipt.counters.participants,
    }
    const controllerActions = productionResult.workflow_receipt.action_receipts
    const controllerSpawns = controllerActions.filter(item => item.kind === 'spawn')
    const controllerFollowups = controllerActions.filter(item => item.kind === 'followup')
    const spawnedThreadByActor = new Map(
      controllerSpawns.map(item => [item.actor_id, item.host_thread_id]),
    )
    assertCondition(
      controllerActions.length === 7
        && controllerSpawns.length === 4
        && controllerFollowups.length === 3
        && new Set(controllerSpawns.map(item => item.actor_id)).size === 4
        && new Set(controllerSpawns.map(item => item.host_thread_id)).size === 4
        && controllerFollowups.every(item => (
          spawnedThreadByActor.get(item.actor_id) === item.host_thread_id
        ))
        && new Set(controllerActions.map(item => item.host_turn_id)).size === 7,
      'Production controller did not prove four role threads and three same-thread follow-ups',
    )
    const brokerOutputProjection = {
      delta_log_count: productionOutput.delta_log.length,
      verdict: {
        alive: productionOutput.verdict.alive,
      },
      receipt: {
        counters: {
          valid_deltas: outputReceipt.counters.valid_deltas,
          dry_deltas: outputReceipt.counters.dry_deltas,
        },
        quality: {
          alive: outputReceipt.quality.alive,
          theatre: outputReceipt.quality.theatre,
        },
      },
    }
    const expectedProduction = fixture.synthetic.expected_production_output
    assertCondition(
      controllerCounters.model_calls === controllerCounters.terminal_action_count
        && productionResult.workflow_receipt.action_receipts.every(
          item => item.stage === 'terminal_event',
        ),
      'controller action receipts do not cover every broker model call',
    )
    assertCondition(
      productionResult.status === expectedProduction.status
        && brokerOutputProjection.verdict.alive === expectedProduction.verdict_alive
        && brokerOutputProjection.receipt.quality.alive
          === expectedProduction.verdict_alive
        && brokerOutputProjection.receipt.quality.theatre === expectedProduction.theatre
        && brokerOutputProjection.receipt.counters.valid_deltas
          >= expectedProduction.min_valid_deltas
        && brokerOutputProjection.delta_log_count
          === brokerOutputProjection.receipt.counters.valid_deltas
            + brokerOutputProjection.receipt.counters.dry_deltas,
      `synthetic positive Production result failed its explicit output expectation: ${JSON.stringify({
        expected: expectedProduction,
        observed: {
          status: productionResult.status,
          controller_counters: controllerCounters,
          broker_output: brokerOutputProjection,
        },
      })}`,
    )
    const actionReceiptEvidence = [...manualActionEvidence, ...controllerActionEvidence]
      .map((item, ordinal) => ({ ordinal: ordinal + 1, ...item }))
    const modelTurnIds = actionReceiptEvidence.map(item => item.host_turn_id)
    assertCondition(
      modelTurnIds.every(value => typeof value === 'string')
        && new Set(modelTurnIds).size === actionReceiptEvidence.length
        && actionReceiptEvidence.length <= fixture.limits.max_model_turns,
      'model turn receipt coverage is not exact',
    )
    const rawEvidence = {
      admission,
      execution_scope: {
        evidence_class: 'trusted-local-observation',
        workspace_kind: 'dedicated-synthetic-temp',
        agent_cwd: canonicalCwd,
        agent_cwd_ref: digest(canonicalCwd),
        repository_cwd_used_by_agent: false,
        workspace_entries: workspaceEntries,
        instruction_source_files: [],
        sensitive_input_supplied: false,
        model_tool_surface: security.model_tool_surface,
        repository_mutation_allowed: security.repository_mutation_allowed,
        agent_tool_network_access: security.agent_tool_network_access,
        sandbox_network_access: security.sandbox_network_access,
        provider_model_transport: security.provider_model_transport,
        auth_snapshot_hygiene_only: security.auth_snapshot_hygiene_only,
        credential_confidentiality_guaranteed:
          security.credential_confidentiality_guaranteed,
        same_user_filesystem_read_confidentiality:
          security.same_user_filesystem_read_confidentiality,
      },
      roles: [
        { actor_id: 'canary:context-a', host_thread_id: bindingA.host_thread_id },
        { actor_id: 'canary:barrier-b', host_thread_id: bindingB.host_thread_id },
        { actor_id: 'canary:interrupt', host_thread_id: interruptBinding.host_thread_id },
      ],
      barrier: {
        width: 2,
        elapsed_ms: barrierElapsedMs,
        results: [
          { ordinal: 1, ...receiptEvidence(firstA) },
          { ordinal: 2, ...receiptEvidence(firstB) },
        ],
      },
      context: {
        first: receiptEvidence(firstA),
        followup: receiptEvidence(contextFollowup),
      },
      repair: {
        initial: receiptEvidence(malformed),
        initial_semantic_valid: initialSemanticValid,
        repaired: receiptEvidence(repaired),
        same_thread: malformed.host_thread_id === repaired.host_thread_id,
        repair_attempts: 1,
      },
      auth: {
        auth_snapshot_removed: security.auth_snapshot_removed,
        auth_snapshot_hygiene_only: security.auth_snapshot_hygiene_only,
        content_read: false,
        credential_confidentiality_guaranteed:
          security.credential_confidentiality_guaranteed,
        same_user_filesystem_read_confidentiality:
          security.same_user_filesystem_read_confidentiality,
        filesystem_observations: authObservations.map(item => structuredClone(item)),
      },
      interrupt: {
        binding: {
          host_thread_id: interruptBinding.host_thread_id,
          host_turn_id: interruptBinding.host_turn_id,
          action_ref: interruptBinding.action_ref,
        },
        receipt: receiptEvidence(interruptReceipt),
        lifecycle: interruptLifecycle,
      },
      cleanup: cleanup.map(item => ({
        schema: item.schema,
        actor_ref: item.actor_ref,
        host_thread_id: item.host_thread_id,
        background_terminals: item.background_terminals,
        deleted: item.deleted,
        deletion_notified: item.deletion_notified,
        rollout_absent: item.rollout_absent,
        rollout_path_ref: item.rollout_path_ref,
        config_digest: item.config_digest,
        environment_digest: item.environment_digest,
        receipt_digest: item.receipt_digest,
      })),
      late_result: {
        rejected: lateResultRejected,
        code: lateResultCode,
        tombstoned: interruptLifecycle.late_result_tombstone,
        host_thread_id: interruptLifecycle.host_thread_id,
        host_turn_id: interruptLifecycle.host_turn_id,
      },
      write_denial: {
        target: writeTarget,
        observation: structuredClone(writeDenial),
      },
      production_chain: {
        branded: isProductionBrainstormResult(productionResult),
        ok: productionResult.ok,
        status: productionResult.status,
        execution_path: productionResult.execution_path,
        fallback_allowed: productionResult.fallback_allowed,
        projection: {
          state_ref: structuredClone(productionResult.state_ref),
          envelope_schema: productionResult.envelope.schema,
          status: productionResult.envelope.status,
          native_started: productionResult.envelope.native_started,
          fallback_allowed: productionResult.envelope.fallback_allowed,
          workload_binding: {
            workload_digest: digest(fixture.production_workload),
            controller_request_digest:
              productionResult.workflow_receipt.execution_input.request_digest,
            controller_run_id: productionRequest.run_id,
            concurrency:
              productionResult.workflow_receipt.execution_input.concurrency,
            cwd_ref: productionResult.workflow_receipt.execution_input.cwd_ref,
            actual_model:
              productionResult.workflow_receipt.admission.actual_model,
            actual_reasoning_effort:
              productionResult.workflow_receipt.admission.actual_reasoning_effort,
            model_evidence: 'controller-workflow-admission-receipt',
          },
          controller_counters: controllerCounters,
          broker_output: brokerOutputProjection,
          raw_state_exposed: false,
        },
        workflow_receipt: structuredClone(productionResult.workflow_receipt),
      },
      action_receipts: actionReceiptEvidence,
    }
    const contract = {
      ...fixture.contract,
      executable: BUNDLED_CODEX_BINARY,
      admission_evidence_digest: capability.admission_evidence_digest,
      environment_digest: capability.environment_digest,
      tool_inventory_capture_ref: capability.tool_inventory_capture.capture_ref,
      tool_inventory_evidence_digest: capability.tool_inventory_capture.evidence_digest,
      tool_inventory_provider_delta_digest:
        capability.tool_inventory_capture.provider_delta_digest,
    }
    const checks = [
      namedCheck('exact_pinned_contract', (
        capability.version === fixture.contract.version
        && capability.binary_digest === fixture.contract.binary_digest
        && capability.schema_digest === fixture.contract.schema_digest
        && capability.config_digest === fixture.contract.config_digest
        && capability.contract_stability === fixture.contract.contract_stability
        && capability.experimental_api === true
        && capability.tool_inventory_capture.evidence_class === 'live-loopback-raw-request'
      ), contract),
      namedCheck('isolated_inventory', (
        admission.inventory.hooks === 0
        && admission.inventory.hook_errors === 0
        && admission.inventory.hook_warnings === 0
        && admission.inventory.skills === 0
        && admission.inventory.skill_errors === 0
        && admission.inventory.plugins === 0
        && admission.inventory.plugin_load_errors === 0
        && admission.inventory.apps === 0
        && admission.inventory.mcp_servers === 0
        && admission.tool_inventory_capture.captured === true
        && admission.tool_inventory_capture.capture_ref
          === admission.tool_inventory_capture.raw_tools_digest
      ), {
        inventory: admission.inventory,
        tool_inventory_capture: admission.tool_inventory_capture,
      }),
      namedCheck(
        'distinct_role_threads',
        new Set(rawEvidence.roles.map(role => role.host_thread_id)).size === rawEvidence.roles.length,
        { roles: rawEvidence.roles },
      ),
      namedCheck('same_thread_context_followup', (
        firstA.host_thread_id === contextFollowup.host_thread_id
        && firstA.host_turn_id !== contextFollowup.host_turn_id
        && contextFollowup.output.remembered_nonce === fixture.synthetic.context_nonce
      ), rawEvidence.context),
      namedCheck('exact_structured_output', (
        firstA.output.nonce === fixture.synthetic.context_nonce
        && firstB.output.answer === fixture.synthetic.role_b_answer
      ), { first_a: firstA.output, first_b: firstB.output }),
      namedCheck('same_thread_single_repair', (
        !initialSemanticValid
        && malformed.host_thread_id === repaired.host_thread_id
        && repaired.output.answer === fixture.synthetic.repaired_answer
        && repaired.output.context_nonce === fixture.synthetic.context_nonce
      ), rawEvidence.repair),
      namedCheck('bounded_barrier', (
        rawEvidence.barrier.width === fixture.limits.barrier_width
        && rawEvidence.barrier.results.length === fixture.limits.barrier_width
      ), rawEvidence.barrier),
      namedCheck(
        'readonly_write_denial',
        isAdapterOwnedNativeObservation(writeDenial)
          && writeDenial.target_absent === true
          && writeDenial.exit_code !== 0
          && writeDenial.permission_profile === ':read-only'
          && writeDenial.sandbox_network_access === false,
        rawEvidence.write_denial,
      ),
      namedCheck('auth_snapshot_absent', (
        security.auth_snapshot_removed
        && security.auth_snapshot_hygiene_only === true
        && security.credential_confidentiality_guaranteed === false
        && authObservations.length === 8
        && authObservations.every(item => item.absent === true)
      ), rawEvidence.auth),
      namedCheck('matching_interrupt', (
        interruptReceipt.terminal_status === 'interrupted'
        && interruptReceipt.host_thread_id === interruptBinding.host_thread_id
        && interruptReceipt.host_turn_id === interruptBinding.host_turn_id
      ), rawEvidence.interrupt),
      namedCheck(
        'cleanup_delete',
        cleanup.length === 3
          && cleanup.every(item => (
            isAdapterOwnedNativeReceipt(item)
            && item.deleted
            && item.deletion_notified
            && item.rollout_absent
            && item.background_terminals === 0
          )),
        { receipts: rawEvidence.cleanup },
      ),
      namedCheck(
        'late_result_fence',
        lateResultRejected && interruptLifecycle.late_result_tombstone === true,
        rawEvidence.late_result,
      ),
      namedCheck('first_dispatch_fallback_fence', (
        rawEvidence.production_chain.branded === true
        && rawEvidence.production_chain.ok === true
        && rawEvidence.production_chain.fallback_allowed === false
        && rawEvidence.production_chain.workflow_receipt.journal.dispatch_started === true
        && rawEvidence.production_chain.workflow_receipt.journal.native_response_received === true
      ), rawEvidence.production_chain),
      namedCheck('production_output_quality', (
        rawEvidence.production_chain.status === expectedProduction.status
        && rawEvidence.production_chain.projection.broker_output.verdict.alive
          === expectedProduction.verdict_alive
        && rawEvidence.production_chain.projection.broker_output.receipt.quality.theatre
          === expectedProduction.theatre
        && rawEvidence.production_chain.projection.broker_output.receipt.counters.valid_deltas
          >= expectedProduction.min_valid_deltas
        && rawEvidence.production_chain.projection.controller_counters.model_calls
          === rawEvidence.production_chain.projection.controller_counters.terminal_action_count
      ), {
        expectation: structuredClone(expectedProduction),
        projection: rawEvidence.production_chain.projection,
      }),
      namedCheck(
        'telemetry_truthful',
        true,
        { tokens: null, token_coverage: 'unavailable', wall_time_coverage: 'exact' },
      ),
      namedCheck(
        'producer_state_opaque',
        rawEvidence.production_chain.workflow_receipt.raw_state_exposed === false
          && rawEvidence.production_chain.projection.raw_state_exposed === false,
        rawEvidence.production_chain.projection,
      ),
    ]
    const finishedAt = new Date().toISOString()
    const receipt = {
      schema: LIVE_RECEIPT_SCHEMA,
      evidence_class: 'live-bundled-app-server',
      attestation_scope: 'trusted-local-observation-bound-to-adapter-receipts',
      run_id: `LIVE-${randomUUID()}`,
      fixture_digest: digest(fixture),
      synthetic_input: true,
      execution_scope: structuredClone(rawEvidence.execution_scope),
      started_at: startedAt,
      finished_at: finishedAt,
      contract,
      limits: structuredClone(fixture.limits),
      checks,
      raw_evidence: rawEvidence,
      telemetry: {
        model_turns: new Set(modelTurnIds).size,
        model_turn_coverage: 'exact',
        tokens: null,
        token_coverage: 'unavailable',
        elapsed_ms: Date.now() - startedMs,
        wall_time_coverage: 'exact',
      },
      passed: checks.every(check => check.passed),
      receipt_digest: null,
    }
    receipt.receipt_digest = liveCanaryReceiptDigest(receipt)
    return validateLiveCanaryReceipt(receipt, fixture)
  } finally {
    await adapter.close().catch(() => {})
    await rm(runtimeRoot, { recursive: true, force: true })
  }
}

function parse(argv) {
  const parsed = { fixture: DEFAULT_FIXTURE, output: null }
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index]
    const value = argv[index + 1]
    if (!['--fixture', '--output'].includes(flag) || !value) {
      throw new Error('usage: persistent_native_live_canary.mjs [--fixture FILE] [--output /private/tmp/FILE]')
    }
    parsed[flag.slice(2)] = value
  }
  parsed.fixture = resolve(parsed.fixture)
  if (
    parsed.output
    && (!isAbsolute(parsed.output) || !resolve(parsed.output).startsWith('/private/tmp/'))
  ) {
    throw new Error('--output must be an absolute path below /private/tmp')
  }
  return parsed
}

async function main() {
  try {
    const cli = parse(process.argv.slice(2))
    const receipt = await runLiveCanary({ fixturePath: cli.fixture })
    const encoded = `${JSON.stringify(receipt, null, 2)}\n`
    if (cli.output) await writeFile(cli.output, encoded, { mode: 0o600 })
    process.stdout.write(encoded)
  } catch (error) {
    process.stderr.write(`${JSON.stringify({
      schema: LIVE_RECEIPT_SCHEMA,
      passed: false,
      error: error.code || 'live_canary_failed',
      message: String(error.message || error),
      details: error.details || {},
    })}\n`)
    process.exitCode = 1
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main()
}
