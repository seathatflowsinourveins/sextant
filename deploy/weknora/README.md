# WeKnora: disposable research retrieval for dsh workers

[Tencent/WeKnora](https://github.com/Tencent/WeKnora) v0.9.0 (`f17ee8a8da901bd658a4cb25f40b5fd41adbfdd7`) holds the pinned upstream sources the manifest cites: NautilusTrader's and alpaca-py's `docs/` at the commits in [pins.json](pins.json). OpenViking keeps the house records. Neither is a memory: no conversation capture, no agent-session writes, no URL ingestion. dsh reaches it only from its `worker` profile, through WeKnora's own plugin, with a key that can only retrieve.

## What runs

Upstream's standard Compose deployment (`website-docs/01-getting-started/02-installation.md:48-92`), started as `up -d app`: `app`, `postgres`, `redis`, `docreader`, plus a copy of the house embeddings server (rootless Docker hides host loopback; about 1.1 GiB of RAM). [weknora.sh](weknora.sh) fetches upstream's compose and config at the commit, checks their sha256 against `pins.json`, and adds [compose.override.yaml](compose.override.yaml): images by digest, the API on `127.0.0.1:21937` only, whitelist-only outbound, redis reading its password from its environment on stdin, never argv or a file. It runs only upstream's `up -d`, `pull`, `ps`, `down [-v]`, on only the default services, and clears `COMPOSE_PROFILES`. No chat model is needed: summaries and `ask` are off. alpaca-py's `.rst` docs go up as plain text with `.txt` appended.

## Install

The owner, once (no value reaches a command line or file):

```sh
for name in DB_PASSWORD REDIS_PASSWORD JWT_SECRET ADMIN_PASSWORD; do openssl rand -hex 32 | scripts/keys.sh set "WEKNORA_$name"; done
openssl rand -hex 16 | scripts/keys.sh set WEKNORA_SYSTEM_AES_KEY
```

Then, from the main checkout (needs OpenViking's models):

```sh
scripts/with-keys.sh --strict -k WEKNORA_DB_PASSWORD:DB_PASSWORD -k WEKNORA_REDIS_PASSWORD:REDIS_PASSWORD -k WEKNORA_JWT_SECRET:JWT_SECRET -k WEKNORA_SYSTEM_AES_KEY:SYSTEM_AES_KEY -- bash deploy/weknora/weknora.sh up -d app
scripts/with-keys.sh --strict -k WEKNORA_ADMIN_PASSWORD -- python3 -I deploy/weknora/weknora.py bootstrap
scripts/with-keys.sh --strict -k WEKNORA_ADMIN_PASSWORD -- python3 -I deploy/weknora/weknora.py ingest
scripts/with-keys.sh --strict -k WEKNORA_ADMIN_PASSWORD -- python3 -I deploy/weknora/weknora.py retrieve-key | scripts/keys.sh set WEKNORA_API_KEY
```

The worker profile is dsh's headless template plus `packages/dsh-weknora` at the pinned commit (npm's 0.1.0 is older), so `headless` runs (blind legs, AO, the gate) never load it. dsh runs the plugin's `prepare` build only for the exact tarball `pins.json`'s `allowBuilds` key names. Setup uses the sandbox's dsh, as `deploy/wsl/hard-lines/install.sh` does; the run uses the keyed `dsh`:

```sh
bare=~/.local/share/sextant-agents/node_modules/.bin/dsh pins=deploy/weknora/pins.json
"$bare" --profile worker --from-default-profile headless --dump-config > /dev/null
jq -r '"allowBuilds:\n  \"" + ."dsh-weknora".allow_build + "\": true"' "$pins" >> ~/.dsh/profiles/worker/pnpm-workspace.yaml
"$bare" plugin --profile worker add "$(jq -r '."dsh-weknora".spec' "$pins")"
scripts/with-keys.sh --strict -k WEKNORA_API_KEY -- dsh --profile worker --patch config/dsh/weknora.cordis.yml "job"
```

## Verify

`ingest` prints upload and parse counts; `weknora.sh ps` shows only `127.0.0.1:21937` published; `weknora_search` cites file, chunk and `knowledge_id`; the retrieve key gets 403 on writes. The worker's startup receipt reports the providers this lean profile lacks as not active: a diagnostic, not a gate.

## When the embedding model changes

`pins.json`'s `embedding` entry is the one place for model, image, arguments, dimension and endpoint; `test_weknora.py` holds it equal to `deploy/openviking`'s. New model, new vectors: `down -v`, then Install from `up` again, re-ingesting both knowledge bases.

## Removal

```sh
bash deploy/weknora/weknora.sh down -v
~/.local/share/sextant-agents/node_modules/.bin/dsh plugin --profile worker remove @wxg-prc-cpg/dsh-weknora
rm -r ~/.local/share/sextant-weknora
for name in DB_PASSWORD REDIS_PASSWORD JWT_SECRET SYSTEM_AES_KEY ADMIN_PASSWORD API_KEY; do scripts/keys.sh rm "WEKNORA_$name"; done
```

`down -v` removes the containers, network and the three volumes. Left: the pulled images (digests in `pins.json`), `~/.dsh/profiles/worker` and its `allowBuilds` line, and OpenViking's models directory.
