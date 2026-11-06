# Run inside the sandbox: `devc up`, then `devc shell`.
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Install the locked Python dependencies.
sync:
    uv sync --frozen

# Everything the required `ci` check runs.
ci: sync lint test secrets

lint:
    uv run --frozen ruff check .
    uv run --frozen ruff format --check .
    uv run --frozen pyright
    uv run --frozen zizmor --offline .github/workflows
    actionlint .github/workflows/ci.yml .github/workflows/source.yml .github/workflows/scoreboard.yml .github/workflows/dependabot-automerge.yml

test:
    uv run --frozen pytest

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

# Inside the clean distro only: install the Claude shelf .claude/settings.json declares. See docs/start.md.
shelf:
    bash deploy/wsl/shelf.sh

# Inside the clean distro only: AO at its pin, its daemon tab, and the hand-off of a lane PR. See docs/start.md.
ao *args:
    bash deploy/wsl/ao.sh {{args}}

# Inside the clean distro only: the Sextant GitHub App's own rate budget for AO and the lane tabs. See docs/start.md.
gh-app *args:
    bash deploy/wsl/github-app.sh {{args}}

# Run every manifest row's proof. pytest does the running and the counting.
prove:
    uv run --frozen pytest tests/proofs

# Import a disposable copy of the committed research docs into local OpenViking.
index:
    bash deploy/openviking/index.sh

# Opt into the pinned OMC plugin for this Claude session (native settings precedence).
omc:
    claude --settings '{"env":{"DISABLE_OMC":"0"},"enabledPlugins":{"oh-my-claudecode@omc":true}}'

# The trading path: research card, backtest, sim replay, ledger, merit page.
slice:
    uv run --frozen python -m sextant.backtest.thin_slice

# Push this branch, open its PR from a filled-in template, turn on auto-merge.
pr title body_file:
    git push -u origin HEAD
    gh pr create --title "{{title}}" --body-file "{{body_file}}"
    gh pr merge --auto --squash
