// Adopted from seathatflowsinourveins/northstar@b384d298d217d3f8d9aa83356994629536a34795:
// evals/workflows/mock-runtime.mjs; custom agent definitions are not installed here.
// Deterministic mock of the Claude Code Workflow runtime, for testing claude/workflows/*.js offline.
//
// Semantics follow the workflow-authoring reference:
//   - agent() returns the scripted value, or null when the agent is skipped or dies.
//   - parallel(thunks) is a barrier; a thunk that throws resolves to null; it never rejects.
//   - pipeline(items, ...stages) runs each item through every stage independently; each stage gets
//     (prev, item, index); a stage that throws drops that item to null and skips its remaining stages.
// The reference does not say whether a stage that RETURNS null still feeds the next stage, so the mock
// runs every scenario under both readings (nullMode 'pass' and 'drop'); a workflow must be fail-closed
// under either.
//
// The mock also enforces what the real runtime enforces at agent() time (schema shape, option values),
// validates every scripted response against the agent's schema (so fixtures cannot drift from the
// workflow's contract), and makes Date.now()/Math.random()/new Date() throw like the real runtime.
import { readFileSync } from 'node:fs'

export class HarnessError extends Error {}

const EFFORTS = new Set(['low', 'medium', 'high', 'xhigh', 'max'])
const AGENT_EFFORTS = {}
const MODEL_ALIASES = new Set(['haiku', 'sonnet', 'opus', 'fable'])
const OPT_KEYS = new Set(['label', 'phase', 'schema', 'model', 'effort', 'isolation', 'agentType'])

// Minimal JSON Schema subset used by the workflows: type, properties, required, items, enum.
export function validate(value, schema, path = '$') {
  if (!schema) return []
  const errs = []
  const types = [].concat(schema.type || [])
  const typeOf = v => (v === null ? 'null' : Array.isArray(v) ? 'array' : Number.isInteger(v) ? 'integer' : typeof v)
  if (types.length) {
    const t = typeOf(value)
    const ok = types.some(x => x === t || (x === 'number' && t === 'integer'))
    if (!ok) return [`${path}: expected ${types.join('|')}, got ${t}`]
  }
  if (schema.enum && !schema.enum.includes(value)) errs.push(`${path}: ${JSON.stringify(value)} not in enum`)
  if (typeOf(value) === 'object') {
    for (const k of schema.required || []) if (!(k in value)) errs.push(`${path}: missing required "${k}"`)
    for (const [k, sub] of Object.entries(schema.properties || {})) if (k in value) errs.push(...validate(value[k], sub, `${path}.${k}`))
  }
  if (typeOf(value) === 'array' && schema.items) value.forEach((v, i) => errs.push(...validate(v, schema.items, `${path}[${i}]`)))
  return errs
}

function checkSchemaShape(schema, path = 'schema') {
  const errs = []
  if (schema.type === 'object') {
    if (!schema.properties || typeof schema.properties !== 'object') errs.push(`${path}: object schema without properties`)
    for (const k of schema.required || []) if (!schema.properties || !(k in schema.properties)) errs.push(`${path}: required "${k}" not in properties`)
    for (const [k, sub] of Object.entries(schema.properties || {})) errs.push(...checkSchemaShape(sub, `${path}.${k}`))
  }
  if (schema.type === 'array' && schema.items) errs.push(...checkSchemaShape(schema.items, `${path}[]`))
  return errs
}

// Extract and evaluate the pure-literal meta object (everything up to the first column-0 closing brace).
export function readMeta(src) {
  const m = src.match(/^export const meta = (\{[\s\S]*?\n\})/m)
  if (!m) throw new HarnessError('meta literal not found')
  return new Function(`return (${m[1]})`)()
}

const tick = () => new Promise(r => setTimeout(r, 1))

