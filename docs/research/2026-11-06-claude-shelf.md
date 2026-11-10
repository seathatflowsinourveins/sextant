# Claude shelf: upstream install and verification evidence

Read 2026-11-06. Scope: the G1 brief's Claude shelf, implemented on `shelf-skills-plugins-mcp` from `origin/main` (`cf377d0`). Versions and proofs are in [the manifest](../manifest.md#claude-shelf); byte hashes and resolved source commits are in [the snapshot record](../../.claude/shelf.lock.json). This implements the approved picks rather than reopening the foundations convergence.

## Native loading, without a bootstrap hook

Upstream checked: Claude Code's [project settings](https://code.claude.com/docs/en/settings), [settings reference](https://code.claude.com/docs/en/settings-reference#enabledplugins), [per-repository plugins](https://code.claude.com/docs/en/plugins/org#require-plugins-per-repository), [marketplace source reference](https://code.claude.com/docs/en/plugins/marketplace-reference), [MCP configuration](https://code.claude.com/docs/en/mcp), [Agent Skills](https://code.claude.com/docs/en/skills), [code intelligence](https://code.claude.com/docs/en/plugins/code-intelligence) and [CLI settings override](https://code.claude.com/docs/en/cli-reference), all read 2026-11-06. These are live docs, not a versioned 2.1.318 documentation archive. The relevant configurations were also validated by the actual 2.1.318 executable.

The upstream per-repository install path is `extraKnownMarketplaces` plus `enabledPlugins`. A plugin whose entry uses a relative source loads from the marketplace checkout after native workspace trust. A project-enabled plugin with an external source does not auto-install. All four selected upstream plugin marketplaces use `source: "./"`, so no project hook or installer is needed. Workspace trust and the owner's normal Claude sign-in remain native first-use requirements; they were not bypassed or exercised here. See the per-repository docs above.

The marketplace source schema accepts a branch or tag `ref`, not a separate commit `sha`. A direct probe, `claude plugin marketplace add https://github.com/obra/superpowers.git#22f0b463e7a5e579904dd6211a520321035526f7`, failed with `Remote branch ... not found` on host 2.1.319. Adopt the documented release refs with `autoUpdate: false`, and record their verified full commits. On the extracted 2.1.318 runtime, adding each tagged marketplace and running `git -C <temporary marketplace> rev-parse HEAD` resolved all four to the brief's exact SHAs. This records today's tag resolution; native marketplace settings do not enforce that a tag can never be retargeted.

The official LSP catalog has no tags (`git ls-remote --tags https://github.com/anthropics/claude-plugins-official.git` returned none). Instead of following its moving default branch, the two official plugin directories are copied verbatim from the recorded commit, including their READMEs and licences. The small `sextant-lsp` catalog adopts Claude's documented [local marketplace example](https://code.claude.com/docs/en/plugin-marketplaces), with relative sources to those directories. It adds no plugin implementation or hooks. The proof checks all six upstream files by SHA-256.

## Sources read at the pins

