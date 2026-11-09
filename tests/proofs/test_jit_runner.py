"""Offline witnesses for the JIT boundary, alongside the real branch-dispatch receipt."""

import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).parents[2]
REVIEW = ROOT / "deploy" / "review"
WORKFLOWS = ROOT / ".github" / "workflows"
SEALED = ["self-hosted", "linux", "x64", "sextant-jit-sealed"]
DOCKER = ["self-hosted", "linux", "x64", "sextant-jit-docker"]


def _jit(call: str, expect_ok: bool = True) -> str:
    """Run one function of the installed launcher without its main body."""
    result = subprocess.run(
        ["bash", "-c", f'source "{REVIEW / "jit.sh"}"; {call}'],
        capture_output=True,
        text=True,
        env={"PATH": os.defpath},
        timeout=10,
    )
    assert (result.returncode == 0) == expect_ok, result.stderr
    return result.stdout


def _main(path: str) -> str:
    return subprocess.check_output(["git", "show", f"origin/main:{path}"], cwd=ROOT, text=True)


def test_only_the_docker_profile_reaches_the_daemon() -> None:
    root = "/run/user/1501/sextant-jit-sealed.fixture"
    sealed = _jit(f"runner_options sealed {root} sextant-jit-sealed.fixture").splitlines()
    assert not [o for o in sealed if "docker.sock" in o or "DOCKER_HOST" in o or "GH_AW_" in o]
    assert sealed[sealed.index("--network") + 1] == "sextant-jit-sealed.fixture"
    assert sealed.count("--network") == 1 and f"type=bind,src={root},dst={root}" in sealed
    assert "sextant-jit.profile=sealed" in sealed and "sextant-jit.slot=sealed" in sealed
    assert "HOME=/home/runner" in sealed
    assert not [o for o in sealed if "gh-aw" in o or "dst=/tmp" in o]
    docker = _jit(
        "runner_options docker /run/user/1501/sextant-jit-docker.f sextant-jit-docker.f"
    ).splitlines()
    assert docker[docker.index("--network") + 1] == "host"
    assert "type=bind,src=/run/user/1501/docker.sock,dst=/run/user/1501/docker.sock" in docker
    assert "DOCKER_HOST=tcp://127.0.0.1:2375" in docker
    # $HOME is the job root, the parent of every job mount AWF re-creates under /host$root.
    assert "HOME=/run/user/1501/sextant-jit-docker.f" in docker
    # gh-aw expects the runner and its daemon to share one /tmp; this daemon's /tmp is the host's.
    assert "type=bind,src=/tmp,dst=/tmp" in docker
    # gh-aw detects the socket's group itself; a forced group 0 locks out the non-root gateway.
    assert "GH_AW_DOCKER_SOCK_PATH=/run/user/1501/docker.sock" in docker
    assert not [o for o in docker if "GH_AW_DOCKER_SOCK_GID" in o]
    # Each docker slot carries its own label, so cleanup can tell the slots apart.
    docker2 = _jit(
        "runner_options docker /run/user/1501/x sextant-jit-docker-2.f docker-2"
    ).splitlines()
    assert "sextant-jit.profile=docker" in docker2
    assert "sextant-jit.slot=docker-2" in docker2
    # The producer's own Docker CLI never loads UID 1501's ~/.docker plugins or helpers.
    assert 'DOCKER_CONFIG="$installed/docker-config"' in (REVIEW / "jit.sh").read_text()
    assert _jit("runner_labels sealed").split() == SEALED
    assert _jit("runner_labels docker").split() == DOCKER
    _jit("runner_options everything /x y", expect_ok=False)
    _jit("runner_labels everything", expect_ok=False)


def test_slot_identities_are_bounded_and_distinct() -> None:
    assert _jit(
        'slot_identity sealed; printf \'%s %s %s\\n\' "$profile" "$slot" "$slot_name"'
    ).split() == ["sealed", "1", "sealed"]
    assert _jit(
        'slot_identity docker; printf \'%s %s %s\\n\' "$profile" "$slot" "$slot_name"'
    ).split() == ["docker", "1", "docker-1"]
    assert _jit(
        'slot_identity docker-2; printf \'%s %s %s\\n\' "$profile" "$slot" "$slot_name"'
    ).split() == ["docker", "2", "docker-2"]
    _jit("slot_identity docker-0", expect_ok=False)
    _jit("slot_identity sealed-1", expect_ok=False)


