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
    actionlint

test:
    uv run --frozen pytest

# Scan this PR's commits when CI gives a range, otherwise the working tree.
secrets:
    if [[ -n "${BASE_SHA:-}" && -n "${HEAD_SHA:-}" ]]; then gitleaks git --no-banner --redact --log-opts="$BASE_SHA..$HEAD_SHA" .; else gitleaks dir --no-banner --redact .; fi

# Run every manifest row's proof. pytest does the running and the counting.
prove:
    uv run --frozen pytest tests/proofs

# Push this branch, open its PR from a filled-in template, turn on auto-merge.
pr title body_file:
    git push -u origin HEAD
    gh pr create --title "{{title}}" --body-file "{{body_file}}"
    gh pr merge --auto --squash
