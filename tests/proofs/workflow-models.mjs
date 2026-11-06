// Adopted from seathatflowsinourveins/northstar@b384d298d217d3f8d9aa83356994629536a34795:
// evals/workflows/check-models.mjs; only the reusable scanner/check exports.
export const ALIASES = new Set(['haiku', 'sonnet', 'opus', 'fable'])

// Blank out comments, strings and regex literals (keeping template ${...} code), preserving offsets.
function mask(src) {
  const out = src.split('')
  const blank = (a, b) => { for (let i = a; i < b; i++) if (out[i] !== '\n') out[i] = ' ' }
  const str = (j) => { const q = src[j]; let k = j + 1; while (k < src.length && src[k] !== q) k += src[k] === '\\' ? 2 : 1; return k + 1 }
  // Scan a template literal body from just after the backtick; returns the index after the closing backtick.
  const tpl = (start) => {
    let j = start
    while (j < src.length) {
      if (src[j] === '\\') { blank(j, j + 2); j += 2; continue }
      if (src[j] === '`') return j + 1
      if (src[j] === '$' && src[j + 1] === '{') { // use the same lexer inside template code, including regexes/comments
        j = code(j + 2, true); continue
      }
      blank(j, j + 1); j++
    }
    return j
  }
  // A "/" starts a regex literal after an operator, "(" etc., after "=>", and after a keyword such as return.
  // Reading it as division would parse the regex body as code, and a quote in it would swallow real calls.
  const KEYWORDS = new Set(['return', 'typeof', 'case', 'in', 'of', 'delete', 'void', 'throw', 'new', 'else', 'do', 'yield', 'await'])
  const code = (start, interpolation = false) => {
    let i = start, prev = '', prevIdx = -1, word = '', depth = 0
    while (i < src.length) {
      const c = src[i], n = src[i + 1]
      if (interpolation && c === '}' && depth === 0) return i + 1
      if (c === '/' && n === '/') { let e = src.indexOf('\n', i); if (e < 0) e = src.length; blank(i, e); i = e; continue }
      if (c === '/' && n === '*') { let e = src.indexOf('*/', i + 2); e = e < 0 ? src.length : e + 2; blank(i, e); i = e; continue }
      if (c === "'" || c === '"') { const e = str(i); blank(i + 1, e - 1); i = e; prev = c; prevIdx = e - 1; word = ""; continue }
      if (c === "`") { const e = tpl(i + 1); i = e; prev = c; prevIdx = e - 1; word = ""; continue }
      const arrow = prev === '>' && src[prevIdx - 1] === '='
      if (c === '/' && (prev === '' || arrow || KEYWORDS.has(word) || '(,=:[!&|?{};'.includes(prev))) { // regex literal
        let k = i + 1, cls = false
        while (k < src.length && (src[k] !== '/' || cls)) { if (src[k] === '\\') k++; else if (src[k] === '[') cls = true; else if (src[k] === ']') cls = false; k++ }
        blank(i + 1, k); i = k + 1; prev = '/'; prevIdx = k; word = ''; continue
      }
      if (c === '{') depth++
      else if (c === '}') depth--
      if (!/\s/.test(c)) { prev = c; prevIdx = i; word = /[\w$]/.test(c) ? (/[\w$]/.test(src[i - 1] || '') ? word : '') + c : '' }
      i++
    }
    return i
  }
  code(0)
  return out.join('')
}

// All agent( calls: [{line, args: raw source of the arguments, masked}]
export function agentCalls(src) {
  const m = mask(src), calls = []
  const re = /(^|[^\w.$])agent\s*\(/g
  let x
  while ((x = re.exec(m))) {
    const open = x.index + x[0].length - 1
    let depth = 0, k = open
    for (; k < m.length; k++) { if (m[k] === '(') depth++; else if (m[k] === ')' && !--depth) break }
    if (depth) throw new Error(`unbalanced agent( at line ${src.slice(0, open).split('\n').length}`)
    calls.push({ line: src.slice(0, open).split('\n').length, args: src.slice(open + 1, k), masked: m.slice(open + 1, k) })
  }
  return calls
}

export function routingTable(src, name) {
  const masked = mask(src), t = masked.match(new RegExp(`\\bconst ${name}\\s*=\\s*\\{`))
  if (!t) return null
  const start = masked.indexOf('{', t.index)
  let depth = 0, k = start
  for (; k < masked.length; k++) { if (masked[k] === '{') depth++; else if (masked[k] === '}' && !--depth) break }
  return Function(`return (${src.slice(start, k + 1)})`)()
}

export const modelTable = src => routingTable(src, 'MODEL')

export function check(src, opts = {}) {
  const problems = []
  const table = modelTable(src)
  if (table) for (const [k, v] of Object.entries(table)) if (!ALIASES.has(v)) problems.push(`MODEL.${k} = ${JSON.stringify(v)} is not an alias (${[...ALIASES].join('|')})`)
  if (opts.expectTable) {
    const want = opts.expectTable, have = table || {}
    for (const k of Object.keys(want)) if (have[k] !== want[k]) problems.push(`MODEL.${k} is ${JSON.stringify(have[k])}, the routing pin says ${JSON.stringify(want[k])}`)
    for (const k of Object.keys(have)) if (!(k in want)) problems.push(`MODEL.${k} is not in the routing pin (add it to EXPECTED in check-models.mjs)`)
  }
  for (const c of agentCalls(src)) {
    // The masked text hides string contents, so a "model:" inside a prompt never matches.
    const all = [...c.masked.matchAll(/\bmodel\s*:/g)]
    if (all.length > 1) { problems.push(`line ${c.line}: agent() call sets model more than once`); continue }
    const mm = c.masked.match(/\bmodel\s*:\s*([^,}\n]+)/)
    if (!mm) { problems.push(`line ${c.line}: agent() call has no explicit model`); continue }
    const expr = c.args.slice(mm.index + mm[0].length - mm[1].length, mm.index + mm[0].length).trim()
    // A conditional `cond ? A : B` is allowed (refuter model by severity); every branch must be an alias.
    const q = expr.indexOf('?')
    const branches = q < 0 ? [expr] : expr.slice(q + 1).split(':').map(s => s.trim())
    const resolved = []
    let ok = true
    for (const b of branches) {
      const lit = b.match(/^(['"])([^'"]*)\1$/)
      const ref = b.match(/^MODEL\.(\w+)$/)
      if (lit) { if (!ALIASES.has(lit[2])) { problems.push(`line ${c.line}: model ${JSON.stringify(lit[2])} is not an alias`); ok = false } else resolved.push(lit[2]) }
      else if (ref) { if (!table || !(ref[1] in table)) { problems.push(`line ${c.line}: MODEL.${ref[1]} is not in the script's MODEL table`); ok = false } else resolved.push(table[ref[1]]) }
      else { problems.push(`line ${c.line}: model must be an alias literal or MODEL.<key>, got ${b}`); ok = false }
    }
    if (ok && opts.agents) {
      const at = c.masked.match(/\bagentType\s*:/)
      const t = at && c.args.slice(at.index + at[0].length).match(/^\s*(['"])(\w[\w-]*)\1/)
      if (t && t[2] in opts.agents) {
        for (const r of resolved) if (r !== opts.agents[t[2]]) problems.push(`line ${c.line}: agentType ${t[2]} is defined as ${opts.agents[t[2]]} in claude/agents/${t[2]}.md but this call uses ${r}`)
      } else if (t) problems.push(`line ${c.line}: agentType ${t[2]} has no model in claude/agents/${t[2]}.md`)
    }
  }
  return problems
}
