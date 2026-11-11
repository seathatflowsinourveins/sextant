"""dsh-test-autofix: the first admitted third-party plugin, interactive dsh-tui only.

CI-visible: the lock, the host installer and the register row carry the pin, dsh-tui only.
Host-only: the installed tree is the pinned packlist byte for byte.

Source: 1250589385/dsh-test-autofix@2246371b2869db52c0f9a77098777d66dbdbad32 (package 0.1.3,
  committed 2026-10-23T16:23:03Z): README.md install (`dsh plugin --profile <profile> add
  github:1250589385/dsh-test-autofix`), package.json `files` and `dsh.bundle.patch`,
  index.js:888-915 (inject tools; registers run_tests).
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK = json.loads((ROOT / "config/dsh/profile.lock.json").read_text())
GATE = json.loads((ROOT / ".github/gate/dsh-profile.json").read_text())
GATE_SPEC = json.loads((ROOT / ".github/gate/upstream/parity.json").read_text())
HOST_SPEC = ROOT / "deploy/wsl/lane-runtimes/parity.json"
MANIFEST = (ROOT / "docs/manifest.md").read_text()

PACKAGE = "dsh-test-autofix"
SHA = "2246371b2869db52c0f9a77098777d66dbdbad32"
SPEC = f"github:1250589385/dsh-test-autofix#{SHA}"
# The pin's packlist (npm pack --dry-run); pnpm installs it with bytes unchanged.
PINNED = {
    "CHANGELOG.md": "689c6873da00e6d03e031575e7b728b7d56dac1b596003aac0de6fb6c02b3909",
    "LICENSE": "b302e94d3f8df90b63f60ef05306ad13c320296f9fb09b57a3a5998627dd9561",
    "PROVENANCE.md": "17f16a70ddbc60e39812c598f7a08adb0d1a555b3ee63d152b9003b548b1ff00",
    "README.md": "4d26859d519628cbdf689e86d9889fa5222f1f37d77783e7e108a431bd6d6df2",
    "cordis.patch.yml": "2922fb6bd3fd1ec83acc315f1c64c632298b593753c7d6c59424082bcf6a94d7",
    "icon.svg": "d13fdb82353b3a2fc93054f62d964b80e3f5a8b2ebbb61f8c1458cd8adff5cf0",
    "index.js": "a54c83d03971f2d0bc6ddf19965b92ed78382d589e7a72f5760deb06eeb1e0a2",
    "lib/decode.js": "3e9f1e699946d315c1a7d46a8d9d6e400cbd30f0c70e616f7491a44e04f437fa",
    "locale/en.json": "85257436751f69014fdfd01d70c59eee28d34783ae6777dea2eb2ad32450a118",
    "locale/zh.json": "f9f26cef3357b63112747ade29df019e2ef69019768a3aed356e9b67f11d2884",
    "package.json": "00ee0f139841ed9e5a07946dccd9dff8e3c0e4ea5eb4e512be8e1934f7c45262",
}


def _parity():
    spec = importlib.util.spec_from_file_location("parity", HOST_SPEC.with_name("parity.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_lock_pins_it_in_the_interactive_profile_only() -> None:
    interactive = {row["package"]: row["spec"] for row in LOCK["interactive"]["dependencies"]}
    assert interactive[PACKAGE] == SPEC
    assert LOCK["interactive"]["bundles"][-1] == PACKAGE  # dsh plugin add appends the layer
    assert PACKAGE not in [row["package"] for row in LOCK["headless"]["bundles"]]
    assert PACKAGE not in [row["package"] for row in GATE["bundles"]]
    assert PACKAGE not in [
        row["package"] for row in GATE_SPEC["runtimes"]["dsh"]["quality"]["plugins"]
    ]


def test_the_host_installer_adds_it_to_dsh_tui_alone(tmp_path: Path) -> None:
    parity = _parity()
    rows = parity.SPEC["runtimes"]["dsh"]["quality"]["plugins"]
    row = {"package": PACKAGE, "spec": SPEC, "profiles": ["dsh-tui"]}
    assert [r for r in rows if r["package"] == PACKAGE] == [row]
    for name in ("dsh-tui", "acp", "headless"):
        (tmp_path / name).mkdir()
        missing = parity._quality_missing(tmp_path / name, name, ROOT)
        assert (SPEC in missing) is (name == "dsh-tui"), name


def test_the_register_row_records_the_five_gates() -> None:
    register = MANIFEST.split("\n## Third-party plugins\n", 1)[1].split("\n## ", 1)[0]
    rows = [row for row in register.splitlines() if row.startswith(f"| {PACKAGE}")]
    assert len(rows) == 1
    row = rows[0]
    for needed in (
        f"1250589385/dsh-test-autofix](https://github.com/1250589385/dsh-test-autofix)@`{SHA}`",
        "`dsh-test-autofix 0.1.3 · yellow 58/100 · shell, fs-read, env`",
        "red lines none",
        "launches test processes",
        "can start a suite in any existing directory",
        "approval before `run_tests` starts a process was not established",
        f"dsh plugin --profile dsh-tui remove {PACKAGE}",
        "test_dsh_test_autofix.py::test_the_installed_tree_is_the_pinned_tree",
    ):
        assert needed in row, needed


def _verify(home: Path, pinned: dict[str, str]) -> bool:
    """False if absent; an AssertionError on any difference."""
    package = home / "profiles" / "dsh-tui" / "node_modules" / PACKAGE
    if not package.exists() and not package.is_symlink():
        return False
    manifest = package / "package.json"
    assert manifest.is_file(), f"{package} is present without its package.json"
    found = json.loads(manifest.read_text())
    assert (found.get("name"), found.get("version")) == (PACKAGE, "0.1.3"), found
    # Nothing is exempt: the package has no dependencies, so a node_modules is unpinned.
    root = package.resolve()
    installed = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert installed == pinned
    return True


def _stand_in(home: Path, manifest: dict) -> dict[str, str]:
    package = home / "profiles" / "dsh-tui" / "node_modules" / PACKAGE
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps(manifest))
    (package / "index.js").write_text("export const inject = ['tools']\n")
    return {
        name: hashlib.sha256((package / name).read_bytes()).hexdigest()
        for name in ("package.json", "index.js")
    }


def test_the_proof_fails_on_an_extra_file_under_node_modules(tmp_path: Path) -> None:
    pinned = _stand_in(tmp_path, {"name": PACKAGE, "version": "0.1.3"})
    assert _verify(tmp_path, pinned)
    extra = tmp_path / "profiles/dsh-tui/node_modules" / PACKAGE / "node_modules/unexpected"
    extra.mkdir(parents=True)
    (extra / "index.js").write_text("module.exports = 1\n")
    with pytest.raises(AssertionError):
        _verify(tmp_path, pinned)


@pytest.mark.parametrize(
    "manifest",
    [None, {"name": "other", "version": "0.1.3"}, {"name": PACKAGE, "version": "0.1.4"}],
)
def test_a_present_package_directory_never_skips(tmp_path: Path, manifest: dict | None) -> None:
    pinned = _stand_in(tmp_path, manifest or {})
    package = tmp_path / "profiles/dsh-tui/node_modules" / PACKAGE
    if manifest is None:
        (package / "package.json").unlink()
    with pytest.raises(AssertionError):
        _verify(tmp_path, pinned)
    assert _verify(tmp_path / "absent", pinned) is False


def test_the_installed_tree_is_the_pinned_tree() -> None:
    home = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh-full")).expanduser()
    if not _verify(home, PINNED):
        pytest.skip(f"{home}: the pinned dsh-test-autofix is not composed in dsh-tui")
