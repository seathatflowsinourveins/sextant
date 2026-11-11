"""Attended units, rendered offline like test_tradingview_units.py; no keys or nodes run."""

from __future__ import annotations

import configparser
import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy/paper"
B = "sextant-paper-b-stage1.service"
IBKR = "sextant-paper-ibkr-dry-run.service"
IBKR_LIFECYCLE = "sextant-paper-ibkr-lifecycle.service"
UNITS = (B, IBKR, IBKR_LIFECYCLE)
KEYS = {
    B: ["ALPACA_PAPER_2_API_KEY", "ALPACA_PAPER_2_SECRET_KEY"],
    IBKR: ["IB_PAPER_ACCOUNT_ID"],
    IBKR_LIFECYCLE: ["IB_PAPER_ACCOUNT_ID"],
}


def _unit(path: Path) -> configparser.ConfigParser:
    parsed = configparser.ConfigParser(interpolation=None)
    parsed.optionxform = str  # type: ignore[assignment,method-assign]
    assert parsed.read(path), f"missing unit: {path}"
    return parsed


@pytest.mark.parametrize("name", UNITS)
def test_attended_units_never_restart_or_enable_and_inject_only_named_keys(name: str) -> None:
    unit = _unit(DEPLOY / name)
    service = unit["Service"]
    command = shlex.split(service["ExecStart"])
    prefix = ["/usr/bin/bash", "%h/sextant/scripts/with-keys.sh", "--strict"]
    for key in KEYS[name]:
        prefix += ["-k", key]
    assert command[: len(prefix) + 1] == [*prefix, "--"]
    assert command.count("-k") == len(KEYS[name])
    assert command[len(prefix) + 1 : len(prefix) + 6] == [
        "%h/.local/bin/uv",
        "run",
        "--frozen",
        "python",
        "-m",
    ]
    assert service["Type"] == "simple" and service["Restart"] == "no"
    assert "Install" not in unit
    assert set(service) == {
        "Type",
        "WorkingDirectory",
        "Environment",
        "EnvironmentFile",
        "ExecStart",
        "Restart",
    }
    assert service["WorkingDirectory"] == "%h/sextant"
    assert service["Environment"] == (
        "PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin PYTHONUNBUFFERED=1"
    )
    parameter_file = service["EnvironmentFile"]
    assert parameter_file == f"%h/.config/sextant/paper/{name[8:-8]}.params"
    assert not parameter_file.startswith("-") and ".env" not in parameter_file
    example = DEPLOY / (Path(parameter_file).name + ".example")
    assert example.is_file()
    # No identity/credential values or free-form argument lists in shipped parameters.
    assignments = [
        line.split("=", 1)
        for line in example.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert assignments and all(value == "" for _, value in assignments)
    assert not set(KEYS[name]) & {key for key, _ in assignments}
    used = set(re.findall(r"\$\{([A-Z_]+)\}", service["ExecStart"]))
    assert used <= {key for key, _ in assignments}
    assert "--send-orders" not in (DEPLOY / IBKR).read_text()


def _install(tmp_path: Path, override: str | None = None):
    repo = tmp_path / "checkout"
    deploy = repo / "deploy/paper"
    deploy.mkdir(parents=True, exist_ok=True)
    for name in ("install.sh", *UNITS):
        assert (DEPLOY / name).is_file(), f"missing installation artifact: {name}"
        shutil.copy2(DEPLOY / name, deploy / name)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    calls = tmp_path / "calls"
    fake = fake_bin / "systemctl"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n')
    fake.chmod(0o755)
    config = tmp_path / "config"
    env = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(config),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "CALLS": str(calls),
    }
    if override is not None:
        env["SEXTANT_REPO"] = override
    done = subprocess.run(
        ["bash", str(deploy / "install.sh")], env=env, capture_output=True, text=True
    )
    return done, repo, config / "systemd/user", calls


