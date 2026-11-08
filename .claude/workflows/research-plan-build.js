export const meta = {
  name: 'research-plan-build',
  description: 'Evidence research -> plan + ADR + GitHub Issues -> TDD in worktrees and dependency waves -> skeptic per task -> one tested branch -> optional exact-SHA cross-family review -> report. A dead agent never counts as PASS',
  whenToUse: 'A substantial feature or subsystem. args: {task: string, test_cmd?: string, slug?: string, cross_model?: true (read the existing GitHub review check; off by default)}',
  phases: [
    { title: 'Research', detail: 'docs, papers, code map, prior decisions in parallel' },
    { title: 'Design', detail: 'architect writes ADR, interfaces, test plan, task list on the integration branch' },
    { title: 'Build', detail: 'per dependency wave: one implementer per task in its own worktree, then skeptic' },
    { title: 'Integrate', detail: 'per wave: merge passing branches into rpb/<slug>, run the tests; the branch advances only when green' },
    { title: 'Cross-check', detail: 'read the cross-family GitHub review check on the exact integrated SHA' },
  ],
}

// Adopted upstream-first clause; Sextant's AGENTS.md and manifest own the local rule.
const UPSTREAM_FIRST = `Sextant adopts maintained upstream sources; never invent a mechanism (AGENTS.md Rule 1).
Before you write any new mechanism, search this repo's adapters and templates, then the pinned upstream's release, examples, templates, docs, issues and discussions.
- Build from that pinned upstream example, template or reference implementation. If none exists, stop: only the owner can approve an exception, recorded in docs/manifest.md with where you looked.
- Cite every API, flag, config key and pattern as repo@tag:path:line, or a docs URL with its read date.
- Pin exact versions with lockfile hashes or full commit SHAs; never a moving branch or tag.
- Record every deviation with its reason, and mark anything you did not verify as UNVERIFIED.
- Never invent a package, flag, endpoint or config key.
- If you changed a mechanism, return exactly one source line (in upstream_line when present):
  upstream checked: <repo@tag:path>
  none exists: <where you looked>
- A none exists line is a stop, not permission to build. Keep the source, adoption and proof in docs/manifest.md.
- Reviewers flag a missing source line, unsourced API, unexplained deviation or self-built substitute for an existing upstream practice.`

// Preserve the source model aliases by job.
const MODEL = { research: 'sonnet', architect: 'opus', impl: 'sonnet', skeptic: 'opus', integrate: 'sonnet', cross: 'sonnet' }
// Preserve the source effort levels for the retained jobs.
const EFFORT = { research: 'medium', architect: 'xhigh', impl: 'xhigh', skeptic: 'high', integrate: 'max', cross: 'max' }

const task = typeof args === 'string' ? args : (args && args.task)
if (!task) throw new Error('pass args: {task: "...", test_cmd?: "make test"}')
const opts = args && typeof args === 'object' ? args : {}
const testCmd = opts.test_cmd || 'uv run --frozen pytest'
// Opt-in: the required GitHub review can only be read once a PR/check exists for this exact SHA.
const crossModel = opts.cross_model === true
const clean = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
const slug = clean(opts.slug || task).slice(0, 40).replace(/-+$/, '') || 'task'
const INTEG = `rpb/${slug}`
const branchId = id => String(id).replace(/[^A-Za-z0-9._-]+/g, '-')
const SHA_RE = /^[0-9a-f]{40}$/i