def test_each_slot_removes_only_its_own_containers() -> None:
    fake = (
        "docker() { printf '%s\\n' 'c1 sealed sealed' 'c2 docker docker-1' "
        "'c3 docker ' 'c4 docker docker-2' 'c5  '; }"
    )
    assert _jit(f"{fake}; owned_containers sealed").split() == ["c1"]
    assert _jit(f"{fake}; owned_containers docker-1").split() == ["c2", "c3"]
    assert _jit(f"{fake}; owned_containers docker-2").split() == ["c4"]
    assert _jit(f"{fake}; owned_containers docker").split() == ["c2", "c3"]
    # c5 has no profile or slot label: no runner owns it, but a docker cleanup must still remove it.


def test_unlabeled_siblings_are_removed_only_when_no_docker_peer_is_active(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()

    def cleanup_log(name: str, peer: int) -> Path:
        log = tmp_path / name
        _jit(
            f"""
            review_runtime={runtime}
            profile=docker
            slot_name=docker-2
            sudo() {{ :; }}
            builder_prune() {{ :; }}
            sweep_host_tmp() {{ :; }}
            docker_peer_active() {{ return {peer}; }}
            docker() {{
              printf '%s\\n' "$*" >> "{log}"
              case "$1" in
                ps) printf '%s\\n' 'c1 sealed sealed' 'c2 docker docker-1' 'c9  ' ;;
                *) : ;;
              esac
            }}
            cleanup
            """
        )
        return log

    no_peer = cleanup_log("no-peer.log", 1).read_text().splitlines()
    rm = no_peer.index("rm --force --volumes c9")
    prune = next(
        index
        for index, line in enumerate(no_peer)
        if line.startswith("network prune --force --filter label!=sextant-jit.profile=sealed")
    )
    assert rm < prune, "the unlabeled sibling must go before the daemon-wide prunes"

    peer = cleanup_log("peer.log", 0).read_text().splitlines()
    assert not [line for line in peer if line == "rm --force --volumes c9"]


def test_docker_slots_detect_a_live_peer_before_pruning_the_shared_daemon() -> None:
    peers = "docker() { printf '%s\\n' 'docker-2' 'docker-1'; }"
    _jit(f"profile=docker; slot_name=docker-1; {peers}; docker_peer_active")
    _jit(
        "profile=docker; slot_name=docker-2; "
        "docker() { printf '%s\\n' 'docker-2'; }; docker_peer_active",
        expect_ok=False,
    )
    _jit("profile=sealed; docker_peer_active", expect_ok=False)


def test_each_slot_is_a_boot_enabled_template_instance_that_stops_cleanly() -> None:
    unit = (REVIEW / "sextant-jit@.service").read_text().splitlines()
    for line in (
        "ExecStart=/usr/local/lib/sextant-jit/jit.sh %i",
        "Restart=always",
        "StartLimitIntervalSec=300",
        "StartLimitBurst=20",
        "SuccessExitStatus=130",
        "KillMode=mixed",
        "TimeoutStopSec=120",
        "WantedBy=default.target",
    ):
        assert line in unit, line
    assert not (REVIEW / "sextant-jit.service").exists()
    assert "flock --wait 60 8 && cleanup" in (REVIEW / "jit.sh").read_text()
    limits = json.loads((REVIEW / "limits.json").read_text())
    assert limits["start_limit"]["value"] == "20 starts per 300 s"
    assert limits["slots"]["value"] == {"sealed": 1, "docker": 2}
    assert limits["boot_wait_seconds"]["value"] == 300


def test_docker_2_stays_held_until_gh_aw_isolates_its_fixed_tmp() -> None:
    limits = json.loads((REVIEW / "limits.json").read_text())
    # Counted for the cap, but only docker-1 is enabled: gh-aw recreates fixed /tmp/gh-aw.
    assert limits["slots"]["value"] == {"sealed": 1, "docker": 2}
    assert limits["enabled_slots"]["value"] == {"sealed": 1, "docker": 1}
    _jit("slot_identity sealed; enabled_limit=1; slot_enabled")
    _jit("slot_identity docker-1; enabled_limit=1; slot_enabled")
    _jit("slot_identity docker-2; enabled_limit=1; slot_enabled", expect_ok=False)
    # Raising the registry's enabled count is the only way to lift the hold.
    _jit("slot_identity docker-2; enabled_limit=2; slot_enabled")
    jit = (REVIEW / "jit.sh").read_text()
    assert ".enabled_slots.value[$profile]" in jit
    assert "exceeds the $profile enabled slot count" in jit


def test_the_whole_account_cap_holds_every_slot_limit_plus_the_measured_daemon() -> None:
    limits = json.loads((REVIEW / "limits.json").read_text())
    floor = limits["memory_floor_gib"]["value"]
    cap = limits["memory_max_gib"]["value"]
    slot = limits["slot_memory_gib"]["value"]
    overhead = limits["memory_overhead_mib"]["value"]
    sibling = limits["sibling_memory_mib_per_docker_slot"]["value"]
    tmpfs = limits["runtime_tmpfs_mib_per_slot"]["value"]
    enabled = limits["enabled_slots"]["value"]
    enabled_count = sum(enabled.values())
    slot_count = sum(limits["slots"]["value"].values())
    # Three counted 6 GiB slots, the measured daemon RSS, one enabled docker slot's
    # AWF siblings (6 GiB agent plus 128 MiB init) and 1 GiB of runtime tmpfs a slot.
    assert slot_count == 3 and slot == 6 and enabled_count == 2
    assert overhead >= 320 and sibling == 6 * 1024 + 128 and tmpfs == 1024
    needed_mib = (
        slot_count * slot * 1024 + overhead + enabled["docker"] * sibling + enabled_count * tmpfs
    )
    smallest_cap = (needed_mib + 1023) // 1024
    assert cap >= smallest_cap
    conf = (REVIEW / "user-1501-limits.conf").read_text()
    assert "[Slice]" in conf
    assert f"MemoryMax={cap}G" in conf and "MemorySwapMax=0" in conf
    sealed_mib = (floor + slot) * 1024 + tmpfs
    docker_mib = sealed_mib + sibling
    readme = (REVIEW / "README.md").read_text()
    assert (
        f"Admission needs {sealed_mib / 1024:g} GiB `MemAvailable` for a sealed slot "
        f"and {docker_mib / 1024:g} GiB for a docker slot"
    ) in readme
    jit = (REVIEW / "jit.sh").read_text()
    assert '--memory "${slot_gib}g"' in jit and '--memory-swap "${slot_gib}g"' in jit
    assert '--memory "${cap}g"' not in jit
    budget = (
        f"slot_gib={slot}; slot_count={slot_count}; overhead_mib={overhead}; "
        f"enabled_docker={enabled['docker']}; sibling_mib={sibling}; "
        f"enabled_count={enabled_count}; tmpfs_mib={tmpfs}"
    )
    _jit(f"cap={cap}; {budget}; cap_covers_slots")
    _jit(f"cap={smallest_cap - 1}; {budget}; cap_covers_slots", expect_ok=False)
    base = f"floor={floor}; slot_gib={slot}; tmpfs_mib={tmpfs}; sibling_mib={sibling}"
    assert _jit(f"profile=sealed; {base}; admission_mib").strip() == str(sealed_mib)
    assert _jit(f"profile=docker; {base}; admission_mib").strip() == str(docker_mib)
    _jit(f"runtime_tmpfs_mib={enabled_count * tmpfs}; {budget}; tmpfs_covers_budget")
    _jit(
        f"runtime_tmpfs_mib={enabled_count * tmpfs - 1}; {budget}; tmpfs_covers_budget",
        expect_ok=False,
    )


def test_the_runner_id_is_recorded_and_only_the_configuration_reaches_the_container(
    tmp_path: Path,
) -> None:
    runner = tmp_path / "runner"
    forwarded = _jit(f'runner_id_file="{runner}"; printf "42\\nencoded\\n" | record_runner_id')
    assert forwarded == "encoded\n" and runner.read_text() == "42\n"
    _jit(f'runner_id_file="{runner}.bad"; printf "x\\nencoded\\n" | record_runner_id', False)
    assert not (tmp_path / "runner.bad").exists()
    jit = (REVIEW / "jit.sh").read_text()
    assert "--jq '.runner.id, .encoded_jit_config' | record_runner_id |" in jit


DELETE = "api --method DELETE repos/seathatflowsinourveins/sextant/actions/runners/"


def _teardown_fakes(tmp_path: Path, gh_body: str = "") -> str:
    """Fake daemon, lock and GitHub calls; every call is appended to tmp_path/calls."""
    calls = tmp_path / "calls"
    return (
        f"flock() {{ :; }}; cleanup() {{ :; }}; container=abc; "
        f'runner_id_file="{tmp_path / "runner"}"; pending_file="{tmp_path / "pending"}"; '
        f'docker() {{ printf "docker %s\\n" "$*" >> "{calls}"; }}; '
        f'gh() {{ printf "%s GH_TOKEN=%s\\n" "$*" "${{GH_TOKEN-unset}}" >> "{calls}"; {gh_body} }}'
    )


def _calls(tmp_path: Path) -> list[str]:
    calls = tmp_path / "calls"
    return calls.read_text().splitlines() if calls.exists() else []


def test_every_teardown_removes_the_runner_then_its_registration_with_the_producer_login(
    tmp_path: Path,
) -> None:
    removed, deleted = "docker rm --force abc", f"{DELETE}42 GH_TOKEN=unset"
    for status in (3, 130, 0):
        (tmp_path / "calls").unlink(missing_ok=True)
        (tmp_path / "runner").write_text("42\n")
        fakes = _teardown_fakes(tmp_path)
        script = f'source "{REVIEW / "jit.sh"}"; {fakes}; set +e; (exit {status}); on_exit'
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env={"PATH": os.defpath},
            timeout=10,
        )
        assert result.returncode == status, result.stderr
        assert _calls(tmp_path) == [removed, deleted]
        assert not (tmp_path / "runner").exists() and not (tmp_path / "pending").exists()
    # The control-plane token is the producer's own gh login; jit.sh never supplies another.
    jit = (REVIEW / "jit.sh").read_text()
    assert not re.search(r"GH_TOKEN|GITHUB_TOKEN|sudo[^\n]*\s(?:/usr/bin/)?gh\s", jit)


