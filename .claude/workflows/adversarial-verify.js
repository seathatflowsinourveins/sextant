export const meta = {
  name: 'adversarial-verify',
  description: 'On-demand multi-lens review of a branch/change, with three independent refuters per unique finding. Missing agents stay unknown. Returns a report; creates no verdict-file gate or required check',
  whenToUse: 'Before merging risky work or promoting a strategy. args: {target: "branch name, PR, path, or description", lenses?: string[], base?: "branch to diff against", date?: "YYYY-MM-DD", repo?: "/abs/path of another repo (its main checkout)", worktree?: "/abs/path of a detached worktree at expect_sha", expect_sha?: "40-hex head the review must match", notes?: "the implementing lane\'s own claims to check"}',
  phases: [
    { title: 'Resolve', detail: 'pin the target to one exact commit (and check it equals expect_sha when given)' },
    { title: 'Hunt', detail: 'collect findings from one skeptic per lens' },
    { title: 'Refute', detail: 'group exact duplicate claims, then 3 independent refuters per unique finding' },
    { title: 'Report', detail: 'recheck a frozen review worktree when supplied, then return the findings and exact reviewed identity to the lead' },
  ],
}

// Preserve the source's aliases and efforts for the retained review jobs.
const MODEL = { resolve: 'haiku', recheck: 'haiku', hunt: 'opus', refuteGate: 'opus', refuteLow: 'sonnet' }
const EFFORT = { resolve: 'low', recheck: 'low', hunt: 'high', refuteGate: 'medium', refuteLow: 'medium' }
const A = args && typeof args === 'object' ? args : {}
// Version stamp returned in every result, so a caller can see which copy of this script actually ran (a session's
// Workflow registry can hold an older copy: on 2026-10-20 three repo-mode calls ran a pre-repo-mode script and
// silently reviewed free text). Bump it whenever the argument contract changes.
const WORKFLOW_VERSION = 'adversarial-verify/sextant-1 (on-demand report; exact head/base; no verdict-file gate)'
// Unknown arguments fail loudly instead of being ignored.
const KNOWN_ARGS = ['target', 'base', 'date', 'notes', 'lenses', 'repo', 'worktree', 'expect_sha']
const unknown = Object.keys(A).filter(k => !KNOWN_ARGS.includes(k))
if (unknown.length) throw new Error(`adversarial-verify (${WORKFLOW_VERSION}) does not understand args: ${unknown.join(', ')}`)
const target = typeof args === 'string' ? args : A.target
if (!target) throw new Error('pass args: {target}')
const base = A.base
const DATE_RE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/
const notes = A.notes || ''
// Repo mode resolves a branch in its main checkout and reviews a caller-supplied, clean, detached worktree.
const SHA_RE = /^[0-9a-f]{40}$/
const repo = A.repo ? String(A.repo).replace(/\/+$/, '') : null
const worktree = A.worktree ? String(A.worktree).replace(/\/+$/, '') : null
const expect_sha = A.expect_sha ? String(A.expect_sha).toLowerCase() : null
if (expect_sha && !SHA_RE.test(expect_sha)) throw new Error(`expect_sha must be a full 40-hex commit id, got "${A.expect_sha}"`)
if (worktree && !repo) throw new Error('worktree is only used in repo mode: pass repo as well')
if (repo && (!worktree || !expect_sha)) throw new Error('repo mode needs args: {target, repo, worktree, expect_sha}')
const lenses = A.lenses || [
  'correctness and edge cases (boundaries, error paths, partial failures)',
  'concurrency, reconnection, idempotency and restart/reconciliation',
  'defensive verification of secrets and containment (confirm our own guards hold: input handling, credential exposure, unsafe defaults, sandbox and worker-runtime boundaries)',
  'quant validity (look-ahead, survivorship, overfitting, float money, paper-vs-live divergence)',
  'tests (what is untested; do the tests actually assert the behaviour?)',
]
if (!Array.isArray(lenses) || !lenses.length || lenses.some(l => typeof l !== 'string' || !l.trim())) throw new Error('lenses must be a nonempty array of nonempty strings')
// The resolver and the re-check return RAW command output only; the script compares strings and decides every boolean
// Strings are the text the
// command printed ("" when it printed nothing); the symbolic-ref exit code is the integer from `echo $?`.
const RESOLVE = { type: 'object', properties: {
  head_sha: { type: 'string' }, base_sha: { type: 'string' }, repo_root: { type: 'string' }, repo_physical: { type: 'string' }, git_dir: { type: 'string' }, git_common_dir: { type: 'string' },
  worktree_head: { type: 'string' }, worktree_status: { type: 'string' }, worktree_symbolic_ref: { type: 'string' }, worktree_symbolic_ref_exit: { type: 'integer' },
  utc_date: { type: 'string' },
}, required: ['head_sha'] }
const RECHECK = { type: 'object', properties: { branch_head: { type: 'string' }, worktree_head: { type: 'string' }, worktree_status: { type: 'string' } }, required: ['branch_head', 'worktree_head', 'worktree_status'] }
const FINDINGS = { type: 'object', properties: { findings: { type: 'array', items: { type: 'object', properties: { where: { type: 'string' }, scenario: { type: 'string' }, severity: { type: 'string', enum: ['high', 'medium', 'low'] } }, required: ['where', 'scenario', 'severity'] } } }, required: ['findings'] }
const REFUTE = { type: 'object', properties: { refuted: { type: 'boolean' }, reason: { type: 'string' }, evidence_kind: { type: 'string', enum: ['reproduction', 'file_line', 'none'] }, evidence: { type: 'string' }, contradicts: { type: 'string' } }, required: ['refuted', 'reason', 'evidence_kind', 'evidence', 'contradicts'] }
// Rules every hunter and refuter gets, in both review modes.
const CONTEXT =
  (repo
    ? `Repository: ${repo} (main checkout; do not modify it). The code under review is checked out, detached at exactly ${expect_sha}, in ${worktree}; work there. ` +
      `Its venv is already synced: never run uv sync, uv lock, uv add or pip; run tests from ${worktree} with \`uv run --no-sync pytest ...\`. ` +
      `Do not edit or create tracked files there and do not commit. Do not touch any other worktree. `   // what to diff: REVIEW_DIFF, below
    : '') +
  'Search only the worktree under review; never start a filesystem search from /, $HOME or ~. ' +
  'Use only the tools installed in this sandbox; do not install a missing tool. Scratch files stay in the worktree ignored scratch directory. ' +
  'Use the sandbox resource limits and finite timeouts for tests, probes and backtests; an unavailable bound is UNVERIFIED, not permission for an unbounded run. Every timer needs a stop time. ' +
  'Respect the sandbox and its guards; a blocked tool call is not itself a defect in the code. ' +
  'Never contact trading endpoints or read broker credentials. Skip a test that needs them and report it as UNVERIFIED. '
