"""parity.py's dsh-full step builds both config/dsh/profile.lock.json profiles.

Stub `dsh` and `pnpm` on PATH and a throwaway DSH_HOME, as test_runtime_parity.py does. The stub
applies dsh-v0.2.2-rc.1's documented effects: apps/cli/reference/README.md:15-17 (shipped template
copy), :83 (a non-shipped profile starts from dsh-base) and plugin-manager
src/operations.ts:90-120 (each newly added bundle is appended to dsh.profile.bundles).
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[2]
RUNTIMES = ROOT / "deploy/wsl/lane-runtimes"
LOCK = json.loads((ROOT / "config/dsh/profile.lock.json").read_text())
DOCTOR = ROOT / "scripts/dsh_profile_doctor.py"
BASE, HEADLESS = "@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"

STUB_DSH = """
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(" ".join(args) + "\\n")
if args == ["--version"]:
    print("0.2.2-rc.1")
    sys.exit(0)
names = json.loads(Path(os.environ["STUB_NAMES"]).read_text())
home = Path(os.environ["DSH_HOME"])
if args[0] == "plugin":
    profile = home / "profiles" / args[2]
    profile.mkdir(parents=True, exist_ok=True)
    manifest = profile / "package.json"
    if not manifest.exists():  # a non-shipped name starts from dsh-base alone
        manifest.write_text(json.dumps({"dsh": {"profile": {"bundles": [names["base"]]}}}))
    data = json.loads(manifest.read_text())
    dependencies = data.setdefault("dependencies", {})
    bundles = data["dsh"]["profile"]["bundles"]
    for spec in args[5:]:
        if Path(spec).is_dir():
            name = json.loads((Path(spec) / "package.json").read_text())["name"]
            dependencies[name] = "link:" + spec
            (profile / "node_modules").mkdir(exist_ok=True)
            (profile / "node_modules" / name).unlink(missing_ok=True)
            (profile / "node_modules" / name).symlink_to(spec)
        elif spec.startswith("github:"):
            name = names["github"][spec]
            dependencies[name] = spec
        else:
            name, version = spec.rsplit("@", 1)
            dependencies[name] = version
        if name not in names["plain"] and name not in bundles:
            bundles.append(name)
    manifest.write_text(json.dumps(data))
elif "--from-default-profile" in args:
    profile = home / "profiles" / args[1]
    profile.mkdir(parents=True)
    bundles = [names["base"], names["headless"]]
    (profile / "package.json").write_text(json.dumps({"dsh": {"profile": {"bundles": bundles}}}))
