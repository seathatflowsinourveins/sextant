#!/usr/bin/env bash
# One REST JIT configuration + one disposable Docker runner, following actions/scaleset's
# dockerscaleset/startRunner. systemd replaces this process; there is no GitHub polling loop.
# GitHub routes jobs by runner label, and each instance is its own serial slot (one instance of
# sextant-jit@.service): `sealed` jobs, including ci's PR code, never reach the daemon and get a
# user-defined bridge of their own; `docker` jobs are trusted base-branch code that needs it
# (gh-aw's AWF in its arc-dind topology, devcontainers/ci). The docker profile's slots share the
# one `sextant-jit-docker` label; `limits.json` bounds how many may exist.
set +x
set -Eeuo pipefail
ulimit -c 0
umask 077
installed=/usr/local/lib/sextant-jit
repository=seathatflowsinourveins/sextant
review_runtime=/run/user/1501
review_uid=1501
gh_aw_tmp=/tmp/gh-aw
subuid_file=/etc/subuid

# The producer's Docker CLI reads a root-owned, empty configuration, so no CLI plugin or credential
# helper planted in UID 1501's ~/.docker runs on the host (Docker CLI `DOCKER_CONFIG`). Buildx keeps
# its state in $BUILDX_CONFIG, else under $DOCKER_CONFIG (Docker "Build variables"), so a builder
# command names a fresh state directory in `buildx_state`.
docker() {
  local buildx=()
  [[ -z ${buildx_state:-} ]] || buildx=(BUILDX_CONFIG="$buildx_state")
  sudo -n -u sextant-review env XDG_RUNTIME_DIR="$review_runtime" \
    DOCKER_HOST="unix://$review_runtime/docker.sock" DOCKER_CONFIG="$installed/docker-config" \
    "${buildx[@]}" /usr/bin/docker "$@"
}

# The rootless daemon's namespaces (Docker rootless troubleshooting, "Entering into dockerd
# namespaces": nsenter -U --preserve-credentials -n -m -t $(cat $XDG_RUNTIME_DIR/docker.pid)).
in_daemon_ns() {
  local pid
  pid=$(sudo -n -u sextant-review cat "$review_runtime/docker.pid") || return 1
  [[ $pid =~ ^[0-9]+$ ]] || return 1
  sudo -n -u sextant-review nsenter -U --preserve-credentials -n -m -t "$pid" "$@"
}

runner_labels() {
  case $1 in
    sealed | docker) printf '%s\n' self-hosted linux x64 "sextant-jit-$1" ;;
    *) return 2 ;;
  esac
}

# The systemd instance name is the slot. `sealed` keeps its original name; `docker` is the
# original single docker slot and aliases `docker-1`. `limits.json` bounds the highest slot.
slot_identity() {
  local instance=${1:-}
  if [[ $instance == sealed ]]; then
    profile=sealed slot=1 slot_name=sealed
  elif [[ $instance =~ ^docker(-([1-9][0-9]*))?$ ]]; then
    profile=docker slot=${BASH_REMATCH[2]:-1} slot_name="docker-${BASH_REMATCH[2]:-1}"
  else
    return 2
  fi
}

# Only `docker` sees the daemon: its socket, the loopback TCP API that gh-aw's arc-dind probe
# requires (a tcp:// DOCKER_HOST), and RootlessKit's namespace network where that API listens.
# The runner and the daemon also share the host's /tmp (sweep_host_tmp). $HOME is the job root,
# as the official image's is the runner directory and ARC's work directory sits under it: AWF's
# agent writes its Claude config to /host$HOME (containers/agent/entrypoint.sh:241), which exists
# only as the parent of the job's mounts under /host$root.
runner_options() {
  local profile=$1 root=$2 name=$3 slot_name=${4:-$1}
  runner_labels "$profile" >/dev/null || return 2
  printf '%s\n' --label "sextant-jit.profile=$profile" \
    --label "sextant-jit.slot=$slot_name" \
    --mount "type=bind,src=$root,dst=$root" --env "SEXTANT_JIT_ROOT=$root"
  if [[ $profile == sealed ]]; then
    printf '%s\n' --network "$name" --env HOME=/home/runner
  else
    printf '%s\n' --network host --env "HOME=$root" \
      --mount type=bind,src=/tmp,dst=/tmp \
      --mount "type=bind,src=$review_runtime/docker.sock,dst=$review_runtime/docker.sock" \
      --env DOCKER_HOST=tcp://127.0.0.1:2375 \
      --env "GH_AW_DOCKER_SOCK_PATH=$review_runtime/docker.sock"
  fi
}

