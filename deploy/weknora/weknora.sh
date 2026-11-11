#!/usr/bin/env bash
# WeKnora's documented Compose commands (02-installation.md:48-68) on default services, files pinned;
# keys only from with-keys.sh, never to a command (config, logs, -f, --profile) that could print them.
set -euo pipefail
set +x
refuse() { echo "weknora: only up -d | pull | ps | down [-v], on default services" >&2; exit 2; }
case "${1:-}" in
  up) [[ "${2:-}" == -d ]] || refuse; skip=2 ;;
  down) [[ "${2:-}" == -v ]] && skip=2 || skip=1 ;;
  pull | ps) skip=1 ;;
  *) refuse ;;
esac
for arg in "${@:skip+1}"; do
  case "$arg" in app | frontend | docreader | postgres | redis | embeddings) ;; *) refuse ;; esac
done
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
pins="$here/pins.json"
commit=$(jq -er .weknora.commit "$pins")
upstream="$HOME/.local/share/sextant-weknora/upstream/$commit"
mkdir -p "$upstream/config"
for file in docker-compose.yml config/config.yaml; do
  want=$(jq -er --arg f "$file" '.weknora.files[$f]' "$pins")
  echo "$want  $upstream/$file" | sha256sum -c --status 2> /dev/null && continue
  fetched=$(mktemp "$upstream/.fetch.XXXXXX")
  curl -fsSL -o "$fetched" "https://raw.githubusercontent.com/Tencent/WeKnora/$commit/$file"
  echo "$want  $fetched" | sha256sum -c --status || { rm -f -- "$fetched"; echo "weknora: $file at $commit does not match pins.json" >&2; exit 1; }
  mv -f -- "$fetched" "$upstream/$file"
done
# mktemp's 0600 would hide the bind-mounted config from the app's own non-root user.
chmod 644 "$upstream/docker-compose.yml" "$upstream/config/config.yaml"
# The app's env_file must exist (02-installation.md:68); it stays empty.
touch "$upstream/.env"
[[ $1 != up ]] || for name in DB_PASSWORD REDIS_PASSWORD JWT_SECRET SYSTEM_AES_KEY; do
  [[ -n "${!name:-}" ]] || { echo "weknora: $name is unset; start through scripts/with-keys.sh" >&2; exit 3; }
done
export DB_USER=weknora DB_NAME=weknora
WEKNORA_EMBEDDING_IMAGE=$(jq -er .embedding.image "$pins")
WEKNORA_EMBEDDING_FILE=$(jq -er .embedding.file "$pins")
WEKNORA_EMBEDDING_ARGS=$(jq -er .embedding.args "$pins")
export WEKNORA_EMBEDDING_IMAGE WEKNORA_EMBEDDING_FILE WEKNORA_EMBEDDING_ARGS
# Env forms of -f, --profile, --env-file (compose/how-tos/environment-variables/envvars).
unset COMPOSE_FILE COMPOSE_PROFILES COMPOSE_ENV_FILES
exec docker compose --project-name "${WEKNORA_PROJECT:-sextant-weknora}" \
  -f "$upstream/docker-compose.yml" -f "$here/compose.override.yaml" "$@"