- upstream checked: [obra/superpowers@v7.0.2](https://github.com/obra/superpowers/tree/22f0b463e7a5e579904dd6211a520321035526f7): `README.md`, `.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`, `hooks/hooks.json`. Native plugin, 15 skills, one SessionStart hook; no MCP definition.
- upstream checked: [EveryInc/compound-engineering-plugin@compound-engineering-v3.36.0](https://github.com/EveryInc/compound-engineering-plugin/tree/7dc50943bbf959dbe6a93a175e41e5fff8395e00): `README.md`, `.claude-plugin/`, `skills/ce-compound/SKILL.md`, `skills/ce-bakeoff/SKILL.md`. Native plugin includes all 37 skills; no lifecycle hook or MCP declaration. The two requested skills use that plugin; no selective plugin loader was invented.
- upstream checked: [tradermonty/claude-trading-skills@d8e71ce2f0b069eb5b6fca352857c168c35e6c46](https://github.com/tradermonty/claude-trading-skills/tree/d8e71ce2f0b069eb5b6fca352857c168c35e6c46): README's "Use with Claude Code", the seven named skill directories and `LICENSE`. No native plugin manifest exists at this pin. Follow its documented folder-copy path; 65 skill files plus the repository licence are copied byte for byte. No other skill is copied and no dependency scripts from those skills were run.
- upstream checked: [typesafe-ai/skills@v0.6.2](https://github.com/typesafe-ai/skills/tree/302eea662c54bca6730873fe245bec1d69ebc23d): `README.md`, `.claude-plugin/`. One native skill, `typesafe-ai`, invoked as `/typesafe:typesafe-ai`; no hooks or MCP declaration. No Jev request was made.
- upstream checked: [Yeachan-Heo/oh-my-claudecode@v5.7.30](https://github.com/Yeachan-Heo/oh-my-claudecode/tree/14cd0fe92fbe376fab6c89b333b7896811986d2d): `README.md`, `docs/REFERENCE.md` Environment Variables, `.claude-plugin/`, `hooks/hooks.json`, `.mcp.json`, `scripts/run.cjs`, `scripts/session-start.mjs`, `scripts/keyword-detector.mjs`. Its manifest selects 48 skills and its source has 19 agent files and 21 command-directory entries. Those are available only on session opt-in here.
- upstream checked: [upstash/context7@@upstash/context7-mcp@4.5.0](https://github.com/upstash/context7/tree/a138857cc23f0abaf214b72b15d974e61598369b): `README.md`, `packages/mcp/package.json`, `packages/mcp/src/index.ts`; also the registry package's `dist/index.js`. Use its stdio binary and documented `CONTEXT7_API_KEY` environment support, rather than a key-bearing command-line argument. Missing-key fallback is an empty string.
- upstream checked: [Cognition DeepWiki MCP docs](https://docs.devin.ai/work-with-devin/deepwiki-mcp), read 2026-11-06: official keyless HTTP endpoint `https://mcp.deepwiki.com/mcp`. The hosted implementation has no published version selector or source commit pin; it remains unpinned. No local proxy was built.
- upstream checked: [exa-labs/exa-mcp-server@npm-3.4.3](https://github.com/exa-labs/exa-mcp-server/tree/93c0d5e1fecfc1ec9bf70fa9f3633962a1f2fa8a): `package.json`, `src/stdio.ts`, `src/stdio-cli.ts`; [official local npm setup](https://docs.exa.ai/reference/exa-mcp), read 2026-11-06. Its binary reads `EXA_API_KEY` from the environment. The file stores only the variable reference, with an empty fallback; no authenticated search was exercised.
- upstream checked: [openags/paper-search-mcp@cab1b5cc276a0cd004a0044003926a6440088049](https://github.com/openags/paper-search-mcp/tree/cab1b5cc276a0cd004a0044003926a6440088049): `README.md` Method 2, `pyproject.toml`; [uv tool sources](https://docs.astral.sh/uv/guides/tools/), read 2026-11-06. Use upstream's `uvx` entry point with uv's supported `--from git+...@<commit>` source pin. Optional provider credentials are inherited by upstream environment names; no dotenv is copied or generated.
- upstream checked: [microsoft/playwright-mcp@v0.0.84](https://github.com/microsoft/playwright-mcp/tree/be26c080edfae7c761db1e757c4aff9f6453b4d7): `README.md`, `package.json`. The approved plan's MCP row still names Playwright. Use the pinned stdio binary with documented `--headless` and `--isolated` options; browser launch and browser download were not exercised.
- upstream checked: [colbymchenry/codegraph@v1.6.2](https://github.com/colbymchenry/codegraph/tree/6560052a6f856855d3f71eee838fd66ccfa4285d): README's Manual Setup and Quick Start, `package.json`, `src/bin/codegraph.ts`. Adopt `codegraph serve --mcp` and `alwaysLoad: true`. The upstream separates wiring from `codegraph init`; this task does not create an index.
- upstream checked: [anthropics/claude-plugins-official@cb421c81df4274fd28fd1ead817bc6ffea723fed](https://github.com/anthropics/claude-plugins-official/tree/cb421c81df4274fd28fd1ead817bc6ffea723fed): `plugins/pyright-lsp/`, `plugins/typescript-lsp/`, `.claude-plugin/marketplace.json`. Both official plugins remain verbatim. Their documented npm language-server binaries are included in the existing locked agent-package install, whose bin directory both `.devcontainer/Dockerfile` and `origin/clean-start:deploy/wsl/setup.sh` put on PATH.

## Hooks and MCP footprint

Until 2026-11-09 there was no project `hooks` setting or `.claude/hooks/` directory. **Amended 2026-11-09:** `.claude/settings.json` now declares two compaction hooks, `SessionStart` with matcher `compact` and `PreCompact`, both calling `scripts/compact_context.py`; there is still no `.claude/hooks/` directory. The only default plugin hook is Superpowers' synchronous SessionStart command, `"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start`, matcher `startup|clear|compact` ([pinned hook definition](https://github.com/obra/superpowers/blob/22f0b463e7a5e579904dd6211a520321035526f7/hooks/hooks.json)). The other default plugins and copied skills declare no lifecycle hooks; `rg -n '^hooks:|^  hooks:|"hooks"\s*:'` across their skill directories returned no matches.

OMC's documented `DISABLE_OMC=1` disables hooks, but that check is absent from some registered scripts at this pin, including `scripts/session-start.mjs`; `scripts/run.cjs` does not provide a universal switch check either. Accordingly, adopt both native `enabledPlugins["oh-my-claudecode@omc"] = false` and the documented switch. `just omc` uses the higher-precedence native `--settings` option to set the plugin true and `DISABLE_OMC=0` for that process only. This leaves its entire hook and MCP bundle unloaded by default, without patching upstream. See the pinned OMC files listed above and [the override proof](../../tests/proofs/test_claude_shelf.py).

On opt-in, OMC's pinned `hooks/hooks.json` registers 30 command entries over 11 events, all through `node "${CLAUDE_PLUGIN_ROOT}"/scripts/run.cjs`. Script names below are relative to its `scripts/` directory; all end in `.mjs`.

| Event | Matcher | Scripts |
|---|---|---|
| UserPromptSubmit | `*` | `keyword-detector`, `skill-injector` |
| SessionStart | `*` | `session-start`, `project-memory-session`, `wiki-session-start`, `stale-run-reporter`, `runs-reconciler` |
| SessionStart | `init` | `setup-init` |
| SessionStart | `maintenance` | `setup-maintenance` |
| PreToolUse | `*` | `pre-tool-enforcer` |
| PreToolUse | `Bash` | `git-guardrails` |
| PermissionRequest | `Bash` | `permission-handler` |
| PostToolUse | `*` | `post-tool-verifier`, `project-memory-posttool` (async) |
| PostToolUse | `Read\|Write\|Edit\|MultiEdit` | `post-tool-rules-injector`, `post-tool-directory-context-injector` |
| PostToolUseFailure | `*` | `post-tool-use-failure` |
| SubagentStart | `*` | `subagent-tracker start` |
| SubagentStop | `*` | `subagent-tracker stop`, `verify-deliverables` |
| PreCompact | `*` | `pre-compact`, `project-memory-precompact`, `wiki-pre-compact` |
| Stop | `*` | `context-guard-stop`, `workflow-drift-guard`, `persistent-mode`, `budget-guard`, `code-simplifier` |
| SessionEnd | `*` | `session-end`, `wiki-session-end` |

The six project MCP definitions are Context7, DeepWiki, Exa, paper-search, Playwright and CodeGraph ([configuration](../../.mcp.json)). OMC adds only its internal stdio server `t`, `node ${CLAUDE_PLUGIN_ROOT}/bridge/mcp-server.cjs`, on opt-in ([pinned `.mcp.json`](https://github.com/Yeachan-Heo/oh-my-claudecode/blob/14cd0fe92fbe376fab6c89b333b7896811986d2d/.mcp.json)). Python and TypeScript use LSP, not additional MCP servers. No broker server or trading endpoint is configured.

## Measured validation

All tool downloads, caches and dependencies were confined to this clone's `.git/`, `.venv/` and agent `node_modules/`, except the brief-authorized empty temporary `CLAUDE_CONFIG_DIR` directories under its parent. No native sign-in was used. Ad-hoc Python probes and repository checks used the existing Northstar `memcap.py 8 --` wrapper.

- `claude --version`: host **2.1.319**. The official `@anthropic-ai/claude-code-linux-x64@2.1.318` registry archive was fetched into `.git/shelf-upstream/`, its SHA-512 checked against registry `dist.integrity`, and its executable returned **2.1.318**. No upstream installer script was run.
- On both versions, `claude plugin validate` passed for the four plugin manifests, the local LSP marketplace and both official LSP plugins. Warnings: upstream OMC's root `CLAUDE.md` is not loaded as plugin context; directory listing checks report missing icons and advise README install lines. Upstream files were retained unchanged.
- On both versions, `claude mcp add-json --scope local <name> <JSON>` accepted all six definitions in isolated configuration homes. This validates configuration parsing, not server connectivity.
- On 2.1.318, `claude plugin marketplace add <repo>#<tag>` passed for all four upstream catalogs; each cached checkout's `git rev-parse HEAD` equalled its recorded commit. `claude plugin marketplace add ./.claude/lsp` passed too.
- JSON Schema: `uv run --no-project --python 3.13 --with jsonschema==4.26.0 python` using `Draft7Validator` against `https://json.schemastore.org/claude-code-settings.json` found **zero errors** in `.claude/settings.json`.
- `npm install --package-lock-only --ignore-scripts --no-audit --no-fund --prefix .devcontainer/agents`, then `npm ci --ignore-scripts --no-audit --no-fund --prefix .devcontainer/agents`: succeeded with the cache in `.git/shelf-cache/npm`. `npm audit signatures --prefix .devcontainer/agents` verified **859 registry signatures and 167 attestations**.
- `uv run --frozen pytest tests/proofs/test_claude_shelf.py`: **14 passed**. The hash proof covers every copied skill and LSP file, not only `SKILL.md`.
- `just ci`, with clone-local just 1.59.0 and actionlint 1.7.12 (release hashes from the existing Dockerfile verified) and the locked agent binaries on PATH: **38 tests passed**, ruff check/format passed, Pyright reported zero errors/warnings, zizmor/actionlint passed, gitleaks found no leaks.

## Not verified

Signed-in interactive startup after native workspace trust; the live `/plugins`, `/hooks`, `/mcp` and LSP diagnostics views; actually running `just omc`; authenticated Context7/Exa/TypeSafe use; paper-search queries; Playwright browser installation/launch; a CodeGraph index/query; full sandbox/GitHub environment proofs; the clean WSL or Docker setup itself. Those require a runtime session or environment outside this brief's local-only validation. No such tests were added to this PR.

The offline proofs assert configured release refs and recorded full SHAs; they do not enforce future remote tag immutability. DeepWiki's hosted server is explicitly unpinned. Cross-family dsh PR review is for the lead's push; no GitHub write or review execution occurred here.

Harness: Codex App, native-hook surface; host `codex --version` reports `codex-cli 0.166.0`. GPT-family as assigned by the brief; the exact served model ID and effective reasoning-effort setting are **UNVERIFIED**, because this surface supplies no session attestation. The user requested the highest supported effort; no alternate model or reduced-effort worker was launched.