export async function runWorkflow(file, { args, respond, nullMode = 'pass' } = {}) {
  const src = readFileSync(file, 'utf8')
  const meta = readMeta(src)
  const metaPhases = new Set((meta.phases || []).map(p => p.title))
  const body = src.replace(/^export const meta/m, 'const meta')
  const calls = [], logs = [], harness = [], phasesUsed = new Set()
  const inflight = {}, maxInflight = {}, seen = {}
  let current = '?'

  async function agent(prompt, opts = {}) {
    const phaseName = opts.phase || current
    phasesUsed.add(phaseName)
    for (const k of Object.keys(opts)) if (!OPT_KEYS.has(k)) harness.push(`unknown agent option "${k}" (${opts.label})`)
    if (typeof prompt !== 'string' || !prompt.trim()) harness.push(`empty prompt (${opts.label})`)
    if (!opts.label) harness.push(`agent without label in phase ${phaseName}`)
    if (!MODEL_ALIASES.has(opts.model)) harness.push(`agent without an alias model (${opts.label}): ${JSON.stringify(opts.model)}`)
    const definedEffort = AGENT_EFFORTS[opts.agentType]
    if (Object.hasOwn(opts, 'effort')) {
      if (!EFFORTS.has(opts.effort)) harness.push(`bad effort ${opts.effort} (${opts.label})`)
      // ADR-0003/0048: equal explicit efforts remove ambiguity; lower/spread/variable overrides do not.
      if (definedEffort && opts.effort !== definedEffort) harness.push(`${opts.agentType} effort ${opts.effort} differs from definition ${definedEffort} (${opts.label})`)
    } else if (!EFFORTS.has(definedEffort)) harness.push(`agent without explicit effort or a definition effort (${opts.label})`)
    if (opts.isolation && opts.isolation !== 'worktree') harness.push(`bad isolation ${opts.isolation} (${opts.label})`)
    if (opts.schema) {
      if (opts.schema.type !== 'object') harness.push(`schema root must be an object (${opts.label})`)
      harness.push(...checkSchemaShape(opts.schema).map(e => `${e} (${opts.label})`))
    }
    const label = opts.label || '?'
    const n = (seen[label] = (seen[label] || 0) + 1) - 1
    const call = { label, key: `${label}#${n}`, prompt, opts, phase: phaseName, index: calls.length }
    calls.push(call)
    inflight[phaseName] = (inflight[phaseName] || 0) + 1
    maxInflight[phaseName] = Math.max(maxInflight[phaseName] || 0, inflight[phaseName])
    try {
      await tick()
      let out
      try { out = respond ? respond(call) : null } catch (e) {
        if (e instanceof HarnessError) { harness.push(e.message); return null }
        throw e
      }
      if (out === undefined) out = null
      if (out !== null && opts.schema) {
        const errs = validate(out, opts.schema)
        if (errs.length) harness.push(`fixture for ${call.key} violates schema: ${errs.join('; ')}`)
      }
      if (out !== null && !opts.schema && typeof out !== 'string') harness.push(`fixture for ${call.key} must be a string (no schema)`)
      call.result = out
      return out === null ? null : structuredClone(out)
    } finally { inflight[phaseName]-- }
  }
  async function parallel(thunks) {
    return Promise.all(thunks.map(t => Promise.resolve().then(t).catch(() => null)))
  }
  async function pipeline(items, ...stages) {
    return Promise.all(items.map(async (item, i) => {
      let r = item
      for (const stage of stages) {
        try { r = await stage(r, item, i) } catch { return null }
        if (r === undefined) r = null
        if (r === null && nullMode === 'drop') return null
      }
      return r
    }))
  }
  const phase = t => { current = t; phasesUsed.add(t) }
  const log = m => { logs.push(String(m)) }
  const budget = { total: null, spent: () => 0, remaining: () => Infinity }
  const workflow = async () => { throw new HarnessError('workflow() is not mocked') }

  const RealDate = Date, realRandom = Math.random
  const forbid = name => () => { throw new HarnessError(`${name} is not available in workflow scripts`) }
  globalThis.Date = class extends RealDate {
    constructor(...a) { if (!a.length) throw new HarnessError('new Date() is not available in workflow scripts'); super(...a) }
    static now() { return forbid('Date.now()')() }
  }
  Math.random = forbid('Math.random()')
  let result, error
  try {
    const fn = new Function('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', `return (async () => {\n${body}\n})()`)
    result = await fn(agent, parallel, pipeline, phase, log, structuredClone(args), budget, workflow)
  } catch (e) {
    if (e instanceof HarnessError) harness.push(e.message)
    error = e
  } finally {
    globalThis.Date = RealDate
    Math.random = realRandom
  }
  for (const p of phasesUsed) if (p !== '?' && !metaPhases.has(p)) harness.push(`phase "${p}" is not declared in meta.phases`)
  return { meta, result, error, calls, logs, harness, maxInflight, labels: calls.map(c => c.label) }
}

// Fixture router: [[matcher, value | (call) => value], ...]; matcher is an exact label, a RegExp on
// the label, or a predicate on the call. An unmatched call is a fixture bug, never a silent null.
export function route(table) {
  return call => {
    for (const [m, v] of table) {
      const hit = typeof m === 'string' ? m === call.label : m instanceof RegExp ? m.test(call.label) : m(call)
      if (hit) return typeof v === 'function' ? v(call) : structuredClone(v)
    }
    throw new HarnessError(`no fixture for agent ${call.key}`)
  }
}

// Wrap a responder so the listed call keys (label#occurrence) return null (dead or skipped agent).
export function withNulls(respond, keys) {
  const set = new Set(keys)
  return call => (set.has(call.key) ? null : respond(call))
}

export const allNull = () => null