def test_a_refused_removal_is_retried_at_the_next_start_and_not_found_counts_as_removed(
    tmp_path: Path,
) -> None:
    (tmp_path / "runner").write_text("42\n")
    refuse = 'echo "gh: Runner is still running a job (HTTP 422)" >&2; return 1;'
    _jit(f"{_teardown_fakes(tmp_path, refuse)}; deregister")
    assert (tmp_path / "pending").read_text() == "42\n" and not (tmp_path / "runner").exists()
    gone = 'echo "gh: Not Found (HTTP 404)" >&2; return 1;'
    _jit(f"{_teardown_fakes(tmp_path, gone)}; deregister")
    assert not (tmp_path / "pending").exists()
    assert _calls(tmp_path) == [f"{DELETE}42 GH_TOKEN=unset"] * 2


def test_a_runner_without_a_recorded_id_is_found_by_name(tmp_path: Path) -> None:
    lookup = '[[ $2 == *"?name="* ]] && echo 77; return 0;'
    _jit(f"{_teardown_fakes(tmp_path, lookup)}; name=sextant-jit-sealed.abc; deregister")
    assert _calls(tmp_path) == [
        "api repos/seathatflowsinourveins/sextant/actions/runners?name=sextant-jit-sealed.abc "
        "--jq .runners[0].id // empty GH_TOKEN=unset",
        f"{DELETE}77 GH_TOKEN=unset",
    ]