@pytest.mark.parametrize("override", [None, "/work/checkout&literal|path"])
def test_installer_only_renders_and_reloads_never_starts_or_enables(tmp_path: Path, override):
    done, repo, units, calls = _install(tmp_path, override)
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in units.iterdir()) == sorted(UNITS)
    assert calls.read_text().splitlines() == ["--user daemon-reload"]
    for name in UNITS:
        service = _unit(units / name)["Service"]
        assert service["WorkingDirectory"] == (override or str(repo))
        assert service["ExecStart"].startswith(
            f"/usr/bin/bash {override or repo}/scripts/with-keys.sh --strict "
        )
        assert service["EnvironmentFile"].startswith("%h/.config/sextant/paper/")
        (units / name).write_text("stale")
    again, *_ = _install(tmp_path, override)
    assert again.returncode == 0, again.stderr
    assert all("stale" not in (units / name).read_text() for name in UNITS)


@pytest.mark.parametrize(
    "override", ["/work/check out", "/work/100%h", "/work/$HOME", '/w/"q', "/w/'q", "/w/\\q"]
)
def test_installer_refuses_paths_systemd_would_split_or_expand(tmp_path: Path, override: str):
    done, _, units, calls = _install(tmp_path, override)
    assert done.returncode == 2
    assert not units.exists() and not calls.exists()


def _arguments(name: str, values: dict[str, str]) -> list[str]:
    command = shlex.split(_unit(DEPLOY / name)["Service"]["ExecStart"])
    # systemd.service(5): ${NAME} is one argument, including whitespace and literal dollars.
    args = command[command.index("-m") + 2 :]
    return [re.sub(r"\$\{([A-Z_]+)\}", lambda m: values.get(m[1], ""), arg) for arg in args]


def test_b_command_uses_current_parser_and_keeps_paths_and_source_as_single_arguments(tmp_path):
    from sextant.paper import node_order

    account = tmp_path / "fixture account.json"
    account.write_text(
        json.dumps(
            dict(
                lane="alpaca-paper-b",
                account_id="FIXTUREACCOUNT",
                client_id="ALPACA",
                namespace="BTEST",
                sessions=["rth"],
            )
        )
    )
    values = dict(
        B_ACCOUNT_CONFIG=str(account),
        B_CLAIM_LIST=str(tmp_path / "claim list.json"),
        B_RECEIPT_DIR=str(tmp_path / "receipt dir"),
        B_DURATION_S="7",
        B_WRITER_LEASE_ROOT=str(tmp_path / "writer locks"),
        B_STREAM_LEASE_ROOT=str(tmp_path / "producer leases"),
        B_EXISTING_STREAMS="0",
        B_LEASE_SOURCE="fixture only: no streams; $literal --not-an-option",
    )
    parsed = node_order.parse(_arguments(B, values))
    assert parsed.duration_s == 7 and parsed.existing_streams == 0
    assert parsed.universe_artifact == tmp_path / "claim list.json"
    assert parsed.receipt_dir == tmp_path / "receipt dir"
    assert parsed.writer_lease_root == tmp_path / "writer locks"
    assert parsed.stream_lease_root == tmp_path / "producer leases"
    assert parsed.lease_source == values["B_LEASE_SOURCE"]
    assert [parsed.api_key_env, parsed.api_secret_env] == KEYS[B]
    assert parsed.account.lane == "alpaca-paper-b"
    with pytest.raises(SystemExit):
        node_order.parse(_arguments(B, values | {"B_DURATION_S": ""}))


def test_ibkr_command_parses_as_lifecycle_dry_run_without_reading_account(tmp_path, monkeypatch):
    from sextant.paper import node_ibkr

    monkeypatch.delenv("IB_PAPER_ACCOUNT_ID", raising=False)
    values = dict(
        IBKR_HOST="192.0.2.1",
        IBKR_PORT="4002",
        IBKR_DATA_CLIENT_ID="91001",
        IBKR_EXEC_CLIENT_ID="91002",
        IBKR_INSTRUMENT="TEST.NASDAQ",
        IBKR_ORDER_QTY="1",
        IBKR_DURATION_S="120",
        IBKR_RECEIPT_DIR=str(tmp_path / "receipt dir"),
        IBKR_LEASE_ROOT=str(tmp_path / "compatibility lease"),
    )
    parsed = node_ibkr.parse(_arguments(IBKR, values))
    assert parsed.send_orders is False and parsed.profile == "lifecycle"
    assert parsed.account_id_env == "IB_PAPER_ACCOUNT_ID"
    assert parsed.host == "192.0.2.1" and parsed.port == 4002
    assert parsed.data_client_id == 91001 and parsed.exec_client_id == 91002
    assert parsed.duration_s == 120 and parsed.order_qty == "1"
    assert parsed.receipt_dir == tmp_path / "receipt dir"
    with pytest.raises(SystemExit):
        node_ibkr.parse(_arguments(IBKR, values | {"IBKR_DURATION_S": ""}))