// The two-line rule of the clause: 'checked' names the upstream built from, 'none' says none exists (a skeptic then verifies it), anything else
// (prose, an unfilled placeholder) is 'missing' and stops the work it came with.
const upstreamWord = s => {
  const lines = String(s || '').split('\n').map(l => l.replace(/\r$/, ''))
  const claim = l => /^[ \t]*(upstream checked:|none exists:)/.test(l) && !/[<>]/.test(l)
  const trim = l => l.replace(/^[ \t]+|[ \t]+$/g, '')
  const claims = new Set()
  let fence = ''
  for (const l of lines) {
    const m = l.match(/^[ \t]*(`{3,}|~{3,})/)
    if (m) {
      if (!fence) fence = m[1]
      else if (m[1][0] === fence[0] && m[1].length >= fence.length && /^[ \t]*(`+|~+)[ \t]*$/.test(l)) fence = ''
      continue
    }
    if (!fence && claim(l)) claims.add(trim(l))
  }
  const edges = lines.filter(l => /[^ \t]/.test(l))
  for (const l of [edges[0], edges[edges.length - 1]]) if (l !== undefined && claim(l)) claims.add(trim(l))
  if (claims.size !== 1) return 'missing'
  const [c] = claims
  return /^upstream checked: [^ \t<>]+@[^ \t<>]+:[^ \t<>]+/.test(c) ? 'checked' : /^none exists: [^ \t<>]/.test(c) ? 'none' : 'missing'
}
// What every agent that designs or writes a mechanism returns besides its work (schema-required): the line, the references, the deviations.
const UP = { upstream_line: { type: 'string' }, upstream_references: { type: 'array', items: { type: 'string' } }, deviations: { type: 'array', items: { type: 'string' } } }
const UP_REQUIRED = ['upstream_line', 'upstream_references', 'deviations']
// The clause asks for the line only when a mechanism changed (lane review of 747e4a9). An implementer that says it changed none
// (mechanism_changed false) and gives no line is 'n/a', and its skeptic checks that claim against the diff; a line, once given, must be valid.
const buildWord = b => (b.mechanism_changed === false && !String(b.upstream_line || '').trim() ? 'n/a' : upstreamWord(b.upstream_line))

const NOTE = { type: 'object', properties: { summary: { type: 'string' }, sources: { type: 'array', items: { type: 'string' } }, open_questions: { type: 'array', items: { type: 'string' } } }, required: ['summary', 'sources'] }
const PLAN = {
  type: 'object',
  properties: {
    adr_path: { type: 'string' },
    research_note_path: { type: 'string' },
    ...UP,
    tasks: { type: 'array', items: { type: 'object', properties: {
      id: { type: 'string' }, title: { type: 'string' }, spec: { type: 'string' },
      acceptance: { type: 'array', items: { type: 'string' } }, depends_on: { type: 'array', items: { type: 'string' } },
    }, required: ['id', 'title', 'spec', 'acceptance'] } },
  },
  required: ['tasks', ...UP_REQUIRED],
}
const BUILD = { type: 'object', properties: { branch: { type: 'string' }, summary: { type: 'string' }, tests_passed: { type: 'boolean' }, unverified: { type: 'array', items: { type: 'string' } }, mechanism_changed: { type: 'boolean' }, ...UP }, required: ['branch', 'summary', 'tests_passed', 'mechanism_changed', ...UP_REQUIRED] }
const VERDICT = { type: 'object', properties: { verdict: { type: 'string', enum: ['PASS', 'PASS-WITH-NITS', 'FAIL'] }, findings: { type: 'array', items: { type: 'string' } } }, required: ['verdict', 'findings'] }
const INTEGRATE = { type: 'object', properties: {
  branch: { type: 'string' }, head_sha: { type: 'string' }, merged: { type: 'array', items: { type: 'string' } },
  conflicts: { type: 'array', items: { type: 'string' } }, tests_passed: { type: 'boolean' }, advanced: { type: 'boolean' },
}, required: ['branch', 'head_sha', 'merged', 'conflicts', 'tests_passed', 'advanced'] }
const CROSS = { type: 'object', properties: {
  ran: { type: 'boolean' }, verdict: { type: 'string', enum: ['PASS', 'PASS-WITH-NITS', 'FAIL'] },
  head_sha: { type: 'string' }, findings: { type: 'array', items: { type: 'string' } }, skip_reason: { type: 'string' },
}, required: ['ran', 'findings'] }