// The lane's own notes go to hunters only: refuters must judge independently of the lane under review.
const HUNT_NOTES = notes ? `The implementing lane's own notes (claims to check, not facts): ${notes}. ` : ''

// Pin the target first so hunters and the report refer to the same commit.
phase('Resolve')
const trim = x => (typeof x === 'string' ? x.trim() : '')
const raw = await agent(repo
  ? `Resolve the review target "${target}" in the git repository at ${repo}. Do not modify anything. Return the RAW text each command printed, exactly, with "" when it printed nothing; do not interpret, summarise or judge anything.\n` +
    `- head_sha: the output of git -C ${repo} rev-parse --verify --quiet 'refs/heads/${target}^{commit}' ("" if it printed nothing).\n` +
    `- base_sha: the output of git -C ${repo} merge-base '${base || 'main'}' 'refs/heads/${target}' ("" if it printed nothing or failed): the commit the reviewers' git diff ${base || 'main'}...HEAD starts from.\n` +
    `- repo_root: the output of git -C ${repo} rev-parse --show-toplevel. repo_physical: the output of cd ${repo} && pwd -P.\n` +
    `- git_dir and git_common_dir: the two lines printed by git -C ${repo} rev-parse --path-format=absolute --git-dir --git-common-dir, first line then second line.\n` +
    `- worktree_head: the output of git -C ${worktree} rev-parse HEAD. worktree_status: the whole output of git -C ${worktree} status --porcelain ("" when clean).\n` +
    `- worktree_symbolic_ref: the stdout of git -C ${worktree} symbolic-ref -q HEAD, and worktree_symbolic_ref_exit: that command's exit code as an integer (run it, then echo $?).\n` +
    '- utc_date: the output of date -u +%Y-%m-%d.'
  :`Resolve the review target "${target}" to one exact commit in the current repository. Do not modify anything. Return the RAW text each command printed, exactly, with "" when it printed nothing; do not interpret or judge anything.\n` +
    `- head_sha: for a branch, tag or commit the output of git rev-parse --verify --quiet '${target}^{commit}'; for a PR number the output of gh pr view <n> --json headRefOid (the oid); for a path or a free-text description "".\n` +
    `- base_sha: when head_sha is not "", the output of git merge-base '${base || 'main'}' <that head_sha> ("" if it printed nothing or failed): the commit the reviewers' git diff ${base || 'main'}...HEAD starts from. Otherwise "".\n` +
    '- repo_root: the output of git rev-parse --show-toplevel.\n' +
    '- utc_date: the output of date -u +%Y-%m-%d.',
  { label: 'resolve', phase: 'Resolve', schema: RESOLVE, effort: EFFORT.resolve, model: MODEL.resolve })