# Fail closed unless the live daemon runs as installed: RootlessKit's own network namespace, no
# port driver, no host loopback, and published ports bound to loopback. A job that rewrites the
# user's Docker drop-in cannot weaken this unnoticed.
daemon_as_installed() {
  local rootlesskit dockerd
  rootlesskit=$(pgrep -u sextant-review -a -x rootlesskit) || return 1
  dockerd=$(pgrep -u sextant-review -a -x dockerd) || return 1
  [[ "$rootlesskit " == *" --port-driver=none "* && "$rootlesskit " == *" --disable-host-loopback "* &&
    "$rootlesskit" != *"--detach-netns"* ]] || return 1
  [[ "$dockerd " == *" --ip=127.0.0.1 "* && "$dockerd" == *"host_binding_ipv4=127.0.0.1"* ]]
}

# Sealed egress, through Docker's DOCKER-USER chain ("Docker with iptables": processed before
# Docker's rules) inside RootlessKit's namespace: the sealed subnet reaches the internet and the
# namespace's DNS forwarder, but no private (RFC 1918), shared (RFC 6598, tailnets) or link-local
# (RFC 3927) address, so neither the LAN, the tailnet nor a host listener. Rebuilt before every
# sealed start; a failure stops the slot.
sealed_egress() {
  # shellcheck disable=SC2016 # the script expands inside the daemon namespace's sh
  in_daemon_ns sh -euc '
    subnet=$1 resolv=${2:-/etc/resolv.conf}
    iptables -N SEXTANT-SEALED 2>/dev/null || iptables -F SEXTANT-SEALED
    for dns in $(sed -n "s/^nameserver[[:space:]]\{1,\}//p" "$resolv"); do
      case $dns in *:*) continue ;; esac
      iptables -A SEXTANT-SEALED -d "$dns" -p udp --dport 53 -j RETURN
      iptables -A SEXTANT-SEALED -d "$dns" -p tcp --dport 53 -j RETURN
    done
    for range in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16; do
      iptables -A SEXTANT-SEALED -d "$range" -j DROP
    done
    iptables -C DOCKER-USER -s "$subnet" -j SEXTANT-SEALED 2>/dev/null ||
      iptables -I DOCKER-USER -s "$subnet" -j SEXTANT-SEALED
  ' sh "$@"
}

# gh-aw expects a runner and its daemon to share one /tmp: its setup removes and recreates
# /tmp/gh-aw (setup.sh:105-130), the daemon mounts literal /tmp/gh-aw sources (start_cli_proxy.sh:
# 107-164), and its MCP gateway mounts /tmp itself. This daemon's /tmp is the host's, so docker jobs
# share the host's /tmp; AWF also mounts it into its agent (system-mounts.ts:29). Around each job
# the slot removes what its containers left there: /tmp/gh-aw, and every entry at any depth owned
# by UID 1501's subordinate range, which only this daemon's containers use. Someone else's
# /tmp/gh-aw stops the slot.
sweep_host_tmp() {
  local first count owner
  IFS=: read -r _ first count < <(grep -m1 '^sextant-review:' "$subuid_file") || return 1
  [[ $first =~ ^[0-9]+$ && $count =~ ^[0-9]+$ ]] || return 1
  if [[ -e "$gh_aw_tmp" || -L "$gh_aw_tmp" ]]; then
    owner=$(stat -c %u -- "$gh_aw_tmp")
    (( owner == review_uid || (owner >= first && owner < first + count) )) || {
      echo "$gh_aw_tmp belongs to uid $owner, not to the docker slot" >&2; return 1;
    }
    sudo -n rm -rf -- "$gh_aw_tmp" || return 1
  fi
  sudo -n find "${gh_aw_tmp%/*}" -xdev -mindepth 1 -uid "+$((first - 1))" -uid "-$((first + count))" \
    -prune -exec rm -rf -- {} +
}

# Prune the build cache with an empty buildx state directory, removed afterwards. A leftover after
# SIGKILL matches the docker profile's root sweep in cleanup.
builder_prune() {
  local state status=0
  state=$(sudo -n -u sextant-review mktemp -d \
    "$review_runtime/sextant-jit-${slot_name:-docker}.buildx.XXXXXXXX") ||
    return 1
  buildx_state=$state docker builder prune --all --force >/dev/null || status=1
  sudo -n rm -rf -- "$state" || status=1
  return "$status"
}

