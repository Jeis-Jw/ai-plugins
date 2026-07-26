import { createHash, randomBytes } from 'node:crypto'
import {
  chmod, lstat, mkdir, open, readFile, rename, rm,
} from 'node:fs/promises'
import { isAbsolute, join, resolve } from 'node:path'
import {
  PersistentBrokerError,
  applyPersistentBarrier,
  createPersistentBrainstorm,
  persistentBrainstormEnvelope,
  persistentStateDigest,
} from './persistent_brainstorm_broker.mjs'

const MAX_STATE_BYTES = 4 * 1024 * 1024

function fileKey(runId) {
  return createHash('sha256').update(String(runId), 'utf8').digest('hex')
}

function canonicalJson(value) {
  return JSON.stringify(value, null, 2) + '\n'
}

async function readRegularJson(path) {
  const info = await lstat(path).catch(() => null)
  if (!info || !info.isFile() || info.isSymbolicLink() || info.size > MAX_STATE_BYTES) {
    throw new PersistentBrokerError('state_store_invalid', 'state file must be a bounded regular file')
  }
  try {
    return JSON.parse(await readFile(path, 'utf8'))
  } catch {
    throw new PersistentBrokerError('state_store_invalid', 'state file is not valid JSON')
  }
}

export class PersistentBrainstormStore {
  constructor(root) {
    if (!isAbsolute(root)) {
      throw new PersistentBrokerError('state_root_invalid', 'runtime state root must be absolute')
    }
    this.root = resolve(root)
  }

  async initialize() {
    await mkdir(this.root, { recursive: true, mode: 0o700 })
    const info = await lstat(this.root)
    if (!info.isDirectory() || info.isSymbolicLink()) {
      throw new PersistentBrokerError('state_root_invalid', 'runtime state root must be a real directory')
    }
    await chmod(this.root, 0o700)
  }

  paths(runId) {
    const key = fileKey(runId)
    return {
      state: join(this.root, `${key}.json`),
      lock: join(this.root, `${key}.lock`),
    }
  }

  async create(input) {
    await this.initialize()
    const state = createPersistentBrainstorm(input)
    const paths = this.paths(state.run_id)
    let handle
    try {
      handle = await open(paths.state, 'wx', 0o600)
      await handle.writeFile(canonicalJson(state), 'utf8')
      await handle.sync()
    } catch (error) {
      if (error.code === 'EEXIST') {
        throw new PersistentBrokerError('duplicate_run', 'run_id already exists in runtime-owned state')
      }
      throw error
    } finally {
      await handle?.close()
    }
    return this.project(state)
  }

  async read(runId) {
    await this.initialize()
    const state = await readRegularJson(this.paths(runId).state)
    if (state.run_id !== runId || state.state_digest !== persistentStateDigest(state)) {
      throw new PersistentBrokerError('state_tampered', 'runtime-owned state failed identity/digest validation')
    }
    return state
  }

  lockPayload() {
    const pid = globalThis.process?.pid
    if (!Number.isInteger(pid) || pid < 1) {
      throw new PersistentBrokerError('lock_owner_unavailable', 'runtime process id is unavailable')
    }
    return `${pid}:${randomBytes(8).toString('hex')}\n`
  }

  async initializeLock(handle) {
    await handle.writeFile(this.lockPayload(), 'utf8')
    await handle.sync()
  }

  async acquire(runId) {
    const { lock } = this.paths(runId)
    let handle
    try {
      handle = await open(lock, 'wx', 0o600)
      await this.initializeLock(handle)
      return { handle, path: lock }
    } catch (error) {
      if (handle) {
        await handle.close().catch(() => {})
        await rm(lock, { force: true }).catch(() => {})
      }
      if (error.code === 'EEXIST') {
        throw new PersistentBrokerError('state_busy', 'another transition owns the run lock')
      }
      throw error
    }
  }

  async commit(runId, state) {
    const { state: target } = this.paths(runId)
    const temp = `${target}.${process.pid}.${randomBytes(8).toString('hex')}.tmp`
    let handle
    try {
      handle = await open(temp, 'wx', 0o600)
      await handle.writeFile(canonicalJson(state), 'utf8')
      await handle.sync()
      await handle.close()
      handle = null
      await rename(temp, target)
    } finally {
      await handle?.close()
      await rm(temp, { force: true })
    }
  }

  async apply({ run_id: runId, expected_state_revision: revision, expected_state_digest: stateDigest, receipt }) {
    await this.initialize()
    const lock = await this.acquire(runId)
    try {
      const current = await this.read(runId)
      if (current.state_revision !== revision || current.state_digest !== stateDigest) {
        throw new PersistentBrokerError('stale_state', 'expected state revision/digest does not match runtime-owned state')
      }
      const next = applyPersistentBarrier(current, receipt)
      await this.commit(runId, next)
      return this.project(next)
    } finally {
      await lock.handle.close()
      await rm(lock.path, { force: true })
    }
  }

  project(state) {
    return {
      state_ref: {
        run_id: state.run_id,
        state_revision: state.state_revision,
        state_digest: state.state_digest,
      },
      envelope: persistentBrainstormEnvelope(state),
    }
  }
}
