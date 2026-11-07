# ADR-0001: Sextant is built only from SOTA sources

Status: accepted, 2026-11-05. Drafted by Claude Code 2.1.318, `claude-opus-5-5`, max. Cross-family review: see the PR that lands this file. Picks: [foundations convergence](../research/2026-11-05-foundations-convergence.md), two blind legs from two families.

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
1. **Never self-invent.** Every mechanism and strategy names its source in `docs/manifest.md`. `dangerfile.js`, run by the `source` check, refuses a PR without one, and self-invention is P0 in review.
2. **Compound and self-maintain.** Lessons feed back through PRs, and the harness keeps itself current.
3. **Boundaries, not hooks.** The sandbox is a dev container, gates are GitHub rulesets, and keys are Environment secrets. Zero project hooks.
4. **A PR lands on `ci`, `source` and `review` alone,** with squash auto-merge and no up-to-date rule. All run from the base branch with `pull_request_target`, so a PR cannot change its own checks. PR code runs only in `ci`, in a fresh JIT container of the sealed profile with a read-only token, no secrets, no caches and no Docker daemon. zizmor's `dangerous-triggers` audit is ignored on those lines for this reason. Local execution has the accepted host-trust limit below.

## Requests that override earlier northstar records
Quoted here, not re-researched:
| Item | Record | How it goes in |
|---|---|---|
| OMC | Trial closed (northstar ADR-0041) | Installed, off until a session turns it on |
| OpenViking (AGPL-3.0) | Hold for memory (northstar ADR-0069) | Local research retrieval; the index is disposable |
| Options | Unadmitted (trading ADR-0016) | Design ADR, zero-weight factor, sim only |
| Jev | Research (`northstar-yae.51`) | Paired arm, sim first, no live authority until it earns merit |
| Isolation from the old lanes | `AGENTS.md`'s "never connect to their services" (sextant #17) | The owner, 2026-11-06: "the fact for its too isolated is not my intent , its need sota automation and with clean land with upstream repos yes for all actions, but the sandbox is rather aggressive"; asked to confirm this rule as written, the owner answered: "set up full landscape sota automation,its prs monitor , why are thye not resolute with local sota ahrness freameowrkes automation" (both relayed verbatim on sextant#58, 2026-11-06). Read, don't write: reads of the old campaign's mounts, exports and relay are allowed. `wsl.exe`, writes to another distro, a second stream or writer on a held account, rootful Docker and TradingView's debug port stay forbidden |