# The daemon is shared: each slot removes only its own runner containers. The original single
# docker slot left containers without a slot label, so docker-1 also removes those leftovers;
# docker-2 never touches another slot's containers.
owned_containers() {
  local slot=$1 profile legacy=0
  case $slot in
    sealed) profile=sealed legacy=1 ;;
    docker) slot=docker-1 profile=docker legacy=1 ;;
    docker-[1-9]*) profile=docker ;;
    *) return 2 ;;
  esac
  [[ $slot == docker-1 ]] && legacy=1
  docker ps --all --no-trunc --format \
    '{{.ID}} {{.Label "sextant-jit.profile"}} {{.Label "sextant-jit.slot"}}' |
    awk -v slot="$slot" -v profile="$profile" -v legacy="$legacy" \
      '$3 == slot || (legacy && $3 == "" && $2 == profile) {print $1}'
}

# True when another docker slot still has a runner on the shared daemon. Two concurrent docker
# agent jobs are unsupported while gh-aw's setup removes and recreates the fixed /tmp/gh-aw, so
# cleanup must not prune a peer's networks, volumes, images or tmp entries.
docker_peer_active() {
  [[ ${profile:-} == docker ]] || return 1
  docker ps --filter label=sextant-jit.profile=docker \
    --format '{{.Label "sextant-jit.slot"}}' |
    awk -v self="${slot_name:-docker}" '$0 != self {found=1} END {exit found ? 0 : 1}'
}

