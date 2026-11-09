"""The Sextant App's token: GitHub's JWT-then-installation-token flow, held only in a child's env.

Offline: a throwaway RSA key in a temp dir and a loopback stand-in for api.github.com, which
checks the JWT's RS256 signature with the key's public half and GitHub's iss, iat and exp claims.
"""

import base64
import json
import os
import shutil
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
WSL = ROOT / "deploy" / "wsl"
APP = WSL / "github-app"
APP_ID = 5645371
INSTALLATION = 4242
MARGIN = timedelta(minutes=10)  # token.mjs's MARGIN_MS


def _b64url(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


class Stub(BaseHTTPRequestHandler):
    """api.github.com's two endpoints, issuing ghs_test_N tokens that expire after `ttl`."""

    pub: Path
    ttl: timedelta
    minted: list[str]
    jwt_errors: list[str]

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _check_jwt(self) -> None:
        scheme, _, jwt = self.headers.get("authorization", "").partition(" ")
        head, body, sig = jwt.split(".")
        claims = json.loads(_b64url(body))
        sig_file = self.pub.with_suffix(f".{len(self.minted)}.sig")
        sig_file.write_bytes(_b64url(sig))
        verify = subprocess.run(
            ["openssl", "dgst", "-sha256", "-verify", str(self.pub), "-signature", str(sig_file)],
            input=f"{head}.{body}".encode(),
            capture_output=True,
        )
        now = time.time()
        if scheme.lower() != "bearer" or json.loads(_b64url(head))["alg"] != "RS256":
            self.jwt_errors.append("not a bearer RS256 JWT")
        if verify.returncode != 0:
            self.jwt_errors.append("signature does not verify")
        if str(claims["iss"]) != str(APP_ID) or claims["iat"] > now or claims["exp"] > now + 600:
            self.jwt_errors.append(f"claims {claims}")

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        self._check_jwt()
        if self.path != f"/app/installations/{INSTALLATION}/access_tokens":
            return self._send(404, {"message": "Not Found"})
        token = f"ghs_test_{len(self.minted)}"
        self.minted.append(token)
        expires = (datetime.now(UTC) + self.ttl).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._send(201, {"token": token, "expires_at": expires, "permissions": {}})

    def do_GET(self) -> None:
        self._check_jwt()
        if self.path != "/repos/seathatflowsinourveins/sextant/installation":
            return self._send(404, {"message": "Not Found"})
        self._send(200, {"id": INSTALLATION, "app_id": APP_ID})


@pytest.fixture(scope="module")
def node_modules() -> Path:
    if shutil.which("node") is None or shutil.which("openssl") is None:
        pytest.fail("node and openssl are part of the toolchain this proof needs")
    if not (APP / "node_modules" / "@octokit" / "auth-app").is_dir():
        subprocess.run(
            ["npm", "ci", "--prefix", str(APP), "--ignore-scripts", "--no-audit", "--no-fund"],
            check=True,
            capture_output=True,
        )
    return APP / "node_modules"


@pytest.fixture
def github(tmp_path: Path, node_modules: Path):
    """A temp copy of the runner beside its config, a fresh key, and the loopback stand-in."""
    key, pub = tmp_path / "app.pem", tmp_path / "app.pub"
    subprocess.run(["openssl", "genrsa", "-out", str(key), "2048"], check=True, capture_output=True)
    subprocess.run(
        ["openssl", "rsa", "-in", str(key), "-pubout", "-out", str(pub)],
        check=True,
        capture_output=True,
    )
    runner = tmp_path / "github-app"
    runner.mkdir()
    shutil.copy(APP / "token.mjs", runner / "token.mjs")
    (runner / "node_modules").symlink_to(node_modules)
    config = json.loads((WSL / "github-app.json").read_text())
    (tmp_path / "github-app.json").write_text(
        json.dumps({**config, "installation_id": INSTALLATION})
    )

    state = {"pub": pub, "ttl": timedelta(hours=1), "minted": [], "jwt_errors": []}
    handler = type("Handler", (Stub,), state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "SEXTANT_GITHUB_API_URL": f"http://127.0.0.1:{server.server_port}",
        "SEXTANT_GITHUB_APP_KEY_B64": base64.b64encode(key.read_bytes()).decode(),
    }
    yield runner / "token.mjs", env, handler, key.read_text()
    server.shutdown()


# The child reports what it got, then proves the key is not in its environment.
CHILD = (
    'printf "%s %s\\n" "$GH_TOKEN" "$AO_GITHUB_TOKEN" >> "$1"; '
    '[[ -z "${SEXTANT_GITHUB_APP_KEY_B64:-}" ]]'
)


def test_the_token_reaches_only_the_child_and_the_key_never_does(github, tmp_path: Path) -> None:
    runner, env, stub, pem = github
    out = tmp_path / "child"
    run = subprocess.run(
        ["node", str(runner), "run", "--", "bash", "-c", CHILD, "child", str(out)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert stub.jwt_errors == []
    assert out.read_text() == "ghs_test_0 ghs_test_0\n"
    # Never printed: not the token, the key, or the JWT.
    assert "ghs_test" not in run.stdout + run.stderr
    assert pem.splitlines()[1] not in run.stdout + run.stderr
    # Never written: only the child's own report holds it.
    holders = [p.name for p in tmp_path.rglob("*") if p.is_file() and b"ghs_test" in p.read_bytes()]
    assert holders == ["child"]


def test_the_installation_id_is_read_with_the_jwt(github) -> None:
    runner, env, stub, _ = github
    run = subprocess.run(
        ["node", str(runner), "installation"], env=env, capture_output=True, text=True, timeout=60
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == f"{INSTALLATION}\n" and stub.jwt_errors == []


def test_a_missing_key_or_a_remote_override_is_refused(github) -> None:
    runner, env, _, _ = github
    no_key = {k: v for k, v in env.items() if k != "SEXTANT_GITHUB_APP_KEY_B64"}
    remote = {**env, "SEXTANT_GITHUB_API_URL": "https://example.com"}
    for bad in (no_key, remote):
        run = subprocess.run(
            ["node", str(runner), "run", "--", "true"], env=bad, capture_output=True, text=True
        )
        assert run.returncode == 3, run.stderr


def test_the_supervisor_restarts_the_command_on_a_new_token_before_expiry(
    github, tmp_path: Path
) -> None:
    runner, env, stub, _ = github
    # Renew four seconds after each start: a 64-worker xdist run can delay the
    # first child past one second, and the supervisor would kill it before it
    # reported, losing the token-0 line this test asserts.
    stub.ttl = MARGIN + timedelta(seconds=4)
    out = tmp_path / "child"
    sup = subprocess.Popen(
        [
            "node",
            str(runner),
            "supervise",
            "--",
            "bash",
            "-c",
            f"{CHILD}; exec sleep 60",
            "child",
            str(out),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.time() + 30
    while time.time() < deadline and len(out.read_text().splitlines() if out.exists() else []) < 3:
        time.sleep(0.2)
    sup.send_signal(signal.SIGTERM)
    stdout, stderr = sup.communicate(timeout=30)
    seen = [line.split()[0] for line in out.read_text().splitlines()]
    assert seen[:3] == ["ghs_test_0", "ghs_test_1", "ghs_test_2"], stderr
    assert "ghs_test" not in stdout + stderr and stub.jwt_errors == []


def test_the_wrapper_routes_every_mode_through_the_key_store() -> None:
    script = (WSL / "github-app.sh").read_text()
    shim = APP / "bin" / "gh"
    for path in (WSL / "github-app.sh", shim):
        assert subprocess.run(["bash", "-n", str(path)], check=False).returncode == 0
    assert (
        'scripts/with-keys.sh" --strict -k "$key"' in script
        and "key=SEXTANT_GITHUB_APP_KEY_B64" in script
    )
    assert 'supervise -- bash "$here/ao.sh" daemon' in script
    assert "\ngh-app *args:\n" in (ROOT / "justfile").read_text()
    lock = json.loads((APP / "package-lock.json").read_text())
    assert lock["packages"]["node_modules/@octokit/auth-app"]["version"] == "8.3.1"
    assert json.loads((WSL / "github-app.json").read_text())["app_id"] == APP_ID
