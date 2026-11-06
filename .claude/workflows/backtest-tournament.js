export const meta = {
  name: 'backtest-tournament',
  description: 'Generate strategy variants -> backtest in worktrees -> ADR-0019 validation over the one trial ledger -> rank -> skeptic -> report. No paper or live deployment',
  whenToUse: 'Explore a trading hypothesis in Sextant. args: {hypothesis: string, universe: string, period: string, variants?: number (2-8), date?: "YYYY-MM-DD"}. Missing Phase 4 runners, catalog, TrialLog writer or validators are reported as prerequisites, never invented',
  phases: [
    { title: 'Generate', detail: 'architect proposes distinct, testable variants' },
    { title: 'Backtest', detail: 'use the installed runner/catalog and canonical TrialLog writer; otherwise report missing prerequisites' },
    { title: 'Validate', detail: 'all ADR-0019 gates per variant, with cumulative trial provenance' },
    { title: 'Select', detail: 'rank by complete validation gates, then deflated Sharpe' },
    { title: 'Review', detail: 'skeptic per ranked variant on its exact commit' },
    { title: 'Report', detail: 'findings, research candidates, all attempted variants and missing prerequisites; deploy nothing' },
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
const MODEL = { architect: 'opus', backtest: 'sonnet', gates: 'sonnet', skeptic: 'opus' }
// Preserve the source effort levels for the retained jobs.
const EFFORT = { architect: 'xhigh', backtest: 'xhigh', gates: 'max', skeptic: 'high' }

const h = args && args.hypothesis
if (!h || !args.universe || !args.period) throw new Error('pass args: {hypothesis, universe, period, variants?, date?}')
const unknown = Object.keys(args).filter(k => !['hypothesis', 'universe', 'period', 'variants', 'date'].includes(k))
if (unknown.length) throw new Error(`unknown report-only arguments: ${unknown.join(', ')}`)
const n = Math.min(Math.max((args && args.variants) || 4, 2), 8)
const date = args.date || null
const SHA_RE = /^[0-9a-f]{40}$/

const VARIANTS = { type: 'object', properties: { variants: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, idea: { type: 'string' }, params: { type: 'string' }, why: { type: 'string' } }, required: ['id', 'idea', 'params', 'why'] } } }, required: ['variants'] }
const PREREQUISITES = { prerequisites_met: { type: 'boolean' }, unverified: { type: 'array', items: { type: 'string' } } }
const BT = { type: 'object', properties: { branch: { type: 'string' }, head_sha: { type: 'string' }, trials: { type: 'number' }, oos_sharpe: { type: 'number' }, report_path: { type: 'string' }, notes: { type: 'string' }, upstream_line: { type: 'string' }, ...PREREQUISITES }, required: ['branch', 'head_sha', 'trials', 'report_path', 'upstream_line', 'prerequisites_met', 'unverified'] }
const GATES = { type: 'object', properties: { dsr_prob: { type: 'number' }, pbo: { type: 'number' }, wf_positive_folds: { type: 'number' }, cost_stress_ok: { type: 'boolean' }, all_pass: { type: 'boolean' }, report_path: { type: 'string' }, ...PREREQUISITES }, required: ['all_pass', 'report_path', 'prerequisites_met', 'unverified'] }
const SKEPTIC = { type: 'object', properties: { verdict: { type: 'string', enum: ['PASS', 'PASS-WITH-NITS', 'FAIL', 'INCONCLUSIVE'] }, head_sha: { type: 'string' }, findings: { type: 'array', items: { type: 'string' } } }, required: ['verdict', 'head_sha', 'findings'] }

// The two-line rule of the clause: 'checked' names the upstream built from, 'none' says none exists (the skeptic then verifies it), anything else
// (prose, an unfilled placeholder) is 'missing' and the variant goes no further.
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

const empty = status => ({ hypothesis: h, status, ranking: [], leader: null, leader_review: null, candidates: [], rejected: [], waiting_for: [], report_only: true })

phase('Generate')
const gen = await agent(
  `Hypothesis: ${h}\nUniverse: ${args.universe}\nPeriod: ${args.period}\n` +
  `Propose ${n} materially different, testable strategy variants (different signal construction, horizon or risk logic — not parameter tweaks). ` +
  'Ground each in a cited paper or pinned upstream strategy example in docs/manifest.md. Read docs/adr/0019-validation-and-merit.md. Freeze the hypothesis, estimand, windows, costs, parameters and multiplicity before results. Every configuration attempted counts in the one cumulative TrialLog, including failed, rejected and pruned trials.\n\n' + UPSTREAM_FIRST,
  { label: 'architect:variants', phase: 'Generate', schema: VARIANTS, effort: EFFORT.architect, model: MODEL.architect })
