#!/usr/bin/env node
import { lstat, readFile } from 'node:fs/promises'
import { isAbsolute, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { PersistentBrokerError } from '../broker/persistent_brainstorm_broker.mjs'
import { PersistentBrainstormStore } from '../broker/persistent_brainstorm_store.mjs'

const MAX_REQUEST_BYTES = 1024 * 1024

function parse(argv) {
  const parsed = {}
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index]
    const value = argv[index + 1]
    if (!['--request-file', '--state-root'].includes(flag) || !value) {
      throw new PersistentBrokerError(
        'usage',
        'usage: persistent_brainstorm_driver.mjs --state-root /absolute/runtime-root --request-file /absolute/request.json',
      )
    }
    parsed[flag.slice(2)] = value
  }
  if (!isAbsolute(parsed['request-file']) || !isAbsolute(parsed['state-root'])) {
    throw new PersistentBrokerError('usage', 'request-file and state-root must be absolute')
  }
  return { requestFile: parsed['request-file'], stateRoot: parsed['state-root'] }
}

function exactKeys(value, expected, label) {
  const actual = value && typeof value === 'object' && !Array.isArray(value)
    ? Object.keys(value).sort()
    : []
  const wanted = [...expected].sort()
  if (JSON.stringify(actual) !== JSON.stringify(wanted)) {
    throw new PersistentBrokerError('invalid_request', `${label} fields differ from the exact contract`)
  }
}

export async function executePersistentRequest(request, store) {
  if (request?.op === 'create') {
    exactKeys(request, ['op', 'input'], 'create request')
    const result = await store.create(request.input)
    return { schema: 'studio-persistent-brainstorm-driver/v2', ok: true, ...result }
  }
  if (request?.op === 'apply') {
    exactKeys(
      request,
      ['op', 'run_id', 'expected_state_revision', 'expected_state_digest', 'receipt'],
      'apply request',
    )
    const result = await store.apply(request)
    return { schema: 'studio-persistent-brainstorm-driver/v2', ok: true, ...result }
  }
  throw new PersistentBrokerError('invalid_request', 'request.op must be create or apply')
}

async function readRequest(path) {
  const info = await lstat(path).catch(() => null)
  if (!info || !info.isFile() || info.isSymbolicLink() || info.size > MAX_REQUEST_BYTES) {
    throw new PersistentBrokerError('request_file_invalid', 'request must be a bounded regular non-symlink file')
  }
  return JSON.parse(await readFile(path, 'utf8'))
}

async function main() {
  try {
    const cli = parse(process.argv.slice(2))
    const request = await readRequest(cli.requestFile)
    const result = await executePersistentRequest(request, new PersistentBrainstormStore(cli.stateRoot))
    process.stdout.write(`${JSON.stringify(result)}\n`)
  } catch (error) {
    process.stdout.write(`${JSON.stringify({
      schema: 'studio-persistent-brainstorm-driver/v2',
      ok: false,
      error: error instanceof PersistentBrokerError ? error.code : 'internal_error',
      message: String(error.message || error),
      details: error instanceof PersistentBrokerError ? error.details : {},
    })}\n`)
    process.exitCode = 1
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main()
}
