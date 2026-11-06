"""The local key store: nothing named live can enter it."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPTS = ROOT / "scripts"
# The rule refuses any name containing this word, so the bare word is enough to prove it.
REFUSED = "LIVE"


def _run(*command: str, home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
    )


def test_live_keys_cannot_enter_the_store(tmp_path: Path) -> None:
    for script in ("keys.sh", "with-keys.sh", "key-systemd.sh"):
        assert subprocess.run(["bash", "-n", str(SCRIPTS / script)], check=False).returncode == 0
    receiver = ROOT / "deploy" / "wsl" / "receive-keys.sh"
    assert subprocess.run(["bash", "-n", str(receiver)], check=False).returncode == 0
    keys = SCRIPTS / "keys.sh"
    assert REFUSED not in keys.read_text().split("KNOWN=(", 1)[1].split(")", 1)[0]
    assert _run("bash", str(keys), "set", REFUSED, home=tmp_path).returncode == 3
    unregistered = _run("bash", str(keys), "set", "SOME_OTHER_KEY", "--sealed-stdin", home=tmp_path)
    assert unregistered.returncode == 3
    with_keys = str(SCRIPTS / "with-keys.sh")
    assert (
        _run("bash", with_keys, "--strict", "-k", REFUSED, "--", "true", home=tmp_path).returncode
        == 3
    )
    assert not list(tmp_path.rglob("*")), "a refusal must store nothing"


def test_t9_box_two_names_are_registered_and_the_northstar_app_keys_are_not() -> None:
    """T9 (sextant#58): the owner's Mac-only names move in; northstar's two App keys stay out."""
    known = (SCRIPTS / "keys.sh").read_text().split("KNOWN=(", 1)[1].split("\n)", 1)[0]
    names = {line.split("#", 1)[0].strip() for line in known.splitlines()} - {""}
    box_two = {f"ANTHROPIC_API_KEY_{n}" for n in range(1, 5)} | {
        "OPENAI_API_KEY",
        "META_API_KEY",
        "DATABENTO_API_KEY",
        "COHERE_API_KEY",
        "VOYAGE_API_KEY",
        "SHARADAR_API_KEY",
        "SEXTANT_GITHUB_APP_KEY_B64",
    }
    assert box_two <= names
    assert not {name for name in names if name.startswith("GITHUB_APP_NORTHSTAR")}
