# Upstream authority

One upstream owns each surface. A PR that changes a governed path must name that surface's owner in
its Upstream references; `dangerfile.js` reads this rule from the base branch and fails the PR
otherwise. The map is the convergence point: a fork, a second SDK, a second memory or a second
review owner is not a pick, it is a new surface, and it needs an ADR before it gets a row.

| Surface | Sole owner(s) | Pin | Governed paths |
|---|---|---|---|
| `engine` | `nautechsystems/nautilus_trader`, `alpacahq/alpaca-py`, `docs.alpaca.markets` | `nautechsystems/nautilus_trader@v2.0.0rc8` `d53849b216e20f2c122ca01b4dd0da377638b186` | `src/sextant/exits/`, `src/sextant/execution/`, `src/sextant/risk/`, `src/sextant/backtest/` |
| `broker` | `alpacahq/alpaca-py`, `docs.alpaca.markets`, `nautechsystems/nautilus_trader` | `alpacahq/alpaca-py@v0.44.0` `cc4cb3b7ba50ae250e621983c2779047fb16bb28`; IBKR adapter at the Nautilus pin | `src/sextant/paper/`, `src/sextant/alpaca/`, `lanes/paper/` |
| `data` | `alpacahq/alpaca-py`, `sharadar.com`, `apache/arrow`, `psf/requests` | `psf/requests@v2.34.2` `6e83187b8feb273ed4c6cdab5efd8d54901dfab3`; Sharadar `read 2026-11-06` | `src/sextant/data/` |
| `tradingview` | `ferroxlabs/tvcontrol`, `tradingview.com` | `FerroxLabs/tvcontrol@v2.5.3` `85200201f92967db9e4b63a9251d51fcdfe1f3a8`; Pine docs `read 2026-11-06` | `src/sextant/tradingview/`, `lanes/tradingview/` |
| `harness` | `deepseek-ai/deepseek-harness`, `trailofbits/claude-code-devcontainer`, `everyinc/compound-engineering-plugin`, `obra/superpowers`, `typesafe-ai/skills`, `ccch1mneyyy/dsh-tui`, `anthropics/claude-code`, `stablyai/orca`, `orchestratorinc/agent-orchestrator`, `danger/danger-js`, `volcengine/openviking`, `ggml-org/llama.cpp` | `deepseek-ai/deepseek-harness@dsh-v0.2.2-rc.1` `66491b05e3f05ad35bcdd4f6cd7ed26041d9e3db`; `OrchestratorInc/agent-orchestrator@v0.14.10` `033d597032e448a0ea16c298350e36b099f74106`; `danger/danger-js@14.1.0` `72540533c4f99bad772ba303be0eb4af6eddbdc4`; `volcengine/OpenViking@v0.5.3` `178a8cdfb41b51e7d24c4bf79a13cc54981e0ee8`; `ggml-org/llama.cpp@b11960` `8642541b255bfb5dc39cd351a178be09013a55d6` | `deploy/wsl/` |
| `lanes` | `nautechsystems/nautilus_trader`, `alpacahq/alpaca-py`, `sharadar.com`, `tradingview.com` | `nautechsystems/nautilus_trader@v2.0.0rc8` `d53849b216e20f2c122ca01b4dd0da377638b186` | `lanes/` |

## How it holds

- `dangerfile.js` keeps the same six surfaces in `AUTHORITY`; `tests/proofs/test_sources.py` fails
  when this page and that object drift, and witnesses each surface refusing a fork and accepting its
  owner.
- A governed path with no authority citation fails `source`. The rule runs from the base branch, so
  a PR cannot edit its own check; changing `dangerfile.js` is a gate path with its extra review.
- A new upstream owner is a deliberate act: add the surface or owner here and in `dangerfile.js`, in
  one gate-path PR, with the pin and the proof. Do not widen a surface to make a PR pass.
- `northstar-*` is a pinned bridge, not an authority: it may appear in Upstream references next to
  the surface's owner, never alone. Its own pins live in `docs/manifest.md`.
- The dsh catalog is a discovery surface, not an authority: an entry enters only by the capability
  and red-line register in `docs/handbook/plugins.md`.
- Strategies keep their own rule: an upstream template at a pinned commit or a cited paper.

## Where it came from

The shape is GitHub's code owners: a path has an owner, and changing it needs that owner's
review ([About code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners),
read 2026-11-09). This repo applies it at the gate, in `dangerfile.js`, because Danger runs from
the base branch and the rule must hold for a PR that edits the rule. The owners are the ones
already in `docs/manifest.md`; no owner is invented here.
