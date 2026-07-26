#!/usr/bin/env node
import { readFile } from 'node:fs/promises'
import { isAbsolute, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  PersistentBrokerError,
  applyPersistentBarrier,
  createPersistentBrainstorm,
  persistentBrainstormEnvelope,
} from '../broker/persistent_brainstorm_broker.mjs'

function parse(argv) {
  if (argv.length !== 2 || argv[0] !== '--request-file' || !isAbsolute(argv[1])) {
    throw new PersistentBrokerError(
      'usage',
      'usage: persistent_brainstorm_driver.mjs --request-file /absolute/sealed-request.json',
    )
  }
  return argv[1]
}

export function executePersistentRequest(request) {
  if (!request || !['create', 'apply'].includes(request.op)) {
    throw new PersistentBrokerError('invalid_request', 'request.op must be create or apply')
  }
  const state = request.op === 'create'
    ? createPersistentBrainstorm(request.input)
    : applyPersistentBarrier(request.state, request.receipt)
  return {
    schema: 'studio-persistent-brainstorm-driver/v1',
    ok: true,
    state,
    envelope: persistentBrainstormEnvelope(state),
  }
}

async function main() {
  try {
    const path = parse(process.argv.slice(2))
    const request = JSON.parse(await readFile(path, 'utf8'))
    process.stdout.write(`${JSON.stringify(executePersistentRequest(request))}\n`)
  } catch (error) {
    process.stdout.write(`${JSON.stringify({
      schema: 'studio-persistent-brainstorm-driver/v1',
      ok: false,
      error: error instanceof PersistentBrokerError ? error.code : 'internal_error',
      message: String(error.message || error),
    })}\n`)
    process.exitCode = 1
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main()
}
