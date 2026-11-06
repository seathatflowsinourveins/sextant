// Adapt the pinned upstream run-scenarios.mjs null/fault sweeps and scenario fixtures
// to Sextant's report-only contracts. The runtime is an offline test double, not Claude Code.
import assert from 'node:assert/strict'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { runWorkflow, route, withNulls, allNull } from './workflow-runtime.mjs'
import { check } from './workflow-models.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const SHA = 'a'.repeat(40), BASE = 'b'.repeat(40)
const UP = { upstream_line: 'upstream checked: vendor/example@v1:examples/strategy.py', upstream_references: ['vendor/example@v1:examples/strategy.py'], deviations: [] }
const task = { id: 'a', title: 'first', spec: 'one', acceptance: ['tested'], depends_on: [] }
const RPB_ARGS = { task: 'test', slug: 'test', cross_model: true }
const BT_ARGS = { hypothesis: 'drift', universe: 'SP500', period: '2018-2025', variants: 2 }
const AV_ARGS = { target: 'topic', expect_sha: SHA, date: '2026-11-06' }

async function run(name, args, respond, nullMode = 'pass') {
  const out = await runWorkflow(join(ROOT, '.claude', 'workflows', `${name}.js`), { args, respond, nullMode })
  assert.deepEqual(out.harness, [], 'the fixtures and calls must obey the runtime contract')
  assert.ifError(out.error)
  return out
}

const rpb = route([
  [/^research:/, { summary: 'checked', sources: ['vendor/example@v1'], open_questions: [] }],
  ['architect', { tasks: [task, { ...task, id: 'b', depends_on: ['a'] }], adr_path: 'docs/adr/proposed.md', research_note_path: 'docs/research/test.md', ...UP }],
  [/^impl:/, c => ({ branch: `rpb/test-${c.label.slice(5)}`, summary: 'built', tests_passed: true, unverified: [], mechanism_changed: true, ...UP })],
  [/^skeptic:/, { verdict: 'PASS', findings: [] }],
  [/^integrate:/, c => ({ branch: 'rpb/test', head_sha: SHA, merged: [`rpb/test-${c.label.endsWith('1') ? 'a' : 'b'}`], conflicts: [], tests_passed: true, advanced: true })],
  ['cross-family-review', { ran: true, verdict: 'PASS', head_sha: SHA, findings: [] }],
])
const av = route([
  ['resolve', { head_sha: SHA, base_sha: BASE, repo_root: '/review-repo', repo_physical: '/review-repo', git_dir: '/review-repo/.git', git_common_dir: '/review-repo/.git', worktree_head: SHA, worktree_status: '', worktree_symbolic_ref: '', worktree_symbolic_ref_exit: 1, utc_date: '2026-11-06' }],
  [/^hunt:/, { findings: [] }],
  ['recheck', { branch_head: SHA, worktree_head: SHA, worktree_status: '' }],
])
const bt = route([
  ['architect:variants', { variants: ['v1', 'v2'].map(id => ({ id, idea: `idea ${id}`, params: '{}', why: 'paper' })) }],
  [/^bt:/, c => ({ branch: `bt/${c.label.slice(3)}`, head_sha: SHA, trials: 6, oos_sharpe: 1.1, report_path: `reports/validation/${c.label.slice(3)}/backtest.md`, notes: '', ...UP, prerequisites_met: true, unverified: [] })],
  [/^gates:/, c => ({ dsr_prob: 0.97, pbo: 0.04, wf_positive_folds: 0.75, cost_stress_ok: true, all_pass: true, prerequisites_met: true, unverified: [], report_path: `reports/validation/${c.label.slice(6)}/gates.md` })],
  [/^skeptic:/, { verdict: 'PASS', head_sha: SHA, findings: [] }],
])

for (const nullMode of ['pass', 'drop']) {
  for (const [name, args, respond, green] of [
    ['research-plan-build', RPB_ARGS, rpb, r => r.status === 'PASS'],
    ['adversarial-verify', AV_ARGS, av, r => r.verdict === 'PASS'],
    ['backtest-tournament', BT_ARGS, bt, r => r.status === 'ok' && r.candidates.length === 2],
  ]) {
    test(`${name} [${nullMode}]: all agents dead never passes`, async () => {
      assert.equal(green((await run(name, args, allNull, nullMode)).result), false)
    })
    test(`${name} [${nullMode}]: green path and each required agent dying`, async () => {
      const happy = await run(name, args, respond, nullMode)
      assert.equal(green(happy.result), true)
      for (const call of happy.calls) {
        const failed = await run(name, args, withNulls(respond, [call.key]), nullMode)
        assert.equal(green(failed.result), false, call.key)
      }
    })
  }
}

test('research-plan-build: failed dependencies never build against stubs', async () => {
  const out = await run('research-plan-build', RPB_ARGS, withNulls(rpb, ['impl:a#0']))
  assert.equal(out.result.tasks.find(t => t.id === 'b').status, 'blocked')
  assert.equal(out.calls.some(c => c.label === 'impl:b'), false)
})

test('research-plan-build: a cross-family review of a different SHA never passes', async () => {
  const out = await run('research-plan-build', RPB_ARGS, c => c.label === 'cross-family-review'
    ? { ran: true, verdict: 'PASS', head_sha: BASE, findings: [] } : rpb(c))
  assert.equal(out.result.status, 'INCONCLUSIVE')
})