def test_sigterm_during_a_job_runs_the_whole_exit_cleanup(tmp_path: Path) -> None:
    (tmp_path / "runner").write_text("42\n")
    script = (
        f'source "{REVIEW / "jit.sh"}"; {_teardown_fakes(tmp_path)}; arm_exit; sleep 30 & wait "$!"'
    )
    job = subprocess.Popen(["bash", "-c", script], env={"PATH": os.defpath}, start_new_session=True)
    try:
        time.sleep(1)
        job.send_signal(signal.SIGTERM)
        assert job.wait(timeout=10) == 130
    finally:
        try:  # the test's own process group: bash and its background sleep
            os.killpg(job.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    assert _calls(tmp_path) == ["docker rm --force abc", f"{DELETE}42 GH_TOKEN=unset"]
    # main waits on the runner in the background, so the trap runs as soon as the signal arrives.
    jit = (REVIEW / "jit.sh").read_text()
    assert '  } &\n  local status=0\n  wait "$!" || status=$?\n  runner_status "$status"' in jit


def test_a_runner_that_never_started_a_job_stops_the_slot(tmp_path: Path) -> None:
    fake = f'sudo() {{ shift; "$@"; }}; root="{tmp_path}"; name=fixture'
    for marker, given, expected in ((False, 0, 1), (True, 0, 0), (True, 5, 5), (False, 7, 7)):
        (tmp_path / ".job-started").unlink(missing_ok=True)
        if marker:
            (tmp_path / ".job-started").write_text("2026-11-07T00:00:00Z\n")
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'source "{REVIEW / "jit.sh"}"; {fake}; set +e; runner_status {given}; echo $?',
            ],
            capture_output=True,
            text=True,
            env={"PATH": os.defpath},
            timeout=10,
        )
        assert result.stdout.split()[-1] == str(expected), (marker, given, result.stderr)