"""


def _parity() -> ModuleType:
    spec = importlib.util.spec_from_file_location("parity", RUNTIMES / "parity.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stub(path: Path, body: str, interpreter: str = "/bin/sh") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{interpreter}\n{body}")
    path.chmod(0o755)
    return path


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    rows = LOCK["interactive"]["dependencies"] + LOCK["headless"]["bundles"]
    names = {
        "base": BASE,
        "headless": HEADLESS,
        "github": {r["spec"]: r["package"] for r in rows if r["spec"].startswith("github:")},
        "plain": [
            r["package"]
            for r in LOCK["interactive"]["dependencies"]
            if r["package"] not in LOCK["interactive"]["bundles"]
        ],
    }
    (tmp_path / "names.json").write_text(json.dumps(names))
    tools = tmp_path / "tools"
    dsh = _stub(tools / "dsh", STUB_DSH, sys.executable)
    _stub(tools / "pnpm", f'printf "%s\\n" "$*" >> "{tmp_path / "pnpm.log"}"\n')
    monkeypatch.setenv("PATH", f"{tools}:/usr/bin:/bin")
    monkeypatch.setenv("STUB_LOG", str(tmp_path / "dsh.log"))
    monkeypatch.setenv("STUB_NAMES", str(tmp_path / "names.json"))
    monkeypatch.delenv("DSH_HOME", raising=False)
    skills = tmp_path / "skills"
    for name in _parity().shelf_names():
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: fixture\n---\n")
    return {"tmp": tmp_path, "home": tmp_path / "dsh-full", "dsh": dsh, "skills": skills}


def _install(parity: ModuleType, world: dict[str, Path], **options: bool) -> list[str]:
    skills = {path.name: path for path in world["skills"].iterdir()}
    return parity.install_dsh_full(skills, world["home"], [str(world["dsh"])], ROOT, **options)


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.exists() else []


def _doctor(profile: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DOCTOR), "--profile", str(profile)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip


def _target(row: dict) -> str:
    spec = row["spec"]
    if spec.startswith("link:"):
        return str(ROOT / row["link"])
    if spec.startswith("github:") or spec.startswith(row["package"] + "@"):
        return spec
    return f"{row['package']}@{spec}"


def _expected_calls() -> list[str]:
    calls = []
    for variant in ("interactive", "headless"):
        profile = LOCK[variant]["profile"]
        if variant == "interactive":
            rows, stack = LOCK[variant]["dependencies"], LOCK[variant]["bundles"]
        else:
            rows = LOCK[variant]["bundles"]
            stack = [row["package"] for row in rows]
            calls.append(f"--profile {profile} --from-default-profile headless --dump-config")
        by_name = {row["package"]: row for row in rows}
        plain = [row for row in rows if row["package"] not in stack]
        ordered = plain + [by_name[name] for name in stack if name not in (BASE, HEADLESS)]
        calls += [f"plugin --profile {profile} add --save-exact {_target(r)}" for r in ordered]
    return calls


def test_a_fresh_home_is_built_from_the_lock_with_exact_pins(world: dict[str, Path]) -> None:
    parity = _parity()
    _install(parity, world)
    assert _lines(world["tmp"] / "dsh.log") == _expected_calls()
    review = ROOT / "config/dsh/review-cmd"
    assert _lines(world["tmp"] / "pnpm.log") == [f"--dir {review} install --frozen-lockfile"] * 2
    assert len(list((world["home"] / "skills").iterdir())) == 25
    for variant in ("interactive", "headless"):
        profile = world["home"] / "profiles" / LOCK[variant]["profile"]
        workspace = (ROOT / "deploy/wsl/dsh/pnpm-workspace.yaml").read_text()
        assert (profile / "pnpm-workspace.yaml").read_text() == workspace
    tui = world["home"] / "profiles/dsh-tui/package.json"
    assert (
        json.loads(tui.read_text())["dsh"]["profile"]["bundles"] == LOCK["interactive"]["bundles"]
    )
    headless = json.loads((world["home"] / "profiles/dsh-headless/package.json").read_text())
    stack = [row["package"] for row in LOCK["headless"]["bundles"]]
    assert headless["dsh"]["profile"]["bundles"] == stack
    result = _doctor(tui)
    assert result.returncode == 0, result.stderr
    recorded = json.loads(tui.read_text())["dependencies"]  # a new home links into the checkout
    assert all(recorded[row["package"]] == f"link:{ROOT / row['link']}" for row in LINKS)


def test_a_second_run_changes_nothing_and_calls_nothing(world: dict[str, Path]) -> None:
    parity = _parity()
    _install(parity, world)
    before = parity._tree(world["home"])
    (world["tmp"] / "dsh.log").unlink()
    (world["tmp"] / "pnpm.log").unlink()
    _install(parity, world)
    assert parity._tree(world["home"]) == before
    assert not (world["tmp"] / "dsh.log").exists() and not (world["tmp"] / "pnpm.log").exists()


def test_a_missing_spec_is_the_only_one_added(world: dict[str, Path]) -> None:
    parity = _parity()
    _install(parity, world)
    tui = world["home"] / "profiles/dsh-tui"
    data = json.loads((tui / "package.json").read_text())
    last = LOCK["interactive"]["bundles"][-1]  # what `dsh plugin remove` leaves behind
    del data["dependencies"][last]
    data["dsh"]["profile"]["bundles"].remove(last)
    (tui / "package.json").write_text(json.dumps(data))
    (tui / "node_modules" / last).unlink()
    (world["tmp"] / "dsh.log").unlink()
    _install(parity, world)
    row = next(r for r in LOCK["interactive"]["dependencies"] if r["package"] == last)
    assert _lines(world["tmp"] / "dsh.log") == [
        f"plugin --profile dsh-tui add --save-exact {_target(row)}"
    ]
    assert _doctor(tui / "package.json").returncode == 0


@pytest.mark.parametrize("drift", ["one extra bundle", "one missing bundle"])
def test_the_doctor_fails_the_built_home_on_bundle_drift(
    world: dict[str, Path], drift: str
) -> None:
    _install(_parity(), world)
    manifest = world["home"] / "profiles/dsh-tui/package.json"
    data = json.loads(manifest.read_text())
    bundles = data["dsh"]["profile"]["bundles"]
    if drift == "one extra bundle":
        bundles.append("dsh-extra-fixture")
    else:
        bundles.remove("brooks-lint")
    manifest.write_text(json.dumps(data))
    result = _doctor(manifest)
    assert result.returncode == 2 and "bundles differ from the lock" in result.stderr


def test_a_foreign_dependency_is_refused_before_any_change(world: dict[str, Path]) -> None:
    parity = _parity()
    _install(parity, world)
    profiles = world["home"] / "profiles"
    for name in ("dsh-tui", "dsh-headless"):
        data = json.loads((profiles / name / "package.json").read_text())
        if name == "dsh-tui":  # a missing row the installer would otherwise add first
            del data["dependencies"][LOCK["interactive"]["bundles"][-1]]
        else:
            data["dependencies"]["dsh-extra-fixture"] = "1.0.0"
        (profiles / name / "package.json").write_text(json.dumps(data))
    before = parity._tree(world["home"])
    (world["tmp"] / "dsh.log").unlink()
    with pytest.raises(parity.Refused, match=r"dsh-headless.*dsh-extra-fixture"):
        _install(parity, world)
    assert parity._tree(world["home"]) == before and not (world["tmp"] / "dsh.log").exists()


def _bytes(root: Path) -> dict[str, bytes | None]:
    paths = [root, *root.rglob("*")] if root.is_dir() else [root]
    return {str(p): p.read_bytes() if p.is_file() else None for p in paths if p.exists()}


@pytest.mark.parametrize("found", ["an unknown directory", "a file", "a foreign profile"])
def test_an_unrecognised_home_is_left_unchanged_and_the_run_fails(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch, found: str
) -> None:
    parity = _parity()
    home = world["tmp"] / "home"
    target = home / ".dsh-full"
    if found == "a file":
        target.parent.mkdir(parents=True)
        target.write_text("owner notes\n")
    elif found == "an unknown directory":
        (target / "notes").mkdir(parents=True)
        (target / "notes/today.md").write_text("owner notes\n")
    else:
        (target / "profiles/dsh-tui").mkdir(parents=True)
        (target / "profiles/dsh-tui/package.json").write_text('{"dependencies": {"x": "1"}}')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sys, "argv", ["parity.py", "--runtime", "dsh-full"])
    monkeypatch.setattr(parity, "shelf", lambda cache: {})
    before = _bytes(home)
    assert parity.main() == 1
    assert _bytes(home) == before and not (world["tmp"] / "dsh.log").exists()


LINKS = [row for row in LOCK["interactive"]["dependencies"] if row["spec"].startswith("link:")]


def _copied_links(world: dict[str, Path]) -> dict[str, str]:
    """This host's layout: the four house bundles linked to copies inside the home."""
    tui = world["home"] / "profiles/dsh-tui"
    data = json.loads((tui / "package.json").read_text())
    for row in LINKS:
        copy = world["home"] / "src" / row["link"]
        copy.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / row["link"] / "package.json", copy / "package.json")
        data["dependencies"][row["package"]] = f"link:{copy}"
        (tui / "node_modules" / row["package"]).unlink()
        (tui / "node_modules" / row["package"]).symlink_to(copy)
    (tui / "package.json").write_text(json.dumps(data))
    (world["tmp"] / "dsh.log").unlink()
    return {row["package"]: data["dependencies"][row["package"]] for row in LINKS}


