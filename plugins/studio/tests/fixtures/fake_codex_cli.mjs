#!/usr/bin/env node
import { spawn } from 'node:child_process'
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs'

const args = process.argv.slice(2)
const valueAfter = flag => args[args.indexOf(flag) + 1]
const label = process.env.STUDIO_CODEX_AGENT_LABEL || ''
const mode = process.env.FAKE_CODEX_MODE || 'broker'
const record = process.env.FAKE_CODEX_RECORD

if (args[0] !== 'exec' || args.some(arg => arg.startsWith('--dangerously-')) || args.includes('--add-dir')) {
  process.exit(64)
}

const outputPath = valueAfter('--output-last-message')
const schemaPath = valueAfter('--output-schema')
const schema = JSON.parse(readFileSync(schemaPath, 'utf8'))
const schemaHasOneOf = value => {
  if (!value || typeof value !== 'object') return false
  if (Array.isArray(value)) return value.some(schemaHasOneOf)
  return Object.hasOwn(value, 'oneOf') || Object.values(value).some(schemaHasOneOf)
}

if (record) {
  appendFileSync(record, `${JSON.stringify({
    args,
    cwd: process.cwd(),
    depth: process.env.STUDIO_CODEX_RUNNER_DEPTH,
    label,
    providerSchemaHasOneOf: schemaHasOneOf(schema),
  })}\n`)
}

if (mode === 'approval') {
  process.stderr.write('approval required; non-interactive policy denied the action\n')
  process.exit(77)
}

if (mode === 'hang') {
  const grandchildCode = 'setInterval(() => {}, 1000)'
  const childCode = [
    "const {spawn}=require('node:child_process')",
    `const grandchild=spawn(process.execPath,['-e',${JSON.stringify(grandchildCode)}],{stdio:'ignore'})`,
    "require('node:fs').writeFileSync(process.env.FAKE_CODEX_PIDS, JSON.stringify({child:process.pid,grandchild:grandchild.pid}))",
    'setInterval(() => {}, 1000)',
  ].join(';')
  spawn(process.execPath, ['-e', childCode], {
    env: process.env,
    stdio: 'ignore',
  })
  setInterval(() => {}, 1000)
}

if (mode === 'invalid') {
  writeFileSync(outputPath, '{"invalid":true}')
  process.exit(0)
}

function valueForSchema(schema) {
  if (schema.anyOf) {
    const nonNull = schema.anyOf.find(item => item.type !== 'null')
    return valueForSchema(nonNull || schema.anyOf[0])
  }
  if (schema.oneOf) return valueForSchema(schema.oneOf[0])
  if (schema.enum) return schema.enum[0]
  if (schema.type === 'object') {
    return Object.fromEntries(Object.entries(schema.properties || {}).map(([key, child]) => [key, valueForSchema(child)]))
  }
  if (schema.type === 'array') return []
  if (schema.type === 'boolean') return false
  if (schema.type === 'integer' || schema.type === 'number') return 0
  if (schema.type === 'null') return null
  return 'fake'
}

let output = valueForSchema(schema)

if (label.startsWith('diverge:') || label.startsWith('debate:')) {
  output = { utterance: `turn:${label}`, deltas: [] }
} else if (label.startsWith('critic:r')) {
  output = { verified: [] }
} else if (label === 'summarizer') {
  output = { synthesis: 'fake synthesis', minority: 'none', proposals: [] }
} else if (label === 'critic:final') {
  output = { alive: false, reason: 'dry fake run' }
} else if (label.startsWith('dev:')) {
  output = {
    summary: 'fake implementation',
    defended: [],
    unresolved: [],
    changedFiles: ['probe.txt'],
    verification: [{ command: 'fake-check', result: 'pass' }],
    blockedChecks: [],
  }
} else if (label.startsWith('qa:')) {
  output = {
    broke: false,
    failures: [],
    verification: [{ command: 'fake-check', result: 'pass' }],
    blockedChecks: [],
  }
} else if (label === 'critic:verdict') {
  output = { alive: true, reason: 'fake evidence accepted', defended_count: 0, open_count: 0 }
}

writeFileSync(outputPath, JSON.stringify(output))
