# ADR-0001: Sextant is built only from SOTA sources

Status: accepted, 2026-11-05. Drafted by Claude Code 2.1.318, `claude-opus-5-5`, max. Cross-family review: see the PR that lands this file.

## Context
The earlier campaign measured 8,393 tracked files, about 71 KB of rules per session, 17 hook entries, 108 deny rules, 1,130 open beads and 64 open PRs (northstar `35069bf281afb11fdbb87bde1ad66c77f7f0aca3`, measured 2026-11-05). Its last 100 merged PRs took a median of 3.2 hours once opened, so the delay was the local work before merge.

The owner's direction, verbatim:
- "i want to set up a clean new harnesses set up for all the lanes ... the most essential part for it is the cleanness.no endless block hooks and unneeded friction, only the harness project itself. it is aside of current endless refuse and never landing campagin ... with research lane and paper manfiest merit into live.make sure it have full sota skills, and harnesss, entire harness are only form sota sources and keep maintanced sota"
- "not cloud , local seamless with repo for sync sota practice,a clean sota practice harness framework"
- "the essential harnes rules is NEVER SELF INVENT, THE PRs WILL ENFORCE THE SOURCE OF THE SOTA REPOS FOUNDATIONS" / "OR SOTA TRADE STRATGIES ETC"
- "the entire workflow harness itself is built,install,integrate form sota repos and convergneced rsearch,even the research convergence practice itself"
- "make sur our automation itself are sota ,such as openhand and beyond with our philosophy and handbooks ,the other most essential rule are the compounding learning and self maintancing lifecycle"
- "this repo itself need to be clean sota and rather portable with github with secrect etc seamlessly stored"
- "high quality sota autmation, with our practice built form sota foundations with cited sources form sota repos and references."

## Decision
1. **Never self-invent.** Every mechanism and strategy names its source in `docs/manifest.md`. `dangerfile.js` and the `review` check refuse a PR without one, and self-invention is P0 in review.
2. **Compound and self-maintain.** Lessons feed back through PRs, and the harness keeps itself current.
3. **Boundaries, not hooks.** The sandbox is a dev container, gates are GitHub rulesets, and keys are Environment secrets. Zero project hooks.
4. **A PR lands on `ci` and `review` alone,** with squash auto-merge and no up-to-date rule. Both run from the base branch with `pull_request_target`, so a PR cannot change its own checks. PR code runs only in the container. zizmor's `dangerous-triggers` audit is ignored on those lines for this reason.

## Requests that override earlier northstar records
Quoted here, not re-researched:
| Item | Record | How it goes in |
|---|---|---|
| OMC | Trial closed (northstar ADR-0041) | Installed, off until a session turns it on |
| OpenViking (AGPL-3.0) | Hold for memory (northstar ADR-0069) | Local research retrieval; the index is disposable |
| Options | Unadmitted (trading ADR-0016) | Design ADR, zero-weight factor, sim only |
| Jev | Research (`northstar-yae.51`) | Paired arm, sim first, no live authority until it earns merit |

## Deviations from the approved plan, on the owner's later rule
- **Workspace:** bind mount with Trail of Bits' read-only protections, not a named volume, because that is upstream's own mitigation.
- **Launchers:** `devc` instead of self-written `up` and `agent`.
- **Review effort follows risk,** on the owner's direction ("highest quality review, but assign with high quality workflow and suitable efforts"): one other-family reviewer at high effort for an ordinary PR, two families at max for a risk path. Claude and Meta Muse join as reviewers once their sign-ins exist.
- **The verdict is the upstream rubric's `overall_correctness`.** From round three only a P0 blocks and the rest become issues, the plan's rule, so a PR cannot loop for ever. No upstream has a round limit. This one line in `review.yml` is the owner-approved plan's, not a mechanism of its own.

## Two adaptations with no upstream to copy
Each is the smallest adaptation of a cited upstream, with a manifest row saying where we looked:
- the private-range firewall, because Anthropic and Trail of Bits ship allowlists and the owner chose open web;
- the job guard, because GitHub supplies the hook but selected-workflow limits are organization features.

## Consequences and residuals
- A malicious page could trick a no-prompt agent into sending out what is in its sandbox: sign-ins and agent keys, never broker keys. Use low-limit, rotatable keys. Owner accepted.
- The runner user is in the `docker` group, which is root-equivalent on its device, so only main's workflows may run there. An administrator on that device can reach credentials. The live device is chosen at Phase 7, preferring one with no agents.
- Anyone who can merge to `live` could reach the live key, so `live` needs a promotion record and two-family review.

## Revisit when
- Median merge time passes 1 hour over the last 20 PRs, open PRs pass 10, or proven rows stop rising across 20 merged PRs: adding layers stops until the blocker is fixed. Owner: the lead.
- A candidate in the manifest's Watching list hits its trigger. Owner: the lead.
- A new release of a pinned upstream changes a mechanism we rely on: `refresh-manifest` or Dependabot opens a PR. Owner: the lead.
- The second family disagrees on an item: a factual error is fixed at the primary source, and a disposition disagreement is quoted here. Owner: the lead.