## Deviations from the approved plan, on the owner's later rule
- **Workspace:** bind mount with Trail of Bits' read-only protections, not a named volume, because that is upstream's own mitigation.
- **Launchers:** `devc` instead of self-written `up` and `agent`.
- **Local ephemeral checks supersede hosted compute (2026-11-07, #201).** Hosted jobs stopped for account billing at 04:32Z. The owner's answer, recorded on #58 (comment 6707587169): "go local or go public"; on a follow-up, "you decide with highest quality convergence". The lead chose private local JIT containers at $0 Actions compute and explicitly accepted possible verdict forgery by this host's sudo-capable agents. Runner labels split two profiles (#201): `sealed` jobs, ci's PR code among them, get no Docker socket, API or shared network; only trusted base-branch jobs get the daemon. Native logs/receipts and blind multi-family legs mitigate it; an agent-free host is the upgrade. Public history/assets would expose vendor bars and owner fills. [Runbook](../../deploy/review/README.md).
- **GPT review waits.** The owner allows a subscription through OmniRoute and a dashboard API key. A GitHub-hosted VM cannot reach a local router, so OmniRoute waits for a local runner, and GPT stays in local agent sessions until then.
- **Review runs on gh-aw,** the pick of both research legs (J1), on the owner's rule ("EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF"). Each reviewer sets the `review` check with gh-aw's `create-check-run`, which replaces the hand-written verdict. The plan's bound stays, as an instruction: from a PR's third reviewed commit only a P0 fails.
- **One reviewer per PR, always the other family,** on the owner's direction ("dsh can be used and gpt via omni,anthropic via api only when quality needed") and "QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING". This replaces the plan's two reviewers on a risk path. Two reviewers would share one GitHub identity and one check name, so the later verdict would overwrite the earlier. The `live` branch keeps its promotion record and two-family review, which Phase 7 designs.
- **dsh runs through gh-aw's unsupported sample engine.** gh-aw lists it with no compatibility commitment, and it reaches DeepSeek through gh-aw's documented custom Anthropic endpoint. `strict: false` is what lets that endpoint take this repo's key, and it needs a private repo. The firewall still keeps the key out of the agent's sandbox.
- **Threat detection is off in both reviewers.** gh-aw's default detection engine is Copilot, whose sign-in is not admitted for this, and a second model on every PR is more than the owner asked for. A reviewer's verdict is therefore not screened for prompt injection, a residual of reading PR text.

## One adaptation with no upstream to copy
The private-range firewall is the smallest adaptation of a cited upstream, because Anthropic and Trail of Bits ship allowlists and the owner chose open web. Its manifest row says where we looked.

## Consequences and residuals
- The read-only binds stop direct edits, not an agent replacing the writable `.git` parent, as upstream's README also says. So the host runs no git or script in a working copy an agent has used.
- A malicious page could trick a no-prompt agent into sending out what is in its sandbox: sign-ins and agent keys, never broker keys. Use low-limit, rotatable keys. Owner accepted.
- Environment secrets reach the local JIT job, so review keys must be low-limit and rotatable; local root can read them. Broker keys stay unavailable to these check runners. The live device is chosen at Phase 7, preferring one with no agents.
- In ci, PR code runs as the runner's own user, so it can read that job's one-job runner credentials (the JIT input in its parents' `/proc` environment, the RSA key in the job root) until GitHub de-registers the runner after the job; upstream has no isolating option short of ARC's Kubernetes mode ([runbook](../../deploy/review/README.md#credentials)). The owner accepted it on 2026-11-07 (#201): "Accept + add exit cleanup"; a slot that stops early deletes its registration.
- Producer credential: the lead decided, under the owner's explicit delegation (2026-11-07, verbatim: "please decide with sota convergenced and recommand"), to keep the existing gh login as the JIT producer's credential for now. It predates #201. Every agent session on this host already holds it. With passwordless sudo, no on-host placement hides a credential from agents. Upgrade, when an agent-free host exists: a dedicated GitHub App with only Administration (read and write) and Metadata (read) on this repository ('Authenticating ARC to the GitHub API', read 2026-11-07), minting short-lived installation tokens ('To use the API on behalf of an organization or another user, you should create a GitHub App', 'Keeping your API credentials secure', read 2026-11-07). Rotate the gh token on any suspected exposure. The #138 re-check's reconciliation may supersede this.
- The repository's own docker jobs are main-gated, but a new branch workflow can still request the docker label: GitHub limits runners to selected workflows only through organization or enterprise runner groups. The repository has no collaborator (lead, 2026-11-07). Prerequisite: before any collaborator is added, the docker profile moves to an organization runner group limited to selected workflows, or to an agent-free host ([runbook](../../deploy/review/README.md#two-profiles)). The lead accepted this residual under the owner's delegation (2026-11-07, verbatim: "please decide with sota convergenced and recommand"). The repository has no collaborator. Every writer today is an agent on this host with passwordless sudo, so the docker label gives a writer nothing beyond the host access it already has. The prerequisite above makes it a boundary before any outside writer exists.
- A docker-profile job controls UID 1501's daemon, so it can reach that UID's files and could replace the daemon socket. It also shares the host's `/tmp`, as gh-aw expects of a runner and its daemon: systemd's `PrivateTmp=` would isolate it but breaks RootlessKit's subordinate-ID mapping. AWF mounts that same `/tmp` into every gh-aw agent sandbox, so an agent reading untrusted PR text can read the host's world-readable `/tmp` files and write into its world-writable directories. The lead accepted, under the owner's delegation (2026-11-07, verbatim: "auto proceed with those sessions actions confirm etc with as you are the lead"), that AWF mounts the daemon's /tmp, which is the host's, read-write into every gh-aw agent sandbox (gh-aw-firewall v0.29.0 system-mounts.ts:29). Measured: about 1,605 world-readable top-level files and 5 world-writable directories; a gitleaks scan found no credential. Limits: the AWF egress allow-list, configured safe outputs only, agent scratch 0700, and the slot's any-depth sweep of subordinate-range entries after every job. The upgrade is an agent-free host. That is the docker profile's trust boundary, held by main-gating. The gh-aw agent never sees the socket: AWF masks it unless DinD is enabled, and gh-aw stages system binaries instead of mounting the runner's filesystem ([runbook](../../deploy/review/README.md#two-profiles)).
- API review bills per use at DeepSeek's and Anthropic's rates, and Actions compute beyond Pro's included $18 a month bills at $0.006 a Linux minute (GitHub billing docs, read 2026-11-05). Not yet measured on this repo.
- Anyone who can merge to `live` could reach the live key, so `live` needs a promotion record and two-family review.

## Revisit when
- The first PR touching `src/sextant/execution` or `src/sextant/risk`: decide how a second family reviews it. Owner: the lead.
- gh-aw ships a supported dsh engine, DeepSeek publishes a definition, or the sample stops working: move to it. Owner: the lead.
- A PR's text is found to have steered a reviewer: turn threat detection on with a non-Copilot engine. Owner: the lead.
- Median merge time passes 1 hour over the last 20 PRs, open PRs pass 10, or proven rows stop rising across 20 merged PRs: adding layers stops until the blocker is fixed. Owner: the lead.
- A candidate in the manifest's Watching list hits its trigger. Owner: the lead.
- A new release of a pinned upstream changes a mechanism we rely on: `refresh-manifest` or Dependabot opens a PR. Owner: the lead.
- The second family disagrees on an item: a factual error is fixed at the primary source, and a disposition disagreement is quoted here. Owner: the lead.
