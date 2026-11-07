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
    assert "sextant-jit.profile=sealed" in sealed and "HOME=/home/runner" in sealed
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
    # The producer's own Docker CLI never loads UID 1501's ~/.docker plugins or helpers.
    assert 'DOCKER_CONFIG="$installed/docker-config"' in (REVIEW / "jit.sh").read_text()
    assert _jit("runner_labels sealed").split() == SEALED
    assert _jit("runner_labels docker").split() == DOCKER
    _jit("runner_options everything /x y", expect_ok=False)
    _jit("runner_labels everything", expect_ok=False)


def test_each_profile_removes_only_its_own_containers() -> None:
    fake = "docker() { printf '%s\\n' 'c1 sealed' 'c2 docker' 'c3 '; }"
    assert _jit(f"{fake}; owned_containers sealed").split() == ["c1"]
    assert _jit(f"{fake}; owned_containers docker").split() == ["c2", "c3"]


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
    assert limits["runners"]["value"] == 2 and limits["boot_wait_seconds"]["value"] == 300


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


def test_ci_proves_the_locks_are_byte_identical_gh_aw_v101_output() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text()
    assert "GH_AW_SHA256: 746d0b41d5fb87e2c010b8ac23a464436bb745ff89fbd19a3456431942c37652" in ci
    assert '"$RUNNER_TEMP/gh-aw" compile --no-check-update' in ci
    assert "git diff --exit-code -- .github/workflows/ .github/aw/" in ci


def test_the_sealed_smoke_probes_the_daemon_published_ports_and_egress() -> None:
    smoke = (WORKFLOWS / "scoreboard.yml").read_text().split("  jit-sealed-smoke:", 1)[1]
    for probe in ("/2375", "for port in 3128 8080", "10.0.2.1/80 10.0.2.2/80 169.254.169.254/80"):
        assert probe in smoke, probe


def test_compiler_resolves_every_runtime_container_to_a_digest() -> None:
    for path in (ROOT / ".github/workflows").glob("review*.lock.yml"):
        manifest = json.loads(path.read_text().splitlines()[1].split(": ", 1)[1])
        assert not manifest.get("resolution_failures"), path
        assert all("@sha256:" in c["pinned_image"] for c in manifest["containers"]), path


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


def test_pr_code_and_docker_free_jobs_run_only_on_the_sealed_profile() -> None:
    import yaml

    routes = {
        f"{path.name}/{name}": job["runs-on"]
        for path in WORKFLOWS.glob("*.yml")
        for name, job in yaml.safe_load(path.read_text())["jobs"].items()
    }
    sealed = {job for job, labels in routes.items() if labels == SEALED}
    assert sealed == {
        "ci.yml/ci",
        "source.yml/source",
        "dependabot-automerge.yml/automerge",
        "scoreboard.yml/jit-sealed-smoke",
    }
    assert {job for job, labels in routes.items() if labels != SEALED} == {
        job for job, labels in routes.items() if labels == DOCKER
    }
    # No sealed job may need the daemon: no job container, service container or Docker action.
    for path in WORKFLOWS.glob("*.yml"):
        for name, job in yaml.safe_load(path.read_text())["jobs"].items():
            if job["runs-on"] == SEALED:
                assert not {"container", "services"} & set(job), (path.name, name)
                uses = [str(step.get("uses", "")) for step in job.get("steps", [])]
                assert not [u for u in uses if u.startswith("docker://")], (path.name, name)


def test_ports_published_without_an_address_bind_to_loopback() -> None:
    conf = (REVIEW / "docker-jit.conf").read_text()
    daemon = next(line for line in conf.splitlines() if line.startswith("ExecStart=/"))
    assert "--ip=127.0.0.1" in daemon.split()
    assert "--default-network-opt=bridge=com.docker.network.bridge.host_binding_ipv4=127.0.0.1" in (
        daemon.split()
    )


def test_the_repositorys_own_docker_jobs_are_main_gated() -> None:
    import yaml

    branch_reachable = {}
    for path in WORKFLOWS.glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        triggers = set(workflow.get("on", workflow.get(True)))
        for name, job in workflow["jobs"].items():
            if job["runs-on"] == DOCKER and triggers != {"pull_request_target"}:
                branch_reachable[f"{path.name}/{name}"] = job.get("if")
    # pull_request_target always runs the base branch's files; every other docker job is pinned to
    # an exact main-only condition, so a new docker job or a widened condition fails here.
    main = "${{ github.ref == 'refs/heads/main' && "
    smoke = main + "github.event_name == 'workflow_dispatch' && inputs.jit_smoke }}"
    assert branch_reachable == {
        "scoreboard.yml/scoreboard": main
        + "(github.event_name != 'workflow_dispatch' || !inputs.jit_smoke) }}",
        "scoreboard.yml/jit-smoke": smoke,
        "scoreboard.yml/jit-cleanup-smoke": smoke,
    }


def test_every_job_keeps_its_privileges_and_secret_names() -> None:
    import yaml

    for name in ("ci", "source", "scoreboard", "dependabot-automerge"):
        text = (WORKFLOWS / f"{name}.yml").read_text()
        current, base_text = yaml.safe_load(text), _main(f".github/workflows/{name}.yml")
        base = yaml.safe_load(base_text)
        for job_name, job in current["jobs"].items():
            granted = job.get("permissions", current["permissions"])
            if job_name in base["jobs"]:
                base_job = base["jobs"][job_name]
                assert granted == base_job.get("permissions", base["permissions"]), job_name
            else:
                assert granted == {"contents": "read"}, job_name
        assert set(re.findall(r"secrets\.(\w+)", text)) == set(
            re.findall(r"secrets\.(\w+)", base_text)
        )
    for path in WORKFLOWS.glob("review*.lock.yml"):

        def secrets(lock: str) -> list[str]:
            return json.loads(lock.splitlines()[1].split(": ", 1)[1])["secrets"]

        assert secrets(path.read_text()) == secrets(_main(f".github/workflows/{path.name}"))
