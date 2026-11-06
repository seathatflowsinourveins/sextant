# ADR-0023: Carry the foundation rules without the old campaign machinery

- **Status:** accepted. Harvested; the decision is unchanged unless "Changes for Sextant" says otherwise.
- **Date:** 2026-11-06
- **Harvested from:** northstar@b384d298d217:claude/AGENTS.global.md
- **Harvested from:** northstar@b384d298d217:docs/decisions/0045-harness-first-upstream-first.md
- **Harvested from:** northstar@b384d298d217:docs/decisions/0046-proportionate-rigor-and-focus.md
- **Harvested from:** northstar@b384d298d217:docs/decisions/0048-quality-first-efficiency-by-architecture.md

## Context

Trading needs sourced decisions, measured merit and a harness that improves itself. Carry those rules, not the old campaign's orchestration. The approved plan and later owner rulings in [ADR-0001](0001-sextant-foundation.md) govern Sextant's changes.

## Decision

- **Evidence first:** source every non-trivial technical claim or give its measurement command. Mark anything not verified **unverified**. Check APIs against the installed version. Evidence belongs in `docs/research/`; decisions link it. [E]
- **Bridge, not builder:** agentic work uses a maintained harness or SDK. Search the pinned upstream's releases, examples, templates, docs and issues, plus existing adapters, before adding anything. Report `upstream checked: <repo@tag:path>` for each piece. Trading starts from upstream adapters, strategy templates or a cited published method; record deviations. [U]
- **Upstream is presumed correct:** adopt its documented practice, redesign the need or record non-use. An upstream filing, local patch or workaround is not a resolution. Sextant's stricter no-source exception is below. [U]
- **Pin what was verified:** an exact registry version plus lockfile hash, or a full commit SHA; check available provenance and retain an update path. A pin records a read, not safety. Models use the highest-scoring SOTA model of the latest generation; IDs follow latest-only policy. [P]
- **Latest stable defaults:** every environment layer on every host uses the latest stable upstream release through its documented install path, pinned with an update path. Legacy compatibility needs a recorded hard constraint, reason and named evidence trigger. [L]
- **Quality first:** usage is not capped or rationed. Never lower model or effort, shrink a panel or skip review for tokens. Efficiency uses stable cached prefixes, suitable role routing, narrow structural reads, conclusions and resumed work. A saving requires non-decreasing quality and lower cost per solved task beyond uncertainty. Stronger resolvers, not more gates, provide quality. [Q]
- **Proportionate rigor:** fix and verify the task's measured risk. After two FAIL rounds without a confirmed finding on that risk or a hard line, land with residuals recorded. No new security machinery without a measured, relevant threat. Beyond hard lines, security findings are best-effort issues, never blocking rounds; blind-leg independence remains a quality rule. [R]
- **Resolve now:** start accepted work immediately; run independent ready work in parallel within ownership and capacity bounds. Dependencies and revisits are evidence events, not convenient dates. Market boundaries, credential lifetimes, owner-exception expiries and mandatory safeguard clocks remain gates. [N]
- **Compound research without bias:** register criteria first; use the same neutral brief, blind independent legs and process-only posts. Verify highest supported effort from each session. Screen owner stars; reconcile syntheses at primary sources and report disagreements. Publish each claim's pinned source, read date and confirming families. Reverify load-bearing facts; rederive verdicts blind. [C]
- **Trading lanes:** paper strategies, orders and integration tests need no human approval; tests, reviews and broker refusals still apply. Each account has one writer. Live needs the sanctioned runner, promotion record, gates, stages and limits; owner credential custody, limit approval and halt remain. No agent gains direct live access. Money and quantity use engine types or `Decimal`, never floats. [T]
- **Trading learning:** decide trade-offs by point-in-time replay, sim and recorded paper fills, with walk-forward, CPCV, DSR and PBO over one cumulative trial ledger. Every exit and incident leaves an append-only lesson; corrections are new records. Nightly tuning proposes only; every arm and run, including 24/7 sim, counts. [T]
- **Hard lines still block:** a readable or leaked secret; a live order outside the sanctioned runner or gates; Claude OAuth in a third-party runtime outside the bounded TUI6 `dsh-tui` exception; an unrequested destructive action; a bypassed guard; or a foundation breach: unsourced decisions, self-invention or upstream patching where an upstream practice exists, upstream filings offered as fixes, or missing required convergence. The old exception grants no wider sign-in authority. [H]