def test_a_slot_refuses_a_live_daemon_that_differs_from_the_installed_drop_in() -> None:
    good_kit = (
        "1 rootlesskit --net=gvisor-tap-vsock --disable-host-loopback "
        "--port-driver=none --copy-up=/etc"
    )
    good_daemon = (
        "2 dockerd --tls=false --ip=127.0.0.1 "
        "--default-network-opt=bridge=com.docker.network.bridge.host_binding_ipv4=127.0.0.1"
    )

    def check(kit: str, daemon: str) -> bool:
        fake = (
            f'pgrep() {{ [[ $* == *rootlesskit* ]] && echo "{kit}" && return 0; '
            f'[[ $* == *dockerd* ]] && echo "{daemon}" && return 0; return 1; }}'
        )
        result = subprocess.run(
            ["bash", "-c", f'source "{REVIEW / "jit.sh"}"; {fake}; set +e; daemon_as_installed'],
            capture_output=True,
            text=True,
            env={"PATH": os.defpath},
            timeout=10,
        )
        return result.returncode == 0

    assert check(good_kit, good_daemon)
    assert not check(good_kit + " --detach-netns", good_daemon)
    assert not check(good_kit.replace("--port-driver=none", "--port-driver=builtin"), good_daemon)
    assert not check(good_kit.replace(" --disable-host-loopback", ""), good_daemon)
    assert not check(good_kit, good_daemon.replace(" --ip=127.0.0.1", ""))
    assert not check(good_kit, good_daemon.split(" --default-network-opt")[0])


def test_sealed_egress_drops_private_shared_and_link_local_ranges_but_not_dns(
    tmp_path: Path,
) -> None:
    bin_dir, log = tmp_path / "bin", tmp_path / "iptables.log"
    bin_dir.mkdir()
    fake = bin_dir / "iptables"
    fake.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\ncase "$1" in -N|-C) exit 1;; esac\n')
    fake.chmod(0o755)
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 10.0.2.1\nnameserver fe80::1\n")
    fake_ns = 'in_daemon_ns() { "$@"; }'
    script = f'source "{REVIEW / "jit.sh"}"; {fake_ns}; sealed_egress 10.231.0.0/24 "{resolv}"'
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:{os.defpath}"},
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    rules = log.read_text().splitlines()
    assert rules[0] == "-N SEXTANT-SEALED" and rules[1] == "-F SEXTANT-SEALED"
    assert "-A SEXTANT-SEALED -d 10.0.2.1 -p udp --dport 53 -j RETURN" in rules
    assert not [rule for rule in rules if "fe80::1" in rule]
    for rng in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"):
        assert f"-A SEXTANT-SEALED -d {rng} -j DROP" in rules
    assert rules[-2:] == [
        "-C DOCKER-USER -s 10.231.0.0/24 -j SEXTANT-SEALED",
        "-I DOCKER-USER -s 10.231.0.0/24 -j SEXTANT-SEALED",
    ]


