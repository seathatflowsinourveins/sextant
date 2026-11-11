"""WeKnora v0.9.0: loopback, disposable, retrieve-only, for dsh workers (deploy/weknora/README.md).

Static checks; the live run's receipt is in the PR body.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).parents[2]
HERE = ROOT / "deploy/weknora"
DIGEST = re.compile(r"^[a-z0-9./_-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$")
UPSTREAM_DEFAULT_SERVICES = {"app", "frontend", "docreader", "postgres", "redis"}


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor(
    "!override", lambda loader, node: loader.construct_sequence(cast(yaml.SequenceNode, node))
)


def _pins() -> dict[str, Any]:
    return json.loads((HERE / "pins.json").read_text())


def _override() -> dict[str, Any]:
    return yaml.load((HERE / "compose.override.yaml").read_text(), Loader=_Loader)  # noqa: S506


def test_pins_hold_the_tag_commit_and_every_image_by_digest() -> None:
    weknora = _pins()["weknora"]
    assert weknora["tag"] == "v0.9.0"
    assert weknora["commit"] == "f17ee8a8da901bd658a4cb25f40b5fd41adbfdd7"
    assert set(weknora["files"]) == {"docker-compose.yml", "config/config.yaml"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in weknora["files"].values())
    assert set(weknora["images"]) == UPSTREAM_DEFAULT_SERVICES
    services = _override()["services"]
    for service, image in weknora["images"].items():
        assert DIGEST.match(image), image
        assert services[service]["image"] == image, service
    launcher = (HERE / "weknora.sh").read_text()
    assert "raw.githubusercontent.com/Tencent/WeKnora/$commit/$file" in launcher
    assert "sha256sum -c --status" in launcher


def test_every_published_port_binds_loopback_and_replaces_upstreams() -> None:
    text = (HERE / "compose.override.yaml").read_text()
    published = {}
    for name, service in _override()["services"].items():
        for port in service.get("ports", []):
            assert port.startswith("127.0.0.1:"), (name, port)
            published[name] = port
    # Upstream publishes these two on every interface; the override must replace, not append.
    assert set(published) == {"app", "frontend"}
    assert len(re.findall(r"^    ports: !override \[", text, re.M)) == 2
    assert published["app"] == "127.0.0.1:21937:8080"
    assert _pins()["weknora"]["url"] == "http://127.0.0.1:21937/api/v1"


def test_embedding_has_one_tracked_source_equal_to_openvikings() -> None:
    mine = _pins()["embedding"]
    theirs = json.loads((ROOT / "deploy/openviking/pins.json").read_text())["embedding"]
    for key in ("repository", "revision", "file", "sha256"):
        assert mine[key] == theirs[key], key
    openviking = yaml.safe_load((ROOT / "deploy/openviking/compose.yaml").read_text())
    house = openviking["services"]["embeddings"]
    assert house["image"] == mine["image"]
    assert " ".join(house["command"]).startswith(f"-m /models/{mine['file']} {mine['args']} ")
    ov = json.loads((ROOT / "deploy/openviking/ov.conf").read_text())
    assert ov["embedding"]["dense"]["dimension"] == mine["dimension"]
    # pins.json is the only place: the override and the ingest read it, never a literal.
    embeddings = _override()["services"]["embeddings"]
    assert embeddings["image"] == "${WEKNORA_EMBEDDING_IMAGE:?}"
    assert "${WEKNORA_EMBEDDING_FILE:?} ${WEKNORA_EMBEDDING_ARGS:?}" in embeddings["command"]
    for path in ("compose.override.yaml", "weknora.sh", "weknora.py", "README.md"):
        text = (HERE / path).read_text()
        assert mine["file"] not in text and mine["image"].split("@")[1] not in text, path


def test_no_secret_value_is_tracked_and_keys_come_through_the_store() -> None:
    assignment = re.compile(
        r"(PASSWORD|SECRET|AES_KEY|API_KEY)\s*[:=]\s*['\"]?(?![$!{]|process\.env|[A-Z][A-Z0-9_]*\b)"
        r"[A-Za-z0-9+/_-]{8,}"
    )
    tracked = [*HERE.iterdir(), ROOT / "config/dsh/weknora.cordis.yml"]
    for path in tracked:
        assert not assignment.search(path.read_text()), path
    readme = (HERE / "README.md").read_text()
    known = (ROOT / "scripts/keys.sh").read_text().split("KNOWN=(", 1)[1].split("\n)", 1)[0]
    names = ("DB_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET", "SYSTEM_AES_KEY", "ADMIN_PASSWORD")
    for name in (*names, "API_KEY"):
        assert re.search(rf"^\s*WEKNORA_{name}\b", known, re.M), name
    for name in names[:4]:
        assert f"-k WEKNORA_{name}:{name}" in readme, name
    assert "scripts/with-keys.sh --strict" in readme
    assert not (HERE / ".env").exists()


def test_redis_reads_its_password_on_stdin_from_its_environment() -> None:
    override = _override()
    assert "secrets" not in json.dumps(override)
    redis = override["services"]["redis"]
    assert redis["environment"] == ["REDIS_PASSWORD"]  # a name: Compose passes the shell's value
    sh, script = redis["command"][:2], redis["command"][2]
    assert sh == ["sh", "-c"] and script.startswith("exec docker-entrypoint.sh redis-server - <<")
    assert re.findall(r"\$+\{?REDIS_PASSWORD", script) == ["$$REDIS_PASSWORD"]
    probe = script.replace("$$", "$").replace("docker-entrypoint.sh redis-server -", "cat")
    env = {"PATH": "/usr/bin:/bin", "REDIS_PASSWORD": "sentinel"}
    out = subprocess.run(["sh", "-c", probe], env=env, capture_output=True, text=True, timeout=9)
    assert out.stdout == "appendonly yes\nrequirepass sentinel\n"


def test_the_launcher_runs_only_documented_commands(tmp_path: Path) -> None:
    upstream = tmp_path / ".local/share/sextant-weknora/upstream" / _pins()["weknora"]["commit"]
    stub = tmp_path / "bin"
    stub.mkdir()  # stubs: Compose records its argv
    for tool in ("sha256sum", "chmod"):
        (stub / tool).symlink_to("/bin/true")
    (stub / "docker").write_text('#!/bin/sh\necho "$@" $COMPOSE_PROFILES $COMPOSE_FILE >~/argv')
    (stub / "docker").chmod(0o755)
    keys = ("DB_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET", "SYSTEM_AES_KEY")
    env = {**dict.fromkeys(keys, "sentinel"), "PATH": f"{stub}:/usr/bin:/bin"}
    env |= {"HOME": str(tmp_path), "COMPOSE_PROFILES": "neo4j", "COMPOSE_FILE": "x.yml"}
    sh = ["bash", HERE / "weknora.sh"]
    for form in ("up -d app", "ps", "pull", "down", "down -v"):
        subprocess.run([*sh, *form.split()], env=env, check=True, timeout=9)
        assert (tmp_path / "argv").read_text() == (
            f"compose --project-name sextant-weknora -f {upstream}/docker-compose.yml"
            f" -f {HERE}/compose.override.yaml {form}\n"
        )
    (tmp_path / "argv").unlink()
    for form in (
        "config|config --output o|convert|exec app env|run app env|logs|up|up -d neo4j|--x"
        "|-f x up -d|--env-file x up -d|--project-directory x up -d|--profile neo4j up -d|up -d"
        " --profile neo4j"
    ).split("|"):
        run = subprocess.run([*sh, *form.split()], env=env, capture_output=True, text=True)
        assert run.returncode == 2 and "up -d | pull | ps" in run.stderr, form
        assert "sentinel" not in run.stdout + run.stderr and not (tmp_path / "argv").exists()
    assert "only the default services" in (HERE / "README.md").read_text()


def test_the_ingest_is_the_one_writer_at_pinned_commits_and_never_ingests_urls() -> None:
    ingest = (HERE / "weknora.py").read_text()
    assert "/knowledge/file" in ingest and "/knowledge/url" not in ingest
    assert '"summary_enabled":false' in ingest  # retrieval needs no chat model
    assert 'corpus["commit"]' in ingest and "git" in ingest and "tempfile.mkdtemp" in ingest
    assert '"capabilities": ["retrieve"]' in ingest
    manifest = (ROOT / "docs/manifest.md").read_text()
    for corpus in _pins()["corpus"].values():
        assert re.fullmatch(r"[0-9a-f]{40}", corpus["commit"])
        assert corpus["commit"] in manifest, corpus["repository"]


def test_the_worker_patch_selects_the_upstream_plugin_retrieve_only() -> None:
    rows = yaml.safe_load((ROOT / "config/dsh/weknora.cordis.yml").read_text().replace("!!js", ""))
    plugin = next(row for row in rows if row.get("id") == "weknora")["config"]
    assert plugin["baseUrl"] == _pins()["weknora"]["url"]
    assert plugin["apiKey"].strip() == "process.env.WEKNORA_API_KEY"
    assert plugin["tools"] == dict(
        listKnowledgeBases=True, search=True, readDocument=True, ask=False
    )
    receipt = next(row for row in rows if "insert" in row)["insert"][0]
    assert receipt["config"]["profile"] == "worker" and receipt["config"]["workerWeKnora"] is True
    pin, commit = _pins()["dsh-weknora"], _pins()["weknora"]["commit"]
    # The tag's own tree, never npm's older 0.1.0; the integrity is the commit tarball's sha512.
    assert pin["spec"] == f"github:Tencent/WeKnora#{commit}&path:/packages/dsh-weknora"
    tarball = f"https://codeload.github.com/Tencent/WeKnora/tar.gz/{commit}"
    assert pin["allow_build"] == f"{pin['package']}@{tarball}#path:/packages/dsh-weknora"
    assert pin["integrity"].startswith("sha512-")
    readme = (HERE / "README.md").read_text()
    assert '."dsh-weknora".spec' in readme and "--from-default-profile headless" in readme
    # Only the worker profile lists the plugin; no shared bundle does.
    assert "dsh-weknora" not in (ROOT / "config/dsh/package.json").read_text()


def test_the_hold_is_lifted_for_the_worker_only() -> None:
    probe = """
import assert from 'node:assert/strict';
import { providersForProfile, tuiStartupContract } from './config/dsh/native-startup.mjs';
assert.ok('weknora' in providersForProfile('worker', { workerWeKnora: true }));
for (const profile of ['web', 'headless', 'tui', 'worker'])
  assert.ok(!('weknora' in providersForProfile(profile)));
assert.throws(() => providersForProfile('headless', { workerWeKnora: true }));
const row = { entryId: 'weknora', enabled: true, fiberPhase: 'active' };
assert.equal(tuiStartupContract({ entries: [row] }, {}).forbiddenActive, 1);
"""
    subprocess.run(["node", "--input-type=module", "-e", probe], cwd=ROOT, check=True, timeout=30)
    receipt = (ROOT / "config/dsh/startup-receipt.cordis.yml").read_text()
    hold = re.search(r"\{id: weknora, reason: '([^']+)'\}", receipt)
    assert hold and "no service or credential provisioned" not in hold[1]
    assert "worker profile only" in hold[1]
    for doc in ("docs/start.md", "docs/design.md"):
        assert "no service or credential provisioned" not in (ROOT / doc).read_text(), doc