if (!gen) { log('backtest-tournament: the architect returned nothing'); return empty('architect-failed') }
const variants = gen.variants.slice(0, n)
if (gen.variants.length > n) log(`backtest-tournament: dropped ${gen.variants.length - n} variant(s) beyond the requested ${n}`)
if (!variants.length) return empty('no variants')
// Adopt research-plan-build's duplicate-ID check before identity-keyed work and reviews start.
if (new Set(variants.map(v => v.id)).size !== variants.length) return { ...empty('invalid variants'), reason: 'variant ids must be unique' }

const results = await pipeline(
  variants,
  v => agent(
    `In Sextant, implement variant ${v.id} (${v.idea}; params ${v.params}) from the manifest's pinned NautilusTrader examples. ` +
    `Change only src/sextant/strategies/${v.id}/ and its tests; write evidence under reports/validation/${v.id}/${date || '<UTC-date>'}/. ` +
    `Use the installed backtest runner and read-only catalog on ${args.universe} for ${args.period}, with identical fills, costs, seed, incumbent and hold-flat controls (docs/adr/0019-validation-and-merit.md). ` +
    'Check prerequisites BEFORE any trial: a compatible strategy runner, point-in-time catalog and the canonical TrialLog writer for the ledger branch. The current EMA thin slice is not that general runner. Vectorbt sweeps await its manifest installation; do not install, emulate or replace missing code. ' +
    'Use only the existing single TrialLog writer: it must record EVERY attempted configuration before evaluation, including failures/rejections/pruning, with MODELED provenance and frozen cumulative N/effective-N. Never start a trial without that writer, create a per-variant trial ledger, reset history, or write the ledger branch directly from this worktree. ' +
    'If any prerequisite is missing, run no trials and return prerequisites_met=false, unverified naming what is missing, trials=0 and empty branch/head_sha when no strategy commit exists. Otherwise commit the variant on its own branch and return its full head_sha, prerequisites_met=true and an empty unverified array only when every required input was verified. No broker endpoints, credentials or deployment. ' +
    'Return your upstream line in upstream_line, and put the upstream references (repo@tag:path:line or docs URL with the access date, the pins, every deviation with its reason, what is UNVERIFIED) in the backtest report at report_path.\n\n' + UPSTREAM_FIRST,
    { label: `bt:${v.id}`, phase: 'Backtest', isolation: 'worktree', schema: BT, effort: EFFORT.backtest, model: MODEL.backtest }),
  (bt, v) => bt && upstreamWord(bt.upstream_line) === 'checked' && bt.prerequisites_met === true && bt.unverified.length === 0 && SHA_RE.test(bt.head_sha)
    ? agent(
      `Validate variant ${v.id} on branch ${bt.branch} at exact SHA ${bt.head_sha}; trials recorded: ${bt.trials}; report ${bt.report_path}. ` +
      'Read docs/adr/0019-validation-and-merit.md and use its installed contract producers and thresholds, with skfolio walk-forward/CPCV (purge/embargo), DSR/PSR/MinTRL, CSCV PBO, paired incumbent AND hold-flat adoption bounds, dependence/multiplicity corrections, cost stress, robustness and the untouched holdout. Read the same cumulative TrialLog on ledger, including all arms, failures and pruned attempts, with each inference\'s frozen N/effective-N snapshot and separate provenance tiers. Never pool tiers or silently drop trials/returns. ' +
      'Missing validators, fold/path contracts, catalog/feed fidelity, cumulative trial provenance or holdout evidence mean prerequisites_met=false and all_pass=false; list every missing item in unverified. Do not write substitute validators. A thin-slice replay is not statistical or prospective merit. Report all ADR gates and exact artifact hashes under reports/validation/<strategy>/<UTC-date>/. Statistical failure never blocks paper operation and never grants live authority. No deployment or promotion.',
      { label: `gates:${v.id}`, phase: 'Validate', schema: GATES, effort: EFFORT.gates, model: MODEL.gates }).then(g => ({ variant: v, bt, gates: g }))
    : { variant: v, bt, gates: null },
)
// Normalise by index: a failed pipeline slot remains a visible attempted variant.
const entries = variants.map((variant, i) => results[i] || { variant, bt: null, gates: null })
const rejected = []
const waiting_for = []
for (const e of entries) {
  const missing = !e.bt ? ['backtest agent returned nothing']
    : upstreamWord(e.bt.upstream_line) !== 'checked' ? ['backtest agent reported no adopted upstream source; no validation run']
      : !e.bt.prerequisites_met || e.bt.unverified.length ? e.bt.unverified.length ? e.bt.unverified : ['backtest prerequisites unverified']
        : !SHA_RE.test(e.bt.head_sha) ? ['backtest agent reported no valid full head_sha']
          : !e.gates ? ['validation agent returned nothing']
            : !e.gates.prerequisites_met || e.gates.unverified.length ? e.gates.unverified.length ? e.gates.unverified : ['validation prerequisites unverified'] : []
  if (missing.length) {
    waiting_for.push({ id: e.variant.id, prerequisites: missing })
    rejected.push({ id: e.variant.id, reason: missing.join('; ') })
  }
}