## Evidence

| Claim | Source (repo@sha:path, section or line) | Basis |
|---|---|---|
| E: evidence and APIs | [northstar@b384d298d217:claude/AGENTS.global.md, L9–17](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/claude/AGENTS.global.md#L9-L17) | Foundation standing rule; owner 2026-10-24 hard-line ruling. |
| U: maintained harness, upstream, trading sources | [northstar@b384d298d217:docs/decisions/0045-harness-first-upstream-first.md, L18–23, L36–96, L263–286](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/docs/decisions/0045-harness-first-upstream-first.md#L18-L23) | Owner 2026-10-21/23/24; upstream-presumed-correct amendment retains its acknowledged pre-release-defect exception. |
| P: exact pins, latest-only models | [northstar@b384d298d217:claude/AGENTS.global.md, L83–86, L124–134](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/claude/AGENTS.global.md#L83-L86) | E35–E38/E41 and ADR-0039/0033 as named by the standing rule; underlying evidence not re-researched. |
| L: environment defaults | [northstar@b384d298d217:claude/AGENTS.global.md, L87–93](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/claude/AGENTS.global.md#L87-L93) | Owner 2026-11-02, ADR-0074 pointer; exact host scope retained. |
| Q: quality and architectural efficiency | [northstar@b384d298d217:docs/decisions/0048-quality-first-efficiency-by-architecture.md, L28–55, L81–104, L151–162, L186–210](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/docs/decisions/0048-quality-first-efficiency-by-architecture.md#L28-L55) | Owner 2026-10-21/30/31 and 2026-11-01; four-family token-efficiency convergence; November 5 reconciliation. |
| R: risk scope, bounded rounds, security | [northstar@b384d298d217:docs/decisions/0046-proportionate-rigor-and-focus.md, L13–33, L238–264](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/docs/decisions/0046-proportionate-rigor-and-focus.md#L13-L33) | Owner 2026-10-21/24 and 2026-11-02; measured Keychain incident, not a general adversary premise. |
| N: events and safeguard clocks | [northstar@b384d298d217:docs/decisions/0046-proportionate-rigor-and-focus.md, L113–135, L183–198](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/docs/decisions/0046-proportionate-rigor-and-focus.md#L183-L198) | Owner 2026-10-30 and 2026-11-02; resolve-now never waives safeguards. |
| C: blind convergence, claim ledger | [northstar@b384d298d217:docs/decisions/0045-harness-first-upstream-first.md, L165–188, L288–306](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/docs/decisions/0045-harness-first-upstream-first.md#L165-L188) | Owner 2026-11-01; claims may compound, prior verdicts may not. |
| T: paper, live, learning and money | [northstar@b384d298d217:claude/AGENTS.global.md, L114–122](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/claude/AGENTS.global.md#L114-L122); [northstar@b384d298d217:docs/decisions/0045-harness-first-upstream-first.md, L278–280, L298](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/docs/decisions/0045-harness-first-upstream-first.md#L278-L280) | Owner paper-autonomy and live-evidence rulings; lesson-v1/one-ledger policy; approved plan Paper and Phase 7. |
| H: current hard lines and trading review gate | [northstar@b384d298d217:claude/AGENTS.global.md, L103, L138–147, L181, L192–196](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/claude/AGENTS.global.md#L138-L147) | Owner foundation hard lines 2026-10-24; bounded TUI6 exception 2026-11-04; Sextant substitutions below. |
| Revisit events | [northstar@b384d298d217:docs/decisions/0045-harness-first-upstream-first.md, L237–251](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/docs/decisions/0045-harness-first-upstream-first.md#L237-L251); [northstar@b384d298d217:docs/decisions/0046-proportionate-rigor-and-focus.md, L86–101, L262–264](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/docs/decisions/0046-proportionate-rigor-and-focus.md#L86-L101); [northstar@b384d298d217:docs/decisions/0048-quality-first-efficiency-by-architecture.md, L121–135](https://github.com/seathatflowsinourveins/northstar/blob/b384d298d217d3f8d9aa83356994629536a34795/docs/decisions/0048-quality-first-efficiency-by-architecture.md#L121-L135) | Existing E45/E46/E48 events; missing detectors never gate finalization. |

## Changes for Sextant

- Approved plan, "Removed": `ns-lane.sh`, receipts, verify ledgers, one-lander, landing trains, beads, release tooling. Keep short rule files and GitHub Issues. No old installers, doctor or runtime/account routing machinery is carried (Harvest; Repo layout and budgets).
- Landing follows [ADR-0001](0001-sextant-foundation.md): `ci` and `review`, squash auto-merge, current dsh/Claude risk routing and round limit. Risk-critical trading retains its safety/review gates. Plan Phase 7 carries ADR-0053 in full; its only verdict substitution is two-family review on the exact SHA. Owner live-path authorization is still required.
- Source-less self-building needs the owner's exception and a manifest search record, under [Rule 1](../../AGENTS.md#rule-1-never-self-invent). Cited upstream evidence, architectural fit and convergence decide stack picks; a self-built bench never gates them. Trading-edge merit remains mandatory (ADR-0045, L128–153, L298).

Owner's newest words, verbatim (COMMON.md, 2026-11-05 and 06):

> "our compounding learning,reflecting, memory/rag etc need to be clean enhacned with sotarepos,adrs harvest with previous convergenced campaign but clean sota architecture never bloat, including the harness rules, our trading philosophy 24/5 24/7 and always previous stated limit ,1000trades/min live lane and 200 paper, 3000for ibkr paper and live"
> "FOCUING ON US EQUALITY, OPTION,STOCKS ETC, AND ALL THE LANES PREVIOSU STATED, PHILOSOPY PREVIOUS STATED, JEV TRADE RELATED RPEOS ETC ,RESEARCH LANE ,AUTO LEVERAGE, PROTFOLIO MANGEMENT AND BEYOND"
> "EVERY HARNESS,EVERY ACTIONS NEED TO BE BUILT FORM SOTA SOURCES ITSELF, INCLUDING THIS VERY HARNESS , FOCUING ON THE TRADING TOPIC , THE QUALITT AND SOTANESS ITSELF RATHER THAN SECURITY OVEREGINNERING ETC"
> "we need to using full sota harness framework.dsh that is fully enhanced with openviking etc"

## Code and config to carry

None. This record links the old rule homes; it does not copy their rule file or tooling. Current enforcement, host conformance and upstream currency are **unverified** by this harvest.

## Disagreements

- ADR-0045's original "not a safety rule" and own-task A/B wording is superseded by its October 24/27 and November 1 owner amendments: evidence/upstream rules are hard lines; no self-built adoption gate.
- Old `none exists:` plus lead approval allowed minimal self-building. Sextant's newer Rule 1 requires the owner's exception. The old pre-release guard exception is recorded history, not permission for a new patch here.
- ADR-0046's older absolute live/OAuth prohibitions are scoped by the later sanctioned-runner authority and November 4 TUI6 exception in the global rule. Sextant's Phase 7 live-path authorization is not assumed.
- Old finalization required closed registers and multi-harness provenance before install. Approved plan "How we make sure it lands" requires evidence and one cross-family review; research campaigns are for real-money gates. Receipts and landing machinery are removed, not the actual safety or merit gates.
- Old risk-critical main/live code required `adversarial-verify`; the plan retains that Workflow and substitutes exact-SHA two-family review for ADR-0053's live verdict only. The plan's local runner, launchers and review routing were later changed in ADR-0001; its recorded owner rulings control.

## Revisit when

- Upstream release, model, interface, advisory, deprecation, licence or official-adapter evidence changes a carried claim; independent evaluation, a named newcomer or owner-star assessment changes a need (E45-1/2/3; E48-1/3/6). Owner: the lead; response: source check, convergence/review and amendment through a PR.
- A measured incident, review or changed shared/data/unattended-live boundary challenges these rules, or a downgraded security finding causes a hard-line breach (E45-4; E46-1–5). Owner: the task/trading lead; apply the hard line immediately, then record evidence and amend.
- Quality falls after an efficiency change: revert; cost rises without quality gain: reroute (E48-4). Owner: the lead. An owner policy/spend/authority change or "multi-model verdict, next version" opens the corresponding reviewed amendment (E45-5/7; E46-7/8; E48-5/7); missing detectors never hold today's decision.
