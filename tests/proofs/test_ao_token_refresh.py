"""AO's long-lived sessions get a fresh Sextant App token on every git and gh call.

Each AO session inherits the App's one-hour installation token when it spawns, and the supervisor
refreshes only the daemon. On 2026-11-06 a session's push failed with 401 Bad credentials, because
git used the user's global `/usr/bin/gh auth git-credential` helper with that stale token.

The fix uses two upstream mechanisms:
- git/git@v2.56.0 `a018953688f1b10bddf91bff8747068f5f4746a4`, at
  `Documentation/gitcredentials.adoc:199-201`, documents that an empty `credential.helper`
  resets the helper list, so AO's clone can override the global helper;
- the repo's own `bin/gh` wrapper, the one `github-app.sh tab` puts first on PATH, mints a token per
  call.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
WSL = ROOT / "deploy" / "wsl"
KEY = "credential.https://github.com.helper"


def test_the_daemon_puts_the_minting_gh_first_on_path() -> None:
    script = (WSL / "github-app.sh").read_text()
    daemon = 'daemon) PATH="$app/bin:$PATH" minted supervise -- bash "$here/ao.sh" daemon ;;'
    assert daemon in script


def test_aos_clone_resets_the_global_helper_and_asks_the_minting_gh(tmp_path: Path) -> None:
    clone = tmp_path / ".ao" / "repos" / "sextant-next"
    clone.mkdir(parents=True)
    env = {**os.environ, "HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": "/dev/null"}
    subprocess.run(["git", "init", "-q", str(clone)], check=True, env=env)
    for _ in range(2):  # idempotent: a second run leaves the same two values
        subprocess.run(["bash", str(WSL / "ao.sh"), "credential"], check=True, env=env)
    helpers = subprocess.run(
        ["git", "-C", str(clone), "config", "--local", "--get-all", KEY],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert helpers == ["", f"!{WSL / 'github-app' / 'bin' / 'gh'} auth git-credential"]


def test_project_sets_the_helper_before_aos_first_session() -> None:
    script = (WSL / "ao.sh").read_text()
    project = script[script.index("project() {") :]
    assert project.index("credential") < project.index("ao project get")