phase('Select')
const ok = entries.filter(e => e.bt && e.gates && e.gates.prerequisites_met === true && e.gates.unverified.length === 0)
// Preserve the source ranking: gates first, then deflated Sharpe. This ranks research evidence only.
const ranked = ok.slice().sort((a, b) => (Number(b.gates.all_pass) - Number(a.gates.all_pass)) || ((b.gates.dsr_prob || 0) - (a.gates.dsr_prob || 0)))
const passing = ranked.filter(r => r.gates.all_pass)
log(`${passing.length}/${ok.length} variants passed all ADR-0019 gates`)
const leader = passing[0] || null

phase('Review')
const reviews = new Map()
const review = r => agent(
  `Adversarially review strategy variant ${r.variant.id} on branch ${r.bt.branch} at exact SHA ${r.bt.head_sha} (gate report ${r.gates.report_path}; backtest report ${r.bt.report_path}). ` +
  'Resolve the branch before and after review; if it differs from that SHA, return INCONCLUSIVE. Read docs/adr/0019-validation-and-merit.md and check every gate, frozen evidence and the one cumulative TrialLog. Hunt look-ahead, survivorship, snooping, underestimated costs and replay/paper divergence. Missing code or evidence is UNVERIFIED. ' +
  `The backtest agent reported this upstream line: ${r.bt.upstream_line}. Verify the pinned source and every deviation. ` +
  `The variant may change only src/sextant/strategies/${r.variant.id}/ and its tests; report artifacts are allowed under reports/validation/. FAIL if its tracked diff changes risk, execution, adapters or configuration. ` +
  'Return the exact reviewed commit as head_sha and PASS, PASS-WITH-NITS, FAIL or INCONCLUSIVE. This is a research report, never authority to deploy or promote.\n\n' + UPSTREAM_FIRST,
  { label: `skeptic:${r.variant.id}`, phase: 'Review', schema: SKEPTIC, effort: EFFORT.skeptic, model: MODEL.skeptic })
// Preserve the source's dead-skeptic normalization and move its deployment-time identity check here.
const normalize = (v, expected) => !v ? { verdict: 'INCONCLUSIVE', head_sha: null, findings: [], missing: true }
  : !SHA_RE.test(v.head_sha) || v.head_sha !== expected ? { ...v, verdict: 'INCONCLUSIVE', invalid: true, findings: [...v.findings, 'skeptic head_sha does not match the backtest commit'] }
    : v
const reviewed = await parallel(ranked.map(r => () => review(r)))
ranked.forEach((r, i) => {
  const v = normalize(reviewed[i], r.bt.head_sha)
  reviews.set(r.variant.id, v)
  if (v.verdict !== 'PASS' && v.verdict !== 'PASS-WITH-NITS') rejected.push({ id: r.variant.id, reason: `skeptic ${v.missing ? 'returned nothing -> INCONCLUSIVE' : v.verdict}` })
})
const candidates = passing.filter(r => ['PASS', 'PASS-WITH-NITS'].includes(reviews.get(r.variant.id).verdict)).map(r => ({ id: r.variant.id, branch: r.bt.branch, head_sha: r.bt.head_sha }))
const degraded = waiting_for.length > 0 || [...reviews.values()].some(v => v.missing || v.invalid || v.verdict === 'INCONCLUSIVE')

phase('Report')
return {
  hypothesis: h,
  status: degraded ? 'degraded' : 'ok',
  date,
  report_only: true,
  ranking: ranked.map(r => ({ id: r.variant.id, branch: r.bt.branch, head_sha: r.bt.head_sha, dsr_prob: r.gates.dsr_prob, pbo: r.gates.pbo, all_pass: r.gates.all_pass, report: r.gates.report_path, upstream_line: r.bt.upstream_line, skeptic: reviews.get(r.variant.id).verdict })),
  attempts: entries.map(e => ({ variant: e.variant, backtest: e.bt, gates: e.gates })),
  leader: leader ? leader.variant.id : null,
  leader_review: leader ? reviews.get(leader.variant.id) : null,
  candidates,
  rejected,
  waiting_for,
  note: 'Research report only. No merge, paper/live deployment or promotion. Statistical failure does not block paper operation; merit needs ADR-0019 evidence and produces at most a Stage-0 draft. Live additionally requires ADR-0020, including two-family review on its exact SHA. The existing single TrialLog writer owns every attempted configuration on ledger.',
}