phase('Research')
const angles = [
  ['docs', 'Official documentation and installed API source of every library/service involved. Use only tools available here; note versions and read dates.'],
  ['papers', 'Peer-reviewed or well-cited methods relevant to the task, using available public sources. Skip if purely engineering.'],
  ['code', 'Map the current codebase: entry points, interfaces, tests and conventions. Use the repo files and available search tools.'],
  ['prior', 'Prior decisions, research and manifest rows in docs/adr/, docs/research/ and docs/manifest.md; open GitHub Issues using gh issue list.'],
]
const notes = await parallel(angles.map(([k, p]) => () =>
  agent(`Task: ${task}\n\nResearch angle "${k}": ${p}\nReturn findings with sources; mark anything unverified.\n\n${UPSTREAM_FIRST}`, { label: `research:${k}`, phase: 'Research', schema: NOTE, effort: EFFORT.research, model: MODEL.research })))
// Label each note by its own index BEFORE dropping nulls, so a dead angle cannot shift the labels of the rest.
const research_missing = angles.filter((_, i) => !notes[i]).map(([k]) => k)
if (research_missing.length) log(`research-plan-build: research angle(s) returned nothing: ${research_missing.join(', ')}`)
const evidence = notes
  .map((n, i) => n && `## ${angles[i][0]}\n${n.summary}\nSources: ${n.sources.join(', ')}\nOpen: ${(n.open_questions || []).join('; ')}`)
  .filter(Boolean).join('\n\n') +
  (research_missing.length ? `\n\nMISSING research angles (the agent returned nothing; treat as unknown, not as "nothing found"): ${research_missing.join(', ')}` : '')
const stop = (status, reason, extra = {}) => ({ task, status, reason, research_missing, integration_branch: null, integration_head: null, ...extra })

phase('Design')
const plan = await agent(
  `Task: ${task}\n\nEvidence gathered:\n${evidence}\n\n${UPSTREAM_FIRST}\n\n` +
  'Report your upstream line, the references (repo@tag:path:line or docs URL with the access date) and every deviation with its reason in the upstream_line, upstream_references and deviations fields. ' +
  'Write the sourced research note under docs/research/ and a proposed ADR under docs/adr/, following the existing records. Update or follow the relevant docs/manifest.md row and its proof. ' +
  'Then define interfaces (code stubs with types/docstrings) and split the work into 2-8 independently implementable tasks with acceptance criteria and dependencies (depends_on lists task ids). ' +
  'Use GitHub Issues for tasks: link an existing issue or create one with gh issue create if this run is authorized to write to GitHub; otherwise list the proposed issues in the report. ' +
  `Commit the docs and stubs on a new branch ${INTEG} created from the current HEAD, then detach (git switch --detach) so no worktree holds ${INTEG}.`,
  { label: 'architect', phase: 'Design', isolation: 'worktree', schema: PLAN, effort: EFFORT.architect, model: MODEL.architect })
if (!plan) return stop('INCONCLUSIVE', 'architect-failed', { evidence })
if (!Array.isArray(plan.tasks) || !plan.tasks.length) return stop('INCONCLUSIVE', 'no tasks planned', { evidence })
const designWord = upstreamWord(plan.upstream_line)
const design = { line: plan.upstream_line, upstream: designWord, references: plan.upstream_references || [], deviations: plan.deviations || [] }
if (designWord === 'missing') {
  return stop('INCONCLUSIVE', 'the architect reported no valid upstream line (upstream checked: <repo@tag:path> or none exists: <where you looked>)', { adr: plan.adr_path, upstream_references: { design } })
}
if (designWord === 'none') return stop('INCONCLUSIVE', 'no upstream source exists; stop for the owner exception required by AGENTS.md Rule 1', { adr: plan.adr_path, upstream_references: { design } })