// Every gate fact is decided here from the raw strings.
const head = trim(raw && raw.head_sha)
const isRef = head !== ''
const baseRaw = trim(raw && raw.base_sha)
const repoRoot = trim(raw && raw.repo_root)
// Date comes from args or the resolver; the workflow script has no clock.
const utcRaw = trim(raw && raw.utc_date)
const date = A.date ? String(A.date) : (DATE_RE.test(utcRaw) ? utcRaw : null)
const isMainCheckout = !!raw && trim(raw.git_dir) !== '' && trim(raw.git_dir) === trim(raw.git_common_dir) // they differ in a linked worktree
const worktreeClean = !!raw && typeof raw.worktree_status === 'string' && (raw.worktree_status.trim() === '' || raw.worktree_status.trim() === '(Bash completed with no output)')
const worktreeDetached = !!raw && typeof raw.worktree_symbolic_ref === 'string' && raw.worktree_symbolic_ref.trim() === '' &&
  Number.isInteger(raw.worktree_symbolic_ref_exit) && raw.worktree_symbolic_ref_exit !== 0 // symbolic-ref -q HEAD prints nothing and fails on a detached HEAD
let bad = null
if (!raw) bad = 'resolve agent returned no result'
else if (isRef && !SHA_RE.test(head)) bad = `target resolved to an invalid head_sha "${head}"`
else if (baseRaw !== '' && !SHA_RE.test(baseRaw)) bad = `the review base resolved to an invalid base_sha "${baseRaw}"`
// The source gate credited no risk-path coverage without a base. Keep that prerequisite in the report itself.
else if (isRef && !baseRaw) bad = 'review base could not be resolved; branch-diff coverage is unverified'
else if (isRef && !date) bad = `no usable date: pass args.date, or the resolver must print date -u +%Y-%m-%d (got "${utcRaw.slice(0, 40)}"); a recorded verdict is never undated`
else if (repo && (!isRef || head !== expect_sha || trim(raw.worktree_head) !== expect_sha))
  bad = `branch head ${head} / verify worktree ${trim(raw.worktree_head)} != expected ${expect_sha} (the lane moved or the worktree is wrong)`
else if (repo && (!isMainCheckout || !repoRoot || repoRoot !== trim(raw.repo_physical)))
  bad = `repo ${repo} must be the main checkout at its repository root (root ${repoRoot}, physical ${trim(raw.repo_physical)}, git-dir ${trim(raw.git_dir)}, common-dir ${trim(raw.git_common_dir)})`
else if (repo && (!worktreeClean || !worktreeDetached))
  bad = `verify worktree ${worktree} must be clean and detached at ${expect_sha} (status ${JSON.stringify(raw.worktree_status)}, symbolic-ref ${JSON.stringify(raw.worktree_symbolic_ref)} exit ${raw.worktree_symbolic_ref_exit})`
else if (!repo && expect_sha && head !== expect_sha) bad = `branch head ${head} != expected ${expect_sha} (the branch moved)`
if (bad) {
  log(`adversarial-verify: ${bad}; verdict INCONCLUSIVE`)
  return { workflow_version: WORKFLOW_VERSION, target, head_sha: null, verdict: 'INCONCLUSIVE', reason: bad, confirmed: [], unverified: [], failed_lenses: [], verdict_file: null }
}
const sha = isRef ? head : null
// Keep the reviewed base beside head_sha so the report identifies the entire diff.
const baseSha = sha && baseRaw !== '' ? baseRaw : null
if (sha && !baseSha) log('adversarial-verify: no base_sha resolved; the report claims no branch-diff coverage')
// (Declared after baseSha, which the verdict records and the subject names.)
const subject = !sha ? target
  : baseSha ? `${target} at commit ${sha} (review the whole diff from base ${baseSha} to this commit${base ? `, the base resolved from ${base}` : ''})`
  : `${target} at commit ${sha} (review exactly this commit${base ? `, diffed against ${base}` : ''})`
