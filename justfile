# Run inside the sandbox: `devc up`, then `devc shell`.
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Install the locked Python dependencies.
sync:
    uv sync --frozen

# Everything the required `ci` check runs.
ci: sync lint test secrets

# Check the locked dsh profile, the live profile and the generated ecosystem index.
session-start:
    python3 scripts/dsh_profile_doctor.py
    python3 scripts/ecosystem_index.py --check
    python3 -I scripts/compact_context.py --check

lint:
    uv run --frozen ruff check .
    uv run --frozen ruff format --check .
    uv run --frozen pyright
    uv run --frozen zizmor --offline .github/workflows
    shellcheck .github/actions/ci-tools/install.sh
    mapfile -t workflows < <(find .github/workflows -maxdepth 1 -type f \( -name '*.yml' -o -name '*.yaml' \) ! -name '*.lock.yml' | sort); actionlint -shellcheck shellcheck "${workflows[@]}"

test path="":
    uv run --frozen pytest -n auto {{path}}

# Scan this PR's commits when CI gives a range, otherwise the working tree.
secrets:
    if [[ -n "${BASE_SHA:-}" && -n "${HEAD_SHA:-}" ]]; then gitleaks git --no-banner --redact --log-opts="$BASE_SHA..$HEAD_SHA" .; else gitleaks dir --no-banner --redact .; fi

# Inside the clean distro only: its settings, tools and Orca. See docs/start.md.
accept:
    uv run --frozen pytest tests/host

# Inside the clean distro only: Orca at this repo's pin, served by Orca's own service. See docs/start.md.
orca-update:
    bash deploy/wsl/update-orca.sh

# Inside the clean distro only: git's upkeep and Orca's daily lifecycle sweep. See docs/start.md.
lifecycle:
    bash deploy/wsl/lifecycle.sh

# Inside the clean distro only: the verified reflection, Orca's automation behind its session/merge precheck (#91).
reflection:
    bash deploy/wsl/reflection.sh

# Inside the clean distro only: install the Claude shelf .claude/settings.json declares. See docs/start.md.
shelf:
    bash deploy/wsl/shelf.sh

# Inside the clean distro only, from the main checkout: the hard-line rules' Codex, Antigravity and dsh user layers.
hard-lines:
    bash deploy/wsl/hard-lines/install.sh

# Inside the clean distro only: issue #62's pinned native Orca CLI roster.
lane-runtimes:
    bash deploy/wsl/lane-runtimes/install.sh

# Durable fresh router, through upstream's own systemd unit generator; run from main after handover.
omniroute *args:
    bash deploy/wsl/lane-runtimes/service.sh {{args}}

# Inside the clean distro only: AO at its pin, its daemon tab, and the hand-off of a lane PR. See docs/start.md.
ao *args:
    bash deploy/wsl/ao.sh {{args}}

# Inside the clean distro only: OmniRoute's per-runtime keys: status, due or renew. See issue #94.
omni-keys *args:
    python3 -I scripts/omni_keys.py {{args}}

# Inside the clean distro only: the Sextant GitHub App's own rate budget for AO and the lane tabs. See docs/start.md.
gh-app *args:
    bash deploy/wsl/github-app.sh {{args}}

# Run every manifest row's proof. Pass a -m expression; the scoreboard passes "not local".
prove marker="":
    uv run --frozen pytest tests/proofs -m "{{marker}}"

# Import a disposable copy of the committed research docs into local OpenViking.
index:
    bash deploy/openviking/index.sh

# Score `qmd search` on this repo's gold queries with qmd's own bench harness, BM25 only, no model.
qmd-bench fixture="docs/research/2026-11-06-qmd-bench/fixture.json":
    qmd update >&2
    node --input-type=module -e "const { runBenchmark } = await import(process.argv[1] + '/../dist/bench/bench.js'); await runBenchmark(process.argv[2], { json: true, backends: ['bm25'], dbPath: '.qmd/index.sqlite', configPath: '.qmd/index.yml' });" "$(dirname "$(readlink -f "$(command -v qmd)")")" "{{fixture}}"

# Opt into the pinned OMC plugin for this Claude session (native settings precedence).
omc:
    claude --settings '{"env":{"DISABLE_OMC":"0"},"enabledPlugins":{"oh-my-claudecode@omc":true}}'

# The trading path: research card, backtest, sim replay, ledger, merit page.
slice:
    uv run --frozen python -m sextant.backtest.thin_slice

# Push a branch and open its PR; pass false as the third argument to leave auto-merge off.
pr title body_file automerge="true":
    git push -u origin HEAD
    gh pr create --title "{{title}}" --body-file "{{body_file}}"
    if [[ "{{automerge}}" == true ]]; then gh pr merge --auto --squash; fi
