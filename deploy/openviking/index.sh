#!/usr/bin/env bash
# OpenViking v0.5.3 (volcengine/OpenViking@178a8cdfb41b51e7d24c4bf79a13cc54981e0ee8): the CLI's own add-resource,
# stat, ls and rm; no ingestion mechanism of our own. Every embedding setting stays in ov.conf.
# - The URI names the commit whose tracked docs/ it holds, so a citation names the revision it read.
# - add-resource --to an existing directory refreshes it in place (docs/en/api/02-resources.md:182,216), so the
#   next run repairs a failed import. The CLI zips and uploads a local directory (crates/ov_cli/src/client.rs:
#   942-958), so the copy is deleted once the call returns.
# - Only after the import succeeds and stats is every other revision removed (ov rm, docs/en/api/03-filesystem.md:
#   599-604), so find returns one revision.
# Default: main as git's hourly prefetch last fetched it (git-maintenance(1), prefetch; lifecycle.sh registers
# it), or origin/main before the first prefetch.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

main=refs/prefetch/remotes/origin/main
git rev-parse --quiet --verify "$main" > /dev/null || main=origin/main
revision=$(git rev-parse --verify "${1:-$main}^{commit}")
root=viking://resources/sextant
target="$root/$revision"
state="$HOME/.local/share/sextant-openviking"
mkdir -p "$state/corpus"
exec 9> "$state/index.lock"
flock 9
export OPENVIKING_CLI_CONFIG_FILE="$PWD/deploy/openviking/ovcli.conf"

if [[ "$(cat "$state/indexed-revision" 2> /dev/null)" != "$revision" ]] || ! ov stat "$target" > /dev/null 2>&1; then
  corpus=$(mktemp -d "$state/corpus/$revision.XXXXXX")
  trap 'rm -rf -- "$corpus"' EXIT
  git archive "$revision" docs | tar -x -C "$corpus"
  ov add-resource "$corpus/docs" --to "$target" \
    --processing-mode vectors_only --reason '' --watch-interval 0 --wait
  ov stat "$target" > /dev/null
  printf '%s\n' "$revision" > "$state/indexed-revision"
fi

listing=$(ov ls --simple "$root")
mapfile -t revisions < <(sed -n -E "s|^($root/[0-9a-f]{40})\$|\1|p" <<< "$listing")
for old in "${revisions[@]}"; do
  [[ "$old" == "$target" ]] || ov rm --recursive "$old"
done
