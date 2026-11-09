# Third-party plugins: disclosure before a row

The catalog is an index, not a review. Its README says a listing "doesn't rank plugins or judge their quality", and that installing one runs third-party code with the user's permissions; tool approvals do not sandbox it ([awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin), read 2026-11-09). This page records the landscape screen behind the watching rows and the gate every third-party plugin passes before it enters `docs/manifest.md`.

## The screen

Read 2026-11-09 from the catalog at `668c3fa6e759f413da6b90e3f3af9a3e6b0f6ee9`: 9,714 entries over 9,384 repositories. Its `data/capabilities.json` holds the disclosure [liuwenji007/dsh-trust-check](https://github.com/liuwenji007/dsh-trust-check)@`787912e37367e3b0e5cbe5a259253a88f3afd502` (MIT, `dsh-trust-check@0.1.13`) produced for 3,821 of them; `data/downloads.json` holds 624 download records.

- 451 entries declare red lines; 890 scanned entries declare no shell, network or environment access.
- Declared capabilities: filesystem read 2,864, filesystem write 2,246, environment 2,192, network 2,169, shell 1,626, credentials 454, model calls 347, dynamic code 346, host runtime 296, subagents 86.
- The shelf already owns the repackaged practices: 12 superpowers, 8 mattpocock, 33 TypeSafe, 2 Aegis, 39 SKILL.md bundles, and no compound-engineering. A second copy is a second owner; only a gap with no shelf owner qualifies.
- 5,893 entries have no scan at all. An absent scan is unavailable, never clean.

## The screen's verdicts

- **Adopt the gate, not a plugin.** The scanner reports capabilities, literal destinations, install scripts and injection shapes with `file:line` evidence; it is disclosure, not a verdict.
- **Pattern only:** hash-chained receipts ([030611/dsh-verification-receipt](https://github.com/030611/dsh-verification-receipt), 4★, MIT; [030611/qiushi-dsh-evidence-audit](https://github.com/030611/qiushi-dsh-evidence-audit), 3★, MIT). The goal gate already binds a verdict to a tree digest and CI keeps its own receipts, so this adds a format, not an owner.
- **Watch [eve1329/dsh-shared-handoff](https://github.com/eve1329/dsh-shared-handoff)** (0★, MIT): `.agents/state` shared with Codex and Claude, handoff and per-turn snapshots. Trigger: a measured cross-family handoff that lost state; then a leg, a row and its proof.
- **Watch [kenz1117/dsh-engram](https://github.com/kenz1117/dsh-engram)** (66★, MIT): SQLite FTS5 plus vector retrieval, a provenance chain, SM-2 and decay. Trigger: OpenViking is retired or a measured retrieval need remains. Never run two memories.
- **Reject [pengpengyi92/dsh-quant](https://github.com/pengpengyi92/dsh-quant)** (68★, MIT): walk-forward evaluation is weaker than ADR-0015's CPCV and untouched holdout, and it owns no US-equity entry, exit or custody. **Reject [taoqizhang55-code/stockproof](https://github.com/taoqizhang55-code/stockproof)** and [kentleenot/dsh-trading-toolkit](https://github.com/kentleenot/dsh-trading-toolkit) for the same reason: a duplicate data and PIT owner.

## Re-screen

The screen is a snapshot, not a one-time approval. Re-screen on every catalog pin bump: a changed capability or a broken proof sends the plugin back through the five fields. [liuwenji007/dsh-trust-check](https://github.com/liuwenji007/dsh-trust-check)@`787912e37367e3b0e5cbe5a259253a88f3afd502` makes the pre-install gate and the pin-bump rescan the rule; [awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin)@`668c3fa6e759f413da6b90e3f3af9a3e6b0f6ee9` is the dated index.

## The gate

A plugin enters the `## Third-party plugins` section of `docs/manifest.md` only when its row records all five:

- **Pin.** `owner/repo@tag` and the full 40-hex commit, or the catalog's exact URL at a dated read. A branch name is not a pin.
- **Disclosure.** The declared capabilities and red lines for that exact version, from the scanner or the catalog's scan. "Not scanned" is unavailable; write it and stop.
- **Owner.** One lane and one writer. It owns no memory, router, reviewer or broker account that another row owns.
- **Proof.** A `just prove` test that the installed tree is the pinned tree, as the shelf's copies are checked.
- **Removal.** The exact uninstall and the files it leaves.

No row, no install. A plugin that fails any line stays in `## Watching, not installed` with a named trigger. A scan is not a sandbox: the code still runs with the session's permissions, so the owner's sign-in, the secrets store and the live lane stay out of reach by `AGENTS.md`'s hard lines, not by the scan.

## Why dsh adds no plugin yet

The screen found no gap the shelf does not already cover. The dsh lane's 25 pinned skills are the converged subset of the Claude shelf, and the session-level pack adds no consumer that needs a plugin's code. The two watches name the triggers that would change that.
