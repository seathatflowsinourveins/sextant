#!/usr/bin/env bash
# OpenViking v0.5.3: quickstart import, CLI AddResourceArgs; no ingestion mechanism of our own.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

# Keep each revision's source and URI together. Only git's tracked docs become a disposable copy.
revision=$(git rev-parse HEAD)
mkdir -p "$HOME/.local/share/sextant-openviking/corpus"
corpus=$(mktemp -d "$HOME/.local/share/sextant-openviking/corpus/$revision.XXXXXX")
git archive HEAD docs | tar -x -C "$corpus"
export OPENVIKING_CLI_CONFIG_FILE="$PWD/deploy/openviking/ovcli.conf"
ov add-resource "$corpus/docs" --to "viking://resources/sextant/$revision" \
  --processing-mode vectors_only --reason '' --watch-interval 0 --wait
