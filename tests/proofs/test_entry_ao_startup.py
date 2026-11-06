"""Keep the entry PR's AO startup regression separate from the shared AO cases."""

from pathlib import Path

from pytest import MonkeyPatch
from test_ao import _run


def test_bash_startup_cannot_bypass_the_fake_commands(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    startup = tmp_path / "startup.sh"
    startup.write_text("gh() { return 97; }\nao() { return 97; }\n")
    monkeypatch.setenv("BASH_ENV", str(startup))
    run, calls = _run(tmp_path, "claim", "57")
    assert run.returncode == 0, run.stderr
    assert any(call.startswith("spawn ") for call in calls)
