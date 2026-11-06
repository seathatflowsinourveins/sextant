#!/usr/bin/env bash
# OmniRoute 3.8.53's documented serve/env contract, in Sextant's own data directory.
set -euo pipefail
set +x
prefix="$HOME/.local/share/sextant-lane-runtimes"
IFS= read -r repository < "$prefix/repository-path"
if [[ $# == 0 ]]; then set -- serve --port 22128 --no-open; fi
exec "$repository/scripts/with-keys.sh" --strict \
  -k OMNIROUTE_API_KEY -k OMNIROUTE_JWT_SECRET:JWT_SECRET \
  -k OMNIROUTE_API_KEY_SECRET:API_KEY_SECRET \
  -k OMNIROUTE_STORAGE_ENCRYPTION_KEY:STORAGE_ENCRYPTION_KEY \
  -k OMNIROUTE_CLI_SALT -- env \
  DATA_DIR="$prefix/router-data" OMNIROUTE_BASE_URL=http://127.0.0.1:22128 \
  OMNIROUTE_SERVER_HOST=127.0.0.1 PORT=22128 REQUIRE_API_KEY=true INITIAL_PASSWORD= \
  OMNIROUTE_NO_UPDATE_NOTIFIER=1 \
  "$prefix/router/node_modules/.bin/omniroute" "$@"