def test_paper_installer_is_shellcheck_clean():
    assert (DEPLOY / "install.sh").is_file()
    if not shutil.which("shellcheck"):
        pytest.skip("shellcheck unavailable")
    done = subprocess.run(
        ["shellcheck", str(DEPLOY / "install.sh")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_ibkr_lifecycle_unit_only_adds_the_fixed_second_opt_in():
    dry_run = (DEPLOY / IBKR).read_text()
    lifecycle = DEPLOY / IBKR_LIFECYCLE
    assert lifecycle.is_file(), "missing attended IBKR order-sending unit"
    assert lifecycle.read_text() == dry_run.replace(
        "Description=Sextant IBKR attended node dry run",
        "Description=Sextant IBKR attended node lifecycle orders",
    ).replace("paper-ibkr-dry-run.params", "paper-ibkr-lifecycle.params").replace(
        "--profile lifecycle\n", "--profile lifecycle --send-orders\n"
    )
    service = _unit(lifecycle)["Service"]
    command = shlex.split(service["ExecStart"])
    assert command.count("--send-orders") == 1
    assert "-c" not in command
    assert command[command.index("--profile") + 1] == "lifecycle"
    assert command[command.index("--order-qty") + 1] == "${IBKR_ORDER_QTY}"
    assert command[command.index("--duration-s") + 1] == "${IBKR_DURATION_S}"


def test_ibkr_lifecycle_command_uses_node_opt_in_without_reading_account(tmp_path, monkeypatch):
    from decimal import Decimal

    from sextant.paper import node_ibkr

    monkeypatch.delenv("IB_PAPER_ACCOUNT_ID", raising=False)
    values = dict(
        IBKR_HOST="192.0.2.1",
        IBKR_PORT="4002",
        IBKR_DATA_CLIENT_ID="91001",
        IBKR_EXEC_CLIENT_ID="91002",
        IBKR_INSTRUMENT="TEST.NASDAQ",
        IBKR_ORDER_QTY="2",
        IBKR_DURATION_S="7",
        IBKR_RECEIPT_DIR=str(tmp_path / "receipt dir $literal --profile bracket"),
        IBKR_LEASE_ROOT=str(tmp_path / "compatibility lease"),
    )
    parsed = node_ibkr.parse(_arguments(IBKR_LIFECYCLE, values))
    assert parsed.send_orders is True and parsed.profile == "lifecycle"
    assert parsed.account_id_env == "IB_PAPER_ACCOUNT_ID"
    assert parsed.duration_s == 7 and parsed.order_qty == "2"
    assert parsed.receipt_dir == Path(values["IBKR_RECEIPT_DIR"])
    tester = node_ibkr.tester_config(parsed)
    assert tester.dry_run is False
    assert tester.open_position_on_start_qty == Decimal("2")
    assert tester.open_position_on_first_quote is True
    assert tester.enable_limit_sells is False and tester.enable_stop_sells is False
    assert tester.cancel_orders_on_stop is False and tester.close_positions_on_stop is False
    for key, value in (
        ("IBKR_DURATION_S", ""),
        ("IBKR_DURATION_S", "7 --profile bracket"),
        ("IBKR_ORDER_QTY", ""),
        ("IBKR_ORDER_QTY", "2 --send-orders"),
    ):
        with pytest.raises((SystemExit, node_ibkr.IbkrNodeRefused)):
            node_ibkr.parse(_arguments(IBKR_LIFECYCLE, values | {key: value}))