// Topological waves over depends_on. Unknown ids, duplicates and cycles fail fast: no agent is spent on a
// plan whose order cannot be honoured.
function planWaves(tasks) {
  const ids = new Set()
  for (const t of tasks) { if (ids.has(t.id)) throw new Error(`duplicate task id ${t.id}`); ids.add(t.id) }
  for (const t of tasks) for (const d of t.depends_on || []) if (!ids.has(d)) throw new Error(`task ${t.id} depends on unknown id ${d}`)
  const placed = new Set(), waves = []
  let left = tasks.slice()
  while (left.length) {
    const wave = left.filter(t => (t.depends_on || []).every(d => placed.has(d)))
    if (!wave.length) throw new Error(`dependency cycle among ${left.map(t => t.id).join(', ')}`)
    wave.forEach(t => placed.add(t.id))
    waves.push(wave)
    left = left.filter(t => !placed.has(t.id))
  }
  return waves
}
let waves
try { waves = planWaves(plan.tasks) } catch (e) { return stop('FAIL', `invalid plan: ${e.message}`, { adr: plan.adr_path }) }
log(`plan: ${plan.tasks.length} tasks in ${waves.length} wave(s); ADR ${plan.adr_path || '(none)'}; integration branch ${INTEG}`)

// Each wave builds on the integration branch, which holds the design stubs plus every earlier wave that merged
// cleanly with green tests. A task whose dependency did not make it in is blocked, never built against a stub.
const state = new Map(plan.tasks.map(t => [t.id, { id: t.id, status: 'not-run' }]))
const integrated = new Set()
const integrations = []
let integrationHead = null
let halted = null
for (const [w, wave] of waves.entries()) {
  const ready = wave.filter(t => (t.depends_on || []).every(d => integrated.has(d)))
  for (const t of wave.filter(x => !ready.includes(x))) {
    state.set(t.id, { id: t.id, status: 'blocked', reason: `dependency not integrated: ${(t.depends_on || []).filter(d => !integrated.has(d)).join(', ')}` })
  }
  if (!ready.length) continue

  phase('Build')
  const built = await pipeline(
    ready,
    t => agent(
      `Implement task ${t.id}: ${t.title}\n\nSpec:\n${t.spec}\n\nAcceptance:\n- ${t.acceptance.join('\n- ')}\n` +
      `Start a new branch ${INTEG}-${branchId(t.id)} from ${INTEG} (it holds the design stubs${(t.depends_on || []).length ? ` and the integrated dependencies ${t.depends_on.join(', ')}` : ''}); commit there and return that branch.\n` +
      `Test with: ${testCmd}. Use TDD. Report tests_passed honestly.\n` +
      `Upstream the architect chose: ${plan.upstream_line}${design.references.length ? ` (references: ${design.references.join('; ')})` : ''}. Build from it. ` +
      'Return your own upstream line, references and deviations in the upstream_line, upstream_references and deviations fields. ' +
      'Set mechanism_changed to false only if your change is documentation only (no code, script, config, workflow or test logic); then upstream_line may be empty. Otherwise set it to true and give the line.\n\n' + UPSTREAM_FIRST,
      { label: `impl:${t.id}`, phase: 'Build', isolation: 'worktree', schema: BUILD, effort: EFFORT.impl, model: MODEL.impl }),
    (b, t) => (b && b.tests_passed && b.branch && ['checked', 'n/a'].includes(buildWord(b)))
      ? agent(
        `Adversarially verify task ${t.id} ("${t.title}") on branch ${b.branch}.\nAcceptance:\n- ${t.acceptance.join('\n- ')}\nImplementer summary (do not trust it): ${b.summary}\n` +
        (buildWord(b) === 'n/a'
          ? 'The implementer says it changed no mechanism (documentation only) and gave no upstream line. Check that claim against the diff: FAIL if the diff adds or changes any code, script, config, workflow or test logic.\n'
          : `The implementer reported this upstream line: ${b.upstream_line}\n`) +
        `References: ${(b.upstream_references || []).join('; ') || 'none'}. Deviations: ${(b.deviations || []).join('; ') || 'none'}.\n` +
        'Verify it. If it says none exists, search the places it names, the pinned upstream and this repo yourself. These are FAIL findings: self-built code where an upstream example, template or API exists; an API, flag or config key with no repo@tag:path:line or docs URL; a deviation from a pinned upstream without a reason.\n\n' + UPSTREAM_FIRST,
        { label: `skeptic:${t.id}`, phase: 'Build', schema: VERDICT, effort: EFFORT.skeptic, model: MODEL.skeptic }).then(v => ({ build: b, review: v }))
      : { build: b, review: null },
  )
  ready.forEach((t, i) => {
    const b = built[i] && built[i].build
    const v = built[i] && built[i].review
    const base = {
      id: t.id, branch: b ? b.branch : null, tests_passed: b ? b.tests_passed : null, verdict: v ? v.verdict : null, findings: v ? v.findings : [],
      upstream: b ? buildWord(b) : null, upstream_line: b ? b.upstream_line : null,
      upstream_references: b ? b.upstream_references || [] : [], deviations: b ? b.deviations || [] : [],
    }
    const status = !b ? 'build-failed' : !b.tests_passed ? 'tests-failed' : ['missing', 'none'].includes(base.upstream) ? 'upstream-missing' : !v ? 'review-missing' : v.verdict === 'FAIL' ? 'rejected' : 'passed'
    if (status !== 'passed') log(`research-plan-build: task ${t.id} ${status}`)
    state.set(t.id, { ...base, status })
  })
  const passing = ready.filter(t => state.get(t.id).status === 'passed')
  if (!passing.length) continue

  phase('Integrate')
  const branches = passing.map(t => state.get(t.id).branch)
  const integ = await agent(
    `Integrate wave ${w + 1} of "${task}" into ${INTEG}. In your worktree run git switch --detach ${INTEG}, then merge these branches with git merge --no-ff --no-edit, in this order: ${JSON.stringify(branches)}. ` +
    'If a merge conflicts, run git merge --abort, record that branch in conflicts and go on; do not resolve conflicts yourself. ' +
    `Then run ${testCmd} on the result. Only if every branch merged cleanly and the tests pass, advance the integration branch with git branch -f ${INTEG} HEAD (advanced=true); otherwise leave ${INTEG} where it was (advanced=false). ` +
    'Return the integration branch, the resulting head_sha, the branches merged, the conflicts, tests_passed and advanced.',
    { label: `integrate:wave${w + 1}`, phase: 'Integrate', isolation: 'worktree', schema: INTEGRATE, effort: EFFORT.integrate, model: MODEL.integrate })
  integrations.push({ wave: w + 1, branches, ...(integ || { status: 'integrator returned nothing' }) })
  if (!integ) { halted = { status: 'INCONCLUSIVE', reason: `integrator for wave ${w + 1} returned nothing` }; break }
  // An agent's success flag is not an identity check: accept only this wave's exact branch set and
  // a commit id. Keep the last accepted head for the cross-check and the commander's final result.
  const wrongResult = integ.branch !== INTEG ? `branch ${integ.branch} != ${INTEG}`
    : typeof integ.head_sha !== 'string' || !SHA_RE.test(integ.head_sha) ? 'missing or invalid full head_sha'
      : !Array.isArray(integ.merged) || integ.merged.length !== branches.length ||
        new Set(integ.merged).size !== branches.length || !branches.every(b => integ.merged.includes(b))
        ? 'merged branches must match the requested branches exactly once' : null
  if (wrongResult) {
    halted = { status: 'FAIL', reason: `wave ${w + 1} invalid integration result: ${wrongResult}` }
    break
  }
  const green = !integ.conflicts.length && integ.tests_passed && integ.advanced
  if (!green) {
    halted = { status: 'FAIL', reason: `wave ${w + 1} integration failed (conflicts: ${integ.conflicts.join(', ') || 'none'}; tests_passed: ${integ.tests_passed}; merged ${integ.merged.length}/${branches.length})` }
    break
  }
  integrationHead = integ.head_sha.toLowerCase()
  passing.forEach(t => integrated.add(t.id))
}
if (halted) log(`research-plan-build: ${halted.reason}; later waves not run, no cross-check`)