def test_the_docker_slot_sweeps_only_its_own_containers_files_from_the_shared_tmp(
    tmp_path: Path,
) -> None:
    host_tmp, uid = tmp_path / "tmp", os.getuid()
    gh_aw, left, other = host_tmp / "gh-aw", host_tmp / "gh-aw-cli-proxy.x", tmp_path / "keep"
    shared, planted = host_tmp / "world-writable", host_tmp / "world-writable" / "planted"
    subuid = tmp_path / "subuid"
    fake_sudo = 'sudo() { while [[ $1 == -* ]]; do shift; done; "$@"; }'
    base = f'{fake_sudo}; gh_aw_tmp="{gh_aw}"; subuid_file="{subuid}"'
    # Files this test creates stand in for the daemon's containers when its uid is in the range.
    subuid.write_text(f"someone:1:2\nsextant-review:{uid}:1\n")
    (gh_aw / "mcp-logs").mkdir(parents=True)
    left.mkdir()
    other.mkdir()
    planted.mkdir(parents=True)  # what an agent could leave inside a world-writable directory
    _jit(f"{base}; review_uid=4242; sweep_host_tmp")
    assert not gh_aw.exists() and not left.exists() and other.exists()
    assert not shared.exists() and not planted.exists()
    # Outside the range nothing is swept, and someone else's /tmp/gh-aw stops the slot.
    subuid.write_text(f"sextant-review:{uid + 1}:1\n")
    (gh_aw / "mcp-logs").mkdir(parents=True)
    left.mkdir()
    _jit(f"{base}; review_uid=4242; sweep_host_tmp", False)
    assert gh_aw.exists() and left.exists()
    gh_aw.rename(tmp_path / "moved")
    _jit(f"{base}; review_uid=4242; sweep_host_tmp")
    assert left.exists()  # not in the subordinate range, so not this daemon's
    jit = (REVIEW / "jit.sh").read_text()
    assert "    sweep_host_tmp || return 1\n" in jit and "reset_gh_aw_tmp" not in jit
    # Any depth: AWF mounts this /tmp into its agent, which can write inside world-writable dirs.
    sweep = jit.split("sweep_host_tmp() {", 1)[1].split("\n}\n", 1)[0]
    assert "-maxdepth" not in sweep and "-prune -exec rm -rf -- {} +" in sweep


def test_the_build_cache_prune_gets_a_fresh_buildx_state_and_nothing_else_does(
    tmp_path: Path,
) -> None:
    log, state = tmp_path / "calls", tmp_path / "state"
    fake = (
        f'sudo() {{ printf "%s\\n" "$*" >>"{log}"; '
        f'case "$*" in *mktemp*) mkdir "{state}" && echo "{state}" ;; esac; }}'
    )
    _jit(f"{fake}; builder_prune; docker ps")
    calls = log.read_text().splitlines()
    prune = next(call for call in calls if call.endswith("builder prune --all --force"))
    # The root-owned DOCKER_CONFIG stays; buildx writes only to its own fresh directory.
    assert f"BUILDX_CONFIG={state} " in prune
    assert "DOCKER_CONFIG=/usr/local/lib/sextant-jit/docker-config " in prune
    assert f"-n rm -rf -- {state}" in calls
    assert "BUILDX_CONFIG" not in calls[-1] and calls[-1].endswith("/usr/bin/docker ps")
    jit = (REVIEW / "jit.sh").read_text()
    assert jit.count("builder prune") == 1 and "    builder_prune || return 1\n" in jit


def test_jobs_run_as_the_images_non_root_runner_inside_a_private_root() -> None:
    entrypoint = (REVIEW / "entrypoint.sh").read_text()
    assert "drop=(setpriv --reuid=runner --regid=runner --init-groups)" in entrypoint
    assert entrypoint.rstrip().endswith('exec "${drop[@]}" ./run.sh')
    assert "\numask 022\n" in entrypoint
    # cp -a copies the distribution directory's 0777 onto the root, so 0700 must follow it.
    assert entrypoint.index("cp -a /opt/runner-dist/.") < entrypoint.index(
        'chmod 0700 "$SEXTANT_JIT_ROOT"'
    )
    dockerfile = (REVIEW / "Dockerfile").read_text()
    assert "install -d -o runner -g runner -m 0755 /home/runner" in dockerfile
    assert "RUNNER_ALLOW_RUNASROOT" not in dockerfile


def test_startup_arms_the_exit_cleanup_before_its_first_cleanup() -> None:
    main = (REVIEW / "jit.sh").read_text().split("main() {", 1)[1]
    assert main.index("\n  arm_exit") < main.index("\n  cleanup\n") < main.index("\n  deregister")


def test_public_gate_retires_generated_private_review_locks() -> None:
    import yaml

    assert not list(WORKFLOWS.glob("*.lock.yml"))
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    assert ci["jobs"]["ci"]["needs"] == ["lint", "tests", "budgets", "secrets"]


def test_public_workflows_cannot_dispatch_old_runner_smokes() -> None:
    scoreboard = (WORKFLOWS / "scoreboard.yml").read_text()
    assert "jit-smoke:" not in scoreboard and "jit-sealed-smoke:" not in scoreboard
    assert "jit-cleanup-smoke:" not in scoreboard