def test_a_default_run_keeps_and_reports_links_outside_the_checkout(
    world: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    parity = _parity()
    _install(parity, world)
    kept = _copied_links(world)
    capsys.readouterr()
    _install(parity, world)
    recorded = json.loads((world["home"] / "profiles/dsh-tui/package.json").read_text())
    assert {name: recorded["dependencies"][name] for name in kept} == kept
    assert not (world["tmp"] / "dsh.log").exists()
    lines = [line for line in capsys.readouterr().out.splitlines() if " kept " in line]
    assert len(lines) == 4
    assert all(
        any(f"{name} at {value[5:]}" in line for line in lines) for name, value in kept.items()
    )


def test_repoint_links_moves_them_into_the_checkout(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    parity = _parity()
    _install(parity, world)
    _copied_links(world)
    checked: list[Path] = []
    monkeypatch.setattr(parity, "_checkout_at_main", checked.append)
    _install(parity, world, repoint=True)
    stack = LOCK["interactive"]["bundles"]
    moved = sorted(LINKS, key=lambda row: stack.index(row["package"]))
    assert checked == [ROOT]
    assert _lines(world["tmp"] / "dsh.log") == [
        f"plugin --profile dsh-tui add --save-exact {_target(row)}" for row in moved
    ]
    assert _doctor(world["home"] / "profiles/dsh-tui/package.json").returncode == 0


def _git(path: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=Sextant",
         "-c", "user.email=sextant@Noesis.localdomain", "-c", "commit.gpgsign=false",
         "-C", str(path), *args], text=True,
    ).strip()  # fmt: skip


def test_repoint_links_refuses_a_checkout_off_its_fetched_main(world: dict[str, Path]) -> None:
    parity = _parity()
    checkout = world["tmp"] / "checkout"
    checkout.mkdir()
    _git(checkout, "init", "--initial-branch=main")
    for note in ("fetched main", "local work"):
        _git(checkout, "commit", "--allow-empty", "-m", note)
        if note == "fetched main":
            _git(checkout, "update-ref", "refs/remotes/origin/main", "HEAD")
    with pytest.raises(parity.Refused, match="origin/main"):
        parity.install_dsh_full({}, world["home"], [str(world["dsh"])], checkout, repoint=True)
    assert not world["home"].exists() and not (world["tmp"] / "dsh.log").exists()
    _git(checkout, "checkout", "--detach", "refs/remotes/origin/main")
    parity._checkout_at_main(checkout)


def test_parity_runs_the_dsh_full_step_on_the_enhanced_home() -> None:
    parity = _parity()
    full = parity.SPEC["runtimes"]["dsh"]["full"]
    assert full["home"] == ".dsh-full" and full["lock"] == "config/dsh/profile.lock.json"
    setup = (ROOT / "deploy/wsl/setup.sh").read_text()
    assert "python3 -I deploy/wsl/lane-runtimes/parity.py --runtime dsh-full\n" in setup
    assert "--repoint-links" not in setup  # a re-point is always a deliberate, separate run