phase('Cross-check')
let cross
if (!crossModel) cross = { skipped: 'off by default; pass args.cross_model=true to read the existing exact-SHA GitHub review check' }
else if (halted || !integrated.size) cross = { skipped: halted ? 'integration did not complete' : 'nothing was integrated' }
else {
  const c = await agent(
    `Read the cross-family review of the single integrated branch ${INTEG} at exact commit ${integrationHead} from the existing GitHub PR and its required review check (.github/workflows/review.md, review-claude.md and review-codex.md). ` +
    'Resolve the branch before and after review. If either head differs from that exact commit, return ran=false with skip_reason; never review a replacement head as if it were the accepted one. ' +
    'Verify that the completed review check belongs to that exact head SHA and the reviewer family differs from the author. Do not open a PR, trigger a workflow, merge or change any check. ' +
    'If the PR, head identity, reviewer family or completed check is unavailable, return ran=false with skip_reason; never substitute your own review. ' +
    'Otherwise report the check verdict and findings without changing their disposition, and return ran=true with the reviewed head_sha. ' +
    'Also check the work against the upstream-first clause: self-built code where an upstream example, template or API exists is a finding.\n\n' + UPSTREAM_FIRST,
    { label: 'cross-family-review', phase: 'Cross-check', schema: CROSS, effort: EFFORT.cross, model: MODEL.cross })
  cross = !c ? { status: 'cross-check-failed' }
    : !c.ran ? { skipped: c.skip_reason || 'cross-model review did not run' }
      : typeof c.head_sha !== 'string' || !SHA_RE.test(c.head_sha) || c.head_sha.toLowerCase() !== integrationHead
        ? { status: 'cross-check-failed', reason: 'review head_sha does not match the accepted integration head', findings: c.findings }
        : c.verdict ? { verdict: c.verdict, head_sha: integrationHead, findings: c.findings }
        : { status: 'cross-check-failed', findings: c.findings }
  if (!cross.verdict) log(`research-plan-build: cross-model review ${cross.status || `skipped (${cross.skipped})`}`)
}