def test_active_review_uses_hosted_jobs_instead_of_runtime_containers() -> None:
    import yaml

    gate = yaml.safe_load((WORKFLOWS / "gate.yml").read_text())
    for job in gate["jobs"].values():
        assert job["runs-on"] == "ubuntu-24.04"
        assert not {"container", "services"} & set(job)


def test_jit_input_is_consumed_from_stdin_and_only_reaches_the_runner(tmp_path: Path) -> None:
    root = tmp_path / "job"
    root.mkdir()
    runner = tmp_path / "runner"
    runner.mkdir()
    (runner / "run.sh").write_text(
        '#!/bin/bash\n[[ "$ACTIONS_RUNNER_INPUT_JITCONFIG" == "$EXPECTED_INPUT" ]]\n'
        '[[ "$#" == 0 ]]\n[[ "$PWD" == "$SEXTANT_JIT_ROOT" ]]\n'
    )
    (runner / "run.sh").chmod(0o755)
    # entrypoint's fixed image source is replaced in the fixture, never in production.
    script = (REVIEW / "entrypoint.sh").read_text().replace("/opt/runner-dist", str(runner))
    env = {"PATH": os.defpath, "SEXTANT_JIT_ROOT": str(root), "EXPECTED_INPUT": "fixture"}
    result = subprocess.run(
        ["bash", "-c", script],
        input="fixture\n",
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "fixture" not in result.stdout + result.stderr
    assert not any("fixture" in p.read_text() for p in root.rglob("*") if p.is_file())


def test_receipt_uses_actual_checkout_and_upstream_summary_file(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    env = {"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    subprocess.run(["git", "init", "-q", str(checkout)], env=env, check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        env=env,
        check=True,
    )
    sha = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], env=env, text=True
    ).strip()
    summary = tmp_path / "summary"
    env.update(
        SEXTANT_JIT_ROOT=str(tmp_path),
        SEXTANT_RUNNER_IMAGE="sha256:" + "a" * 64,
        GITHUB_WORKSPACE=str(checkout),
        GITHUB_SHA="b" * 40,
        GITHUB_STEP_SUMMARY=str(summary),
    )
    for hook in ("job-started.sh", "job-completed.sh"):
        subprocess.run(["bash", str(REVIEW / hook)], env=env, check=True, timeout=10)
    receipt = summary.read_text()
    assert sha in receipt and "sha256:" + "a" * 64 in receipt
    assert "Started (UTC)" in receipt and "Ended (UTC)" in receipt


def test_public_workflows_never_select_the_legacy_runner_profiles() -> None:
    import yaml

    for path in WORKFLOWS.glob("*.yml"):
        for job in yaml.safe_load(path.read_text())["jobs"].values():
            assert job["runs-on"] == "ubuntu-24.04"
            assert job["runs-on"] not in (SEALED, DOCKER)


def test_ports_published_without_an_address_bind_to_loopback() -> None:
    conf = (REVIEW / "docker-jit.conf").read_text()
    daemon = next(line for line in conf.splitlines() if line.startswith("ExecStart=/"))
    assert "--ip=127.0.0.1" in daemon.split()
    assert "--default-network-opt=bridge=com.docker.network.bridge.host_binding_ipv4=127.0.0.1" in (
        daemon.split()
    )


def test_the_parked_report_jobs_remain_main_only() -> None:
    import yaml

    for name, job_name in (("scoreboard", "scoreboard"), ("consolidation", "report")):
        job = yaml.safe_load((WORKFLOWS / f"{name}.yml").read_text())["jobs"][job_name]
        assert "github.ref == 'refs/heads/main'" in job["if"]


def test_review_keys_are_bound_only_to_their_selected_review_steps() -> None:
    import yaml

    ci = (WORKFLOWS / "ci.yml").read_text()
    assert "secrets." not in ci
    gate = yaml.safe_load((WORKFLOWS / "gate.yml").read_text())
    expected = {
        "dsh": {"DEEPSEEK_API_KEY"},
        "codex": {"OPENAI_API_KEY"},
        "claude": {"ANTHROPIC_API_KEY"},
    }
    for name, job in gate["jobs"].items():
        assert set(re.findall(r"secrets\.(\w+)", json.dumps(job))) == expected.get(name, set())
    assert "quality == 'codex'" in gate["jobs"]["codex"]["if"]
    assert "quality == 'claude'" in gate["jobs"]["claude"]["if"]