test('adversarial-verify: exact duplicate findings share three refuters, missing votes stay unknown', async () => {
  const out = await run('adversarial-verify', AV_ARGS, c => c.label.startsWith('hunt:')
    ? { findings: [{ where: 'src/example.py:3', scenario: 'boundary breaks', severity: 'high' }] }
    : c.label.startsWith('refute') ? null : av(c))
  assert.equal(out.result.verdict, 'INCONCLUSIVE')
  assert.equal(out.result.unverified.length, 1)
  assert.equal(out.result.deduplication.unique_count, 1)
  assert.equal(out.calls.filter(c => c.label.startsWith('refute')).length, 3)
  assert.equal(out.result.verdict_file, null)
})

test('adversarial-verify: unproven refutations cannot erase a high finding', async () => {
  const out = await run('adversarial-verify', AV_ARGS, c => c.label.startsWith('hunt:')
    ? { findings: [{ where: 'src/example.py:3', scenario: 'boundary breaks', severity: 'high' }] }
    : c.label.startsWith('refute')
      ? { refuted: true, reason: 'looks fine', evidence_kind: 'none', evidence: 'n/a', contradicts: 'the boundary claim' }
      : av(c))
  assert.equal(out.result.verdict, 'FAIL')
  assert.equal(out.result.confirmed.length, 1)
})

test('adversarial-verify: missing or changed frozen-worktree recheck never passes', async () => {
  const args = { ...AV_ARGS, repo: '/review-repo', worktree: '/review-worktree' }
  for (const answer of [null, { branch_head: BASE, worktree_head: SHA, worktree_status: '' }]) {
    const out = await run('adversarial-verify', args, c => c.label === 'recheck' ? answer : av(c))
    assert.equal(out.result.verdict, 'INCONCLUSIVE')
    assert.equal(out.result.verdict_file, null)
  }
})

test('adversarial-verify: an unresolved requested base cannot pass a branch review', async () => {
  for (const extra of [{}, { repo: '/review-repo', worktree: '/review-worktree' }]) {
    const out = await run('adversarial-verify', { ...AV_ARGS, base: 'missing-base', ...extra }, c => c.label === 'resolve'
      ? { ...av(c), base_sha: '' } : av(c))
    assert.equal(out.result.verdict, 'INCONCLUSIVE')
    assert.equal(out.calls.some(c => c.label.startsWith('hunt:')), false)
    assert.equal(out.result.verdict_file, null)
  }
})

test('backtest-tournament: duplicate IDs cannot reuse another variant review after a dead skeptic', async () => {
  const other = 'c'.repeat(40)
  const out = await run('backtest-tournament', BT_ARGS, c => {
    if (c.label === 'architect:variants') return { variants: [
      { id: 'same', idea: 'one', params: '{}', why: 'paper' },
      { id: 'same', idea: 'two', params: '{}', why: 'paper' },
    ] }
    if (c.label === 'bt:same') return { ...bt(c), branch: c.key.endsWith('#0') ? 'bt/one' : 'bt/two', head_sha: c.key.endsWith('#0') ? SHA : other }
    if (c.label === 'gates:same') return { ...bt(c), dsr_prob: c.key.endsWith('#0') ? 0.99 : 0.98 }
    if (c.label === 'skeptic:same') return c.key.endsWith('#0') ? null : { verdict: 'PASS', head_sha: other, findings: [] }
    return bt(c)
  })
  assert.notEqual(out.result.status, 'ok')
  assert.deepEqual(out.result.candidates, [])
  assert.equal(out.calls.some(c => c.label.startsWith('bt:')), false)
})

test('backtest-tournament: missing TrialLog/validation code blocks results without deployment', async () => {
  const out = await run('backtest-tournament', BT_ARGS, c => c.label.startsWith('bt:')
    ? { ...bt(c), prerequisites_met: false, unverified: ['canonical TrialLog writer missing'] } : bt(c))
  assert.notEqual(out.result.status, 'ok')
  assert.deepEqual(out.result.candidates, [])
  assert.equal(out.calls.some(c => /^(gates:|paper:|lane-status)/.test(c.label)), false)
  assert.ok(out.result.waiting_for.length)
  assert.equal(out.meta.phases.at(-1).title, 'Report')
})

test('backtest-tournament: a skeptic of a different commit cannot qualify a candidate', async () => {
  const out = await run('backtest-tournament', BT_ARGS, c => c.label.startsWith('skeptic:')
    ? { verdict: 'PASS', head_sha: BASE, findings: [] } : bt(c))
  assert.deepEqual(out.result.candidates, [])
  assert.equal(out.result.status, 'degraded')
})

test('backtest-tournament: failed statistical gates stay in the report and do not gain merit', async () => {
  const out = await run('backtest-tournament', BT_ARGS, c => c.label.startsWith('gates:')
    ? { ...bt(c), all_pass: false, dsr_prob: 0.5, pbo: 0.3 } : bt(c))
  assert.equal(out.result.ranking.length, 2)
  assert.deepEqual(out.result.candidates, [])
})

test('model scanner rejects missing models, pinned ids and misleading prompt text', () => {
  assert.deepEqual(check("agent('review', {model: 'opus'})"), [])
  for (const src of ["agent('model: opus', {})", "agent('review', {model: 'claude-pinned'})"]) {
    assert.ok(check(src).length, src)
  }
})