const tasks = plan.tasks.map(t => ({ ...state.get(t.id), integrated: integrated.has(t.id) }))
// FAIL: a reviewer or the tests rejected something. INCONCLUSIVE: something required did not run or answer
// (dead agent, blocked or unintegrated task, missing research angle, cross-model review not done).
const failed = (halted && halted.status === 'FAIL') || tasks.some(t => t.status === 'rejected' || t.status === 'tests-failed' || t.status === 'upstream-missing') || cross.verdict === 'FAIL'
const gaps = research_missing.length > 0 || !!halted || tasks.some(t => !t.integrated) || (crossModel && !cross.verdict)
const nits = tasks.some(t => t.verdict === 'PASS-WITH-NITS') || cross.verdict === 'PASS-WITH-NITS'
const status = failed ? 'FAIL' : gaps ? 'INCONCLUSIVE' : nits ? 'PASS-WITH-NITS' : 'PASS'
// The "Upstream references" of the PR template (.github/pull_request_template.md), collected from the agents' own fields.
const upstream_references = {
  design,
  tasks: tasks.map(t => ({ id: t.id, upstream: t.upstream ?? null, line: t.upstream_line ?? null, references: t.upstream_references ?? [], deviations: t.deviations ?? [] })),
  research_sources: [...new Set(notes.filter(Boolean).flatMap(n => n.sources))],
  template: '.github/pull_request_template.md',
}
return {
  task,
  status,
  reason: halted ? halted.reason : undefined,
  adr: plan.adr_path,
  research_note: plan.research_note_path,
  research_missing,
  integration_branch: integrated.size ? INTEG : null,
  integration_head: integrationHead,
  tasks,
  integrations,
  cross_model: cross,
  upstream_references,
  next: status === 'PASS' || status === 'PASS-WITH-NITS'
    ? `Prepare ${INTEG} for the lead with a PR body from .github/pull_request_template.md and its manifest row. Upstream references come from upstream_references above. Landing follows AGENTS.md and the required GitHub checks; this workflow grants no live authority (docs/adr/0020-live-lane.md).`
    : `Report ${INTEG} as incomplete: fix or re-run the failed, blocked or unverified steps listed above, then re-run.`,
}
