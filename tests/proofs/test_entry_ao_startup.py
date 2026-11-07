"""A parent shell's startup hooks never reach the AO harness's bash.

The leaky-mutant arm is the regression itself: it shows the same startup file would bypass
the PATH stand-ins if the child inherited it, so the as-is arm can fail.
"""

import os
import subprocess
from pathlib import Path

import pytest
import test_ao
from pytest import MonkeyPatch


@pytest.mark.parametrize("harness", ["as-is", "leaky-mutant"])
def test_bash_startup_cannot_bypass_the_fake_commands(
    tmp_path: Path, monkeypatch: MonkeyPatch, harness: str
) -> None:
    startup = tmp_path / "startup.sh"
    startup.write_text("gh() { return 97; }\nao() { return 97; }\n")
    monkeypatch.setenv("BASH_ENV", str(startup))
    if harness == "leaky-mutant":
        real = subprocess.run

        def leaky(cmd, *, env, **kwargs):
            return real(cmd, env={**env, "BASH_ENV": os.environ["BASH_ENV"]}, **kwargs)

        monkeypatch.setattr(test_ao.subprocess, "run", leaky)
    run, calls = test_ao._run(tmp_path, "claim", "57")
    spawned = run.returncode == 0 and any(call.startswith("spawn ") for call in calls)
    assert spawned is (harness == "as-is"), (run.returncode, run.stderr, calls)