# A docker job may leave sibling containers without either sextant-jit label. Only a slot that
# finds no live peer may remove them: a peer's job may still own them.
remove_unlabeled_siblings() {
  local ids=()
  mapfile -t ids < <(docker ps --all --no-trunc \
    --format '{{.ID}} {{.Label "sextant-jit.profile"}}' |
    awk '$2 == "" {print $1}') && wait "$!" || return 1
  (( ${#ids[@]} )) || return 0
  docker rm --force --volumes "${ids[@]}" >/dev/null 2>&1 || true
}

cleanup() {
  local ids=() attached=() net
  mapfile -t ids < <(owned_containers "$slot_name") && wait "$!" || return 1
  if (( ${#ids[@]} )); then
    # A --rm container may already be removing itself (409), so wait, bounded, until all are gone.
    docker rm --force --volumes "${ids[@]}" >/dev/null 2>&1 || true
    for _ in {1..30}; do
      mapfile -t ids < <(owned_containers "$slot_name") && wait "$!" || return 1
      (( ${#ids[@]} )) || break
      sleep 1
    done
    (( ${#ids[@]} == 0 )) || return 1
  fi
  if [[ $profile == sealed ]]; then
    mapfile -t ids < <(docker network ls --quiet --filter label=sextant-jit.profile=sealed) &&
      wait "$!" || return 1
    for net in "${ids[@]}"; do
      mapfile -t attached < <(docker network inspect --format \
        '{{range $id, $e := .Containers}}{{println $id}}{{end}}' "$net") && wait "$!" || return 1
      for id in "${attached[@]}"; do
        [[ -z "$id" ]] || docker network disconnect --force "$net" "$id" >/dev/null || return 1
      done
      docker network rm "$net" >/dev/null || return 1
    done
  else
    # Leave no job networks, volumes, images or build caches; the seed archive is reloaded. Only the
    # sealed slot's live network is spared; nothing else of the sealed profile lives on the daemon.
    # A live peer docker slot owns these daemon-wide resources and the fixed /tmp/gh-aw, so wait.
    if ! docker_peer_active; then
      remove_unlabeled_siblings || return 1
      docker network prune --force --filter label!=sextant-jit.profile=sealed >/dev/null || return 1
      docker volume prune --all --force >/dev/null || return 1
      docker image prune --all --force >/dev/null || return 1
      builder_prune || return 1
      sweep_host_tmp || return 1
    fi
  fi
  # Also erase this slot's earlier tmpfs roots after SIGKILL or a host crash. docker-1 also clears
  # the original single docker slot's `sextant-jit-docker.*` roots.
  sudo -n find "$review_runtime" -mindepth 1 -maxdepth 1 -type d \
    -name "sextant-jit-$slot_name.*" -exec rm -rf -- {} +
  if [[ $slot_name == docker-1 ]]; then
    sudo -n find "$review_runtime" -mindepth 1 -maxdepth 1 -type d \
      -name "sextant-jit-$profile.*" -exec rm -rf -- {} +
  fi
}

# The REST response's runner id is not secret; the encoded configuration streams on to the
# container's stdin without entering a shell variable.
record_runner_id() {
  local id
  IFS= read -r id && [[ $id =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$id" >"$runner_id_file"
  exec cat
}

# One removal with this producer's gh login (GitHub REST "Delete a self-hosted runner from a
# repository"). Like ARC's removeRunnerOfLivePod, a missing runner counts as removed.
remove_runner() {
  local out
  out=$(gh api --method DELETE "repos/$repository/actions/runners/$1" 2>&1 >/dev/null) && return 0
  [[ $out == *"HTTP 404"* ]] && return 0
  echo "JIT runner $1: deregistration refused (${out##*$'\n'}); retried at the next start" >&2
  return 1
}

# Owner, 2026-11-07: "Accept + add exit cleanup". Every teardown removes this runner's registration,
# because a runner also exits 0 without finishing a job (actions/runner run-helper.sh; ARC
# runner_unregistration.go). A refusal, such as a job the service still holds, is retried at the
# next start. A stop during the POST may leave no recorded id, so the runner is found by name.
deregister() {
  local id='' ids=() kept=()
  [[ -s "$pending_file" ]] && mapfile -t ids <"$pending_file"
  [[ -s "$runner_id_file" ]] && id=$(<"$runner_id_file")
  if [[ -z "$id" && -n "${name:-}" ]]; then
    id=$(gh api "repos/$repository/actions/runners?name=$name" --jq '.runners[0].id // empty') ||
      id=''
  fi
  [[ -n "$id" ]] && ids+=("$id")
  for id in "${ids[@]}"; do
    [[ $id =~ ^[0-9]+$ ]] || continue
    remove_runner "$id" || kept+=("$id")
  done
  if (( ${#kept[@]} )); then printf '%s\n' "${kept[@]}" >"$pending_file"; else rm -f -- "$pending_file"; fi
  rm -f -- "$runner_id_file"
}

# A JIT runner that exits without having started a job failed (refused configuration, session
# conflict, killed listener), even when run-helper.sh reports 0. The marker is checked as root,
# because the job root belongs to the container's non-root runner user.
runner_status() {
  if (( $1 == 0 )) && ! sudo -n test -e "$root/.job-started"; then
    echo "JIT runner $name exited without starting a job" >&2
    return 1
  fi
  return "$1"
}

on_exit() {
  local status=$?
  trap - EXIT
  trap '' INT TERM  # a second signal must not cut the cleanup short
  # Stop this slot's own runner first; removing one recorded container needs no daemon lock.
  if [[ -n "${container:-}" ]]; then docker rm --force "$container" >/dev/null 2>&1 || true; fi
  # The rest waits at most 60 s for the other slot, inside TimeoutStopSec. A skipped cleanup is
  # redone by the next start.
  { flock --wait 60 8 && cleanup; } || status=1
  deregister
  exit "$status"
}

arm_exit() {
  trap on_exit EXIT
  trap 'exit 130' INT TERM
}

# The whole-account cap must hold every slot's hard limit plus the daemon's measured RSS.
cap_covers_slots() {
  (( cap * 1024 >= slot_count * slot_gib * 1024 + overhead_mib ))
}

main() {
  local instance=${1:-}
  slot_identity "$instance" || { echo 'usage: jit.sh sealed|docker[-N]' >&2; exit 2; }
  runner_labels "$profile" >/dev/null || exit 2
  exec 9>"${XDG_RUNTIME_DIR:?}/sextant-jit-$slot_name.lock"
  flock -n 9 || exit 1
  runner_id_file=$XDG_RUNTIME_DIR/sextant-jit-$slot_name.runner
  pending_file=$XDG_RUNTIME_DIR/sextant-jit-$slot_name.pending
  # At boot, UID 1501's lingering manager and the network come up independently of this manager.
  boot_wait=$(jq -r .boot_wait_seconds.value "$installed/limits.json")
  for (( waited = 0; waited < boot_wait; waited += 5 )); do
    docker info >/dev/null 2>&1 && break
    sleep 5
  done
  docker info >/dev/null 2>&1 || { echo "UID 1501's daemon not up after ${boot_wait}s" >&2; exit 1; }
  daemon_as_installed || { echo 'the live daemon does not match the installed drop-in' >&2; exit 1; }
  [[ $(stat -f -c %T "$review_runtime") == tmpfs ]]
  floor=$(jq -r .memory_floor_gib.value "$installed/limits.json")
  cap=$(jq -r .memory_max_gib.value "$installed/limits.json")
  slot_gib=$(jq -r .slot_memory_gib.value "$installed/limits.json")
  slot_count=$(jq -r '[.slots.value[]] | add' "$installed/limits.json")
  slot_limit=$(jq -r --arg profile "$profile" '.slots.value[$profile] // empty' "$installed/limits.json")
  overhead_mib=$(jq -r .memory_overhead_mib.value "$installed/limits.json")
  sealed_subnet=$(jq -r .sealed_subnet.value "$installed/limits.json")
  [[ $slot_count =~ ^[1-9][0-9]*$ && $slot_limit =~ ^[1-9][0-9]*$ ]] || {
    echo "limits.json has no slot count for $profile" >&2; exit 1;
  }
  (( slot <= slot_limit )) || {
    echo "JIT admission refused: $instance exceeds the $profile slot count" >&2; exit 1;
  }
  cap_covers_slots || {
    echo 'JIT admission refused: the whole-account cap does not hold every slot and the daemon' >&2; exit 1;
  }
  available_kib=$(awk '$1 == "MemAvailable:" {print $2}' /proc/meminfo)
  (( available_kib >= (floor + slot_gib) * 1024 * 1024 )) || {
    echo 'JIT admission refused: insufficient MemAvailable for the floor plus one slot' >&2; exit 1;
  }
  [[ $(systemctl show user-1501.slice -p MemoryMax --value) == "$((cap * 1024 * 1024 * 1024))" ]]
  docker info --format '{{json .SecurityOptions}}' | jq -e 'index("name=rootless") != null' >/dev/null
  for (( waited = 0; waited < boot_wait; waited += 10 )); do
    private=$(gh api "repos/$repository" --jq .private 2>/dev/null) && break
    sleep 10
  done
  [[ ${private:-} == true ]] || { echo 'GitHub did not confirm a private repository' >&2; exit 1; }
  image=$(cat "$installed/runner-image")
  [[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]]
  # Both slots share the daemon: cleanup, seed load and container creation run one at a time,
  # and cleanup must succeed before any new runner can start, including after a killed process.
  exec 8>"$XDG_RUNTIME_DIR/sextant-jit-daemon.lock"
  flock --wait 300 8
  arm_exit  # before cleanup: a failed cleanup still deregisters leftovers on the way out
  cleanup
  deregister  # leftovers: a refused removal, or the id of a runner whose slot was SIGKILLed
  docker load --input /var/lib/sextant-jit/runner.tar >/dev/null
  [[ $(docker image inspect "$image" --format '{{.Id}}') == "$image" ]]
  root=$(sudo -n -u sextant-review mktemp -d "$review_runtime/sextant-jit-$slot_name.XXXXXXXX")
  name=${root##*/}
  if [[ $profile == sealed ]]; then
    sealed_egress "$sealed_subnet"
    docker network create --subnet "$sealed_subnet" --label sextant-jit.profile=sealed \
      --label "sextant-jit.slot=$slot_name" "$name" >/dev/null
  fi
  local options labels args=() label
  mapfile -t options < <(runner_options "$profile" "$root" "$name" "$slot_name")
  container=$(docker create --rm --interactive --name "$name" --user 0 \
    --memory "${slot_gib}g" --memory-swap "${slot_gib}g" --ulimit core=0 "${options[@]}" \
    --env "SEXTANT_RUNNER_IMAGE=$image" "$image")
  [[ "$container" =~ ^[0-9a-f]{64}$ ]]
  flock --unlock 8
  mapfile -t labels < <(runner_labels "$profile")
  for label in "${labels[@]}"; do args+=(-f "labels[]=$label"); done
  group=$(jq -r .runner_group_id.value "$installed/limits.json")
  # In the background, so a stop's SIGTERM runs the cleanup at once instead of after the timeout.
  {
    gh api --method POST "repos/$repository/actions/runners/generate-jitconfig" \
      -f name="$name" -F runner_group_id="$group" -f work_folder=_work "${args[@]}" \
      --jq '.runner.id, .encoded_jit_config' | record_runner_id |
      docker start --attach --interactive "$name"
  } &
  local status=0
  wait "$!" || status=$?
  runner_status "$status"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
