"""PR-M3: AgentsView as the five-runtime usage-only archive (L1/L2).

Source: kenn-io/agentsview@v0.46.1 `65523169ae016d10112b70ed3410487204764fbc`
(MIT, published 2026-10-23): `cmd/agentsview/cli.go:123`, the `usage` command;
`internal/telemetry/telemetry.go:16,54-55`, the telemetry opt-out the wrapper sets;
`internal/parser/types.go`, the claude, codex, deepseek-harness, antigravity-cli
and muse session roots; `docs/configuration.md:9,46-47,248-249,1509-1510,2382,
2388-2395` and `docs/token-usage.md:756-769`, the config keys and query flags.
Static reads only: no binary, daemon, network or session file is touched.
"""

import json
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
MONITOR = ROOT / "deploy/wsl/monitor"
PIN_COMMIT = "65523169ae016d10112b70ed3410487204764fbc"
PIN_SHA256 = "e7822006d7bafa3aef9a5e4f7d7caffca56051bb039b848222a73633ed4c6c9b"
PIN_ASSET = "agentsview_0.46.1_linux_amd64.tar.gz"
ALL_INTERFACES = "0.0.0.0"  # noqa: S104 - the forbidden bind these proofs keep out


def _pins() -> dict[str, Any]:
    return json.loads((MONITOR / "agentsview-pins.json").read_text())


def _config() -> dict[str, Any]:
    return tomllib.loads((MONITOR / "agentsview-config.toml").read_text())


def test_agentsview_pin_is_release_cooled_and_checksummed() -> None:
    pins = _pins()
    row = pins["agentsview"]
    assert row["repository"] == "kenn-io/agentsview"
    assert row["tag"] == "v0.46.1" and row["version"] == "0.46.1"
    assert row["commit"] == PIN_COMMIT
    assert row["license"] == "MIT"
    assert row["asset"] == PIN_ASSET
    assert row["sha256"] == PIN_SHA256
    assert row["size"] == 66047182
    assert row["url"].endswith(f"/v0.46.1/{PIN_ASSET}")
    published = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
    checked = datetime.fromisoformat(pins["checked_at"].replace("Z", "+00:00"))
    assert checked.tzinfo == UTC
    assert checked - published >= timedelta(days=14)


def test_wrapper_disables_telemetry_updates_and_daemon_autostart() -> None:
    wrapper = (MONITOR / "agentsview.sh").read_text()
    for line in (
        "export AGENTSVIEW_TELEMETRY_ENABLED=0",
        "export DO_NOT_TRACK=1",
        "export AGENTSVIEW_DISABLE_UPDATE_CHECK=1",
        "export AGENTSVIEW_NO_DAEMON=1",
        "export AGENTSVIEW_ARCHIVE_CONTENT=usage",
    ):
        assert line in wrapper, line
    assert "AGENTSVIEW_DATA_DIR" in wrapper and "agentsview-data" in wrapper
    for var in (
        "OTEL_LOG_USER_PROMPTS",
        "OTEL_LOG_ASSISTANT_RESPONSES",
        "OTEL_LOG_RAW_API_BODIES",
        "OTEL_LOG_TOOL_CONTENT",
    ):
        unset = [line for line in wrapper.splitlines() if line.startswith("unset ")]
        assert any(var in line for line in unset), f"{var} stays unset"
    assert "agentsview-pins.json" in wrapper, "the version comes from the pin file"
    assert 'exec "$real" "$@"' in wrapper, "the pinned binary runs by path"
    assert "exec agentsview" not in wrapper, "never resolved through PATH"
    assert '[[ ! -x "$real" ]]' in wrapper, "a missing pin refuses instead of guessing"
    for bad in ("API_KEY", "with-keys", "curl", ALL_INTERFACES):
        assert bad not in wrapper, bad


def test_config_binds_loopback_and_archives_usage_only() -> None:
    text = (MONITOR / "agentsview-config.toml").read_text()
    config = tomllib.loads(text)
    assert config["host"] == "127.0.0.1"
    assert config["disable_update_check"] is True
    assert config["archive_content"] == "usage"
    for bad in (ALL_INTERFACES, '"full"', '"transcripts"', "github_token", "public_url"):
        assert bad not in text, bad
    assert "remote" not in text, "no remote sync surface is configured"
    for section in ("pg", "duckdb", "clickhouse", "vector", "recall", "proxy"):
        assert section not in config, section
    assert config["agents"].get("codex-cloud", {}).get("enabled") is not True


def test_config_registers_the_five_sextant_runtime_homes() -> None:
    text = (MONITOR / "agentsview-config.toml").read_text()
    agents = _config()["agents"]
    assert agents["claude"]["dirs"] == ["~/.claude/projects"]
    assert agents["codex"]["dirs"] == []
    lane = "~/.local/share/sextant-lane-runtimes/codex-home"
    assert agents["codex"]["homes"] == [lane]
    assert agents["deepseek-harness"]["dirs"] == ["~/.dsh-enhanced/sessions"]
    assert agents["antigravity-cli"]["dirs"] == ["~/.gemini/antigravity-cli"]
    assert agents["muse"]["dirs"] == ["~/.local/share/muse/sessions"]
    assert text.count("homes = ") == 1, "the installer rewrites this one line"
    installer = (MONITOR / "install-agentsview.sh").read_text()
    assert ".config/orca/codex-accounts" in installer and "*/home" in installer


def test_usage_query_is_offline_no_sync_json_under_nice_and_ionice() -> None:
    usage = (MONITOR / "agentsview-usage.sh").read_text()
    assert "usage daily --offline --no-sync --json" in usage
    assert "nice -n 19" in usage and "ionice -c 3" in usage
    assert "agentsview.sh" in usage, "the query goes through the wrapper"
    assert "agentsview sync" not in usage, "the query never refreshes sources"
    assert ALL_INTERFACES not in usage


def test_installer_verifies_the_tarball_and_starts_no_service() -> None:
    installer = (MONITOR / "install-agentsview.sh").read_text()
    assert "agentsview-pins.json" in installer
    assert "sha256sum -c" in installer
    assert installer.index("sha256sum -c") < installer.index("tar -xzf")
    assert "config.toml" in installer and ".local/bin/agentsview" in installer
    for bad in ("systemctl", "daemon start", "docker", ALL_INTERFACES):
        assert bad not in installer, bad


def test_manifest_row_names_the_pin_and_this_proof() -> None:
    manifest = (ROOT / "docs/manifest.md").read_text()
    rows = [r for r in manifest.splitlines() if r.startswith("| AgentsView usage-only")]
    assert len(rows) == 1
    assert PIN_COMMIT in rows[0]
    assert "test_monitor_agentsview.py" in rows[0]