// Every hunter and refuter receives the same literal head/base diff and reviews all of it.
const REVIEW_DIFF = baseSha
  ? `The change under review is exactly \`git ${repo ? `-C ${worktree} ` : ''}diff ${baseSha} ${sha}\` (base ${baseSha}, head ${sha}): review that WHOLE diff, every file in it and not only the head commit, and check each risk-critical file in it. `
  // No base resolved: preserve the source's hint without claiming a pinned diff.
  : repo ? `See what changed with \`git -C ${worktree} diff ${base || 'main'}...HEAD\`. ` : ''

// Fail-closed refutation rule. A refutation counts only when its evidence passes the checks
// below; a refuted=true that fails them counts as upholding the finding, so a lazy refuter cannot clear a finding
// by waving at it. A dead refuter is neither a refutation nor a confirmation. A finding is killed only by 2 counted
// refutations and confirmed only by 2 non-refutations (a majority of the 3-panel either way). Anything in between
// is unverified, and an unverified finding makes the verdict INCONCLUSIVE.
// LIMIT: these are checks on the SHAPE of the evidence (script code has no filesystem access, so it cannot open
// the cited file or re-run the command). A well-formed citation of a line that does not exist (guard.py:99999)
// or a command whose output was invented passes. That is why refuters of high and medium findings run on opus;
// the gate rejects lazy refutations, it does not prove a refutation true.
const CITE = /(?:^|[^\w./:@-])((?:[\w.-]+\/)*[\w-]+\.[A-Za-z][A-Za-z0-9]{0,7}):(\d+)\b/g
const HOST_SUFFIX = /^(com|org|net|io|dev|app|local|localhost|internal|test|example|co|ai|us|uk|de)$/i
const PLACEHOLDER = /^\s*(n\/?a|n\.a\.|none|nil|null|tbd|todo|unknown|-+|—+|\.+|cannot happen|can't happen|reasoned|looks fine|fine|ok)\s*[.!]?\s*$/i
const NOT_RUN = /\b(did not|didn't|never|without|not|no)\s+(actually\s+)?(run|ran|execute|executed|running)\b|\bI\s+(only\s+)?(read|reasoned|looked at|reviewed|checked the code)\b/i
const COMMAND = /`[^`\n]*[A-Za-z][^`\n]{2,}`|^\s*\$\s+\S/m
const OBSERVED = /\bexit(?:ed)?(?:\s+(?:status|code))?\s*[:=]?\s*-?\d+|\brc\s*=\s*-?\d+|\b(?:output|stdout|stderr|printed|prints|returned|returns|showed|shows|traceback)\b/i
// A green suite never refutes a finding: it is the state the hunter already judged insufficient or wrong.
const GREEN_SUITE = /\b\d+\s+(?:tests?\s+|scenarios?\s+|checks?\s+)?passed\b|\ball\s+(?:\d+\s+)?(?:tests?|scenarios?|checks?)\s+pass|\bsuite\s+(?:is\s+|was\s+)?green|\b0\s+fail(?:ed|ures?)\b/i
const STOP = new Set(['that', 'this', 'with', 'from', 'have', 'does', 'when', 'then', 'there', 'which', 'after', 'before', 'because', 'cannot', 'would', 'could', 'should', 'line', 'code', 'ran', 'not', 'the', 'and', 'for', 'are', 'was', 'its'])
const str = x => (typeof x === 'string' ? x.trim() : '')
const words = t => t.toLowerCase().match(/[a-z0-9]+/g) || []
const cites = t => [...t.matchAll(CITE)]
  .map(m => ({ path: m[1], line: m[2] }))
  .filter(c => c.path.includes('/') || !HOST_SUFFIX.test(c.path.split('.').pop()))
const sameLine = (a, b) => a.line === b.line && (a.path.endsWith(b.path) || b.path.endsWith(a.path))
function provenRefutation(v, f) {
  if (!v || v.refuted !== true) return false
  const e = str(v.evidence)
  if (!e || PLACEHOLDER.test(e)) return false
  // What the evidence contradicts must be said, and must be about this finding (shares a content word with it).
  const c = str(v.contradicts)
  const claim = new Set(words(`${f.scenario || ''} ${f.where || ''}`).filter(w => w.length >= 4 && !STOP.has(w)))
  if (words(c).length < 3 || !words(c).some(w => claim.has(w))) return false
  if (v.evidence_kind === 'file_line') {
    const found = cites(e)
    const own = cites(str(f.where))
    // A cite of the finding's own where proves nothing; it needs a different line, plus a sentence on what that line does.
    if (!found.some(x => !own.some(o => sameLine(x, o)))) return false
    return words(e.replace(CITE, ' ')).length >= 3
  }
  if (v.evidence_kind === 'reproduction') {
    if (NOT_RUN.test(e) || GREEN_SUITE.test(e)) return false
    return COMMAND.test(e) && OBSERVED.test(e)
  }
  return false
}
function judge(f, votes) {
  const live = votes.filter(Boolean)
  const refuted = live.filter(v => provenRefutation(v, f)).length
  const upheld = live.length - refuted
  if (refuted >= 2) return { ...f, status: 'refuted' }
  if (upheld >= 2) return { ...f, status: 'confirmed' }
  return { ...f, status: 'unverified', unverified: true, votes: { refuted, upheld, missing: votes.length - live.length } }
}
const refute = f => parallel([0, 1, 2].map(i => () => agent(
  `${CONTEXT}${REVIEW_DIFF}\nTry to REFUTE this claimed defect in ${subject} (refuter #${i + 1}; check the code and run what you need).\n` +
  'Proof rule: you may set refuted=true ONLY with proof that contradicts the claim. Either (a) evidence_kind="reproduction": evidence is the exact command you ran in backticks AND what it printed or its exit status, and that output must show the claimed failure does NOT happen (a passing suite or an "N passed" line proves nothing and never refutes a finding about missing or weak tests); or ' +
  '(b) evidence_kind="file_line" (a cited file:line): evidence is path/to/file.ext:LINE, a line other than the one the finding names, and what that line does. A citation of a line you did not open, or output you did not see, is fabrication and invalidates the review. ' +
  'In both cases put in contradicts, in your own words, which part of the claim the evidence contradicts. ' +
  'Anything else (a feeling that it "cannot happen", an argument without a run or a line, "n/a") keeps the finding: set refuted=false and evidence_kind="none", and say in reason what you could not rule out. ' +
  'When in doubt, keep the finding.\n' +
  `Where: ${f.where}\nScenario: ${f.scenario}`,
  { label: `refute${i + 1}:${f.where}`.slice(0, 60), phase: 'Refute', schema: REFUTE, effort: f.severity === 'low' ? EFFORT.refuteLow : EFFORT.refuteGate, model: f.severity === 'low' ? MODEL.refuteLow : MODEL.refuteGate })))
  .then(votes => judge(f, votes))

phase('Hunt')
const perLens = await pipeline(
  lenses,
  (lens, _, i) => agent(
    `${CONTEXT}${REVIEW_DIFF}${HUNT_NOTES}\nThis is defensive verification of our own code, in our own repository, before we merge it: you are checking that our guards, sandboxes and containment hold, ` +
    'using only tests and read-only probes inside the sandbox, never building an attack on anything outside this repository.\n' +
    `Target: ${subject}\nLens: ${lens}\nFind real defects only, each with a concrete failure scenario and path:line. Run tests/probes to support claims.`,
    { label: `hunt:${i + 1}:${lens.split(/[^A-Za-z0-9-]/)[0]}`, phase: 'Hunt', schema: FINDINGS, effort: EFFORT.hunt, model: MODEL.hunt }),
  (r, lens) => (r && Array.isArray(r.findings))
    ? { lens, findings: r.findings }
    : { lens, hunter_failed: true },
)
// Normalise by index: an item the pipeline dropped (stage threw, or a null short-circuited it) is a failed lens.
const lensResults = perLens.map((x, i) => x || { lens: lenses[i], hunter_failed: true })
const failed = new Set(lensResults.filter(x => x.hunter_failed).map(x => x.lens))
const order = { high: 0, medium: 1, low: 2 }
const severity = value => {
  const normalized = str(value).toLowerCase()
  return Object.hasOwn(order, normalized) ? normalized : 'high'
}
// Exact claims only: no semantic judgment and no additional model call. Keep case
// and internal whitespace, since they may describe different identifiers or code.
const groups = new Map(), invalid_findings = []
let input_count = 0, valid_count = 0
for (const [lens_index, entry] of lensResults.entries()) {
  for (const [finding_index, finding] of (entry.findings || []).entries()) {
    input_count++
    const source = { lens: entry.lens, lens_index, finding_index, finding }
    if (!finding || !str(finding.where) || !str(finding.scenario)) {
      failed.add(entry.lens)
      invalid_findings.push(source)
      continue
    }
    valid_count++
    const key = JSON.stringify([str(finding.where), str(finding.scenario)])
    const existing = groups.get(key)
    const level = severity(finding.severity)
    if (existing) {
      existing.sources.push(source)
      if (order[level] < order[existing.severity]) existing.severity = level
    } else groups.set(key, { ...finding, severity: level, sources: [source] })
  }
}
const failed_lenses = [...failed]
if (failed_lenses.length) log(`adversarial-verify: ${failed_lenses.length} hunter(s) failed or returned malformed findings: ${failed_lenses.join(' | ')}`)
phase('Refute')
const unique = [...groups.values()]
const reviewed = await parallel(unique.map(finding => () => refute(finding)))
// A throwing or missing group review never removes its claim from the verdict.
const all = unique.map((finding, i) => reviewed[i] || { ...finding, status: 'unverified', unverified: true, refute_failed: true })
const bySeverity = (a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3)
const confirmed = all.filter(f => f.status === 'confirmed').sort(bySeverity)
const unverified = all.filter(f => f.status === 'unverified').sort(bySeverity)
const refuted = all.filter(f => f.status === 'refuted')
// Preserve refuted_count's original-claim meaning; expose the new group count separately.
const refuted_count = refuted.reduce((count, finding) => count + finding.sources.length, 0)
const deduplication = {
  input_count, valid_count, unique_count: unique.length,
  duplicate_count: valid_count - unique.length,
  refuter_calls_avoided: 3 * (valid_count - unique.length),
  invalid_findings,
  // Keep every source, including claims that were refuted, for later audit.
  groups: all.map(({ where, scenario, severity, status, sources }) => ({ where, scenario, severity, status, sources })),
}
if (unverified.length) log(`adversarial-verify: ${unverified.length} finding(s) unverified (refuters missing or split)`)
// A confirmed high finding is a FAIL whatever else happened; otherwise any gap in coverage is INCONCLUSIVE.
const verdict = confirmed.some(f => f.severity === 'high') ? 'FAIL'
  : (failed_lenses.length || unverified.length) ? 'INCONCLUSIVE'
    : confirmed.length ? 'PASS-WITH-NITS' : 'PASS'
const result = { workflow_version: WORKFLOW_VERSION, target, head_sha: sha, verdict, confirmed, unverified, failed_lenses, refuted_count, unique_refuted_count: refuted.length, deduplication }
if (!sha) return { ...result, verdict_file: null, note: 'target is not a git ref; no verdict file written' }

phase('Report')
// Repo mode: the freeze must still hold when the verdict is written, or the verdict would attest to code no one
// reviewed (a checkout or an uncommitted edit in the worktree during the hunt). A dead re-check fails closed.
if (repo) {
  const again = await agent(
    `Read-only check, change nothing. Run: git -C ${repo} rev-parse --verify --quiet 'refs/heads/${target}^{commit}' (return branch_head), ` +
    `git -C ${worktree} rev-parse HEAD (return worktree_head) and git -C ${worktree} status --porcelain (return worktree_status: the whole output, "" when it printed nothing; do not judge it). Return the raw text each command printed.`,
    { label: 'recheck', phase: 'Report', schema: RECHECK, effort: EFFORT.recheck, model: MODEL.recheck })
  const againClean = !!again && typeof again.worktree_status === 'string' && (again.worktree_status.trim() === '' || again.worktree_status.trim() === '(Bash completed with no output)')
  if (!again || trim(again.branch_head) !== sha || trim(again.worktree_head) !== sha || !againClean) {
    const reason = again ? `freeze broken during review: branch ${trim(again.branch_head)}, worktree ${trim(again.worktree_head)}, status ${JSON.stringify(again.worktree_status)}` : 'recheck agent returned nothing'
    log(`adversarial-verify: ${reason}; verdict INCONCLUSIVE, no verdict file`)
    return { ...result, verdict: 'INCONCLUSIVE', reason, verdict_file: null }
  }
}
return {
  ...result, base_sha: baseSha, date, lenses, verdict_file: null, report_only: true,
  note: 'On-demand review report only; no verdict recorder or required check. The live branch requires two-family review on its exact SHA under docs/adr/0020-live-lane.md. This report grants no promotion or deployment authority.',
}
