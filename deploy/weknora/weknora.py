"""WeKnora v0.9.0's own REST API, the one writer of its corpus; no ingestion mechanism of ours.

Tencent/WeKnora@f17ee8a8, website-docs/04-api/: 02-api-auth.md:9-75, 02-api-model-system.md:45-69
(an Embedding model on a `generic` OpenAI-compatible endpoint), 02-api-knowledge.md:16-34,
:329-378 (upload, `summary_enabled`), :419-442, 02-api-tenant.md:169-187. WEKNORA_ADMIN_PASSWORD
comes from scripts/with-keys.sh; no secret reaches argv, a file or a log.
  python3 -I deploy/weknora/weknora.py bootstrap | ingest [--limit N] | retrieve-key
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

PINS = json.loads((Path(__file__).parent / "pins.json").read_text())
EMAIL = "sextant@weknora.local"
# txt and Markdown parse natively (03-features/03-document-parsing.md:10,76). With no
# reStructuredText parser, .rst goes up unconverted under its own path plus .txt.
NATIVE, AS_TEXT = {".md", ".markdown", ".txt"}, {".rst"}


def call(method: str, path: str, token: str = "", body: Any = None, form: str = "") -> Any:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = body if form else json.dumps(body).encode() if body is not None else None
    if body is not None:
        kind = f"multipart/form-data; boundary={form}" if form else "application/json"
        headers["Content-Type"] = kind
    url = PINS["weknora"]["url"] + path  # pins.json's loopback URL, never a caller's
    request = urllib.request.Request(url, data, headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def login() -> tuple[str, int]:
    password = os.environ.get("WEKNORA_ADMIN_PASSWORD") or sys.exit("weknora: no admin password")
    status, reply = call("POST", "/auth/login", body={"email": EMAIL, "password": password})
    if status != 200:
        sys.exit(f"weknora: login refused ({status})")
    return reply["token"], reply["active_tenant"]["id"]


def bootstrap() -> None:
    body = {
        "username": "sextant",
        "email": EMAIL,
        "password": os.environ.get("WEKNORA_ADMIN_PASSWORD", ""),
    }
    print("register:", call("POST", "/auth/register", body=body)[0])
    token, embedding = login()[0], PINS["embedding"]
    if not any(m["name"] == embedding["file"] for m in call("GET", "/models", token)[1]["data"]):
        parameters = {
            "provider": "generic",
            "base_url": embedding["endpoint"],
            "embedding_parameters": {"dimension": embedding["dimension"]},
        }
        model = {
            "name": embedding["file"],
            "type": "Embedding",
            "source": "remote",
            "parameters": parameters,
        }
        print("embedding model:", call("POST", "/models", token, model)[0])


def bases(token: str) -> dict[str, Any]:
    return {kb["name"]: kb for kb in call("GET", "/knowledge-bases", token)[1]["data"] or []}


def fetch(corpus: dict[str, str], into: Path) -> Path:
    git = ["git", "-C", str(into / "repo")]
    subprocess.run(["git", "init", "-q", str(into / "repo")], check=True)
    url = f"https://github.com/{corpus['repository']}"
    subprocess.run([*git, "fetch", "-q", "--depth", "1", url, corpus["commit"]], check=True)
    tree = subprocess.run(
        [*git, "archive", corpus["commit"], corpus["path"]], check=True, capture_output=True
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(into)], input=tree, check=True)
    return into / corpus["path"]


def upload(token: str, kb: str, file: Path, name: str) -> int:
    b = uuid.uuid4().hex
    head = "".join(
        f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
        for k, v in (("fileName", name), ("process_config", '{"summary_enabled":false}'))
    )
    head += f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{Path(name).name}"'
    form = f"{head}\r\nContent-Type: text/plain\r\n\r\n".encode() + file.read_bytes()
    form += f"\r\n--{b}--\r\n".encode()
    return call("POST", f"/knowledge-bases/{kb}/knowledge/file", token, form, b)[0]


def total(token: str, kb: str, status: str = "") -> int:
    query = f"?parse_status={status}&page_size=1" if status else "?page_size=1"
    return int(call("GET", f"/knowledge-bases/{kb}/knowledge{query}", token)[1].get("total") or 0)


def ingest(limit: int) -> None:
    token = login()[0]
    models = call("GET", "/models", token)[1]["data"]
    model = next(m["id"] for m in models if m["name"] == PINS["embedding"]["file"])
    root = Path.home() / ".local/share/sextant-weknora/corpus"
    root.mkdir(parents=True, exist_ok=True)
    for name, corpus in PINS["corpus"].items():
        title = f"{name}@{corpus['commit']}"
        new = {"name": title, "type": "document", "embedding_model_id": model}
        kb = bases(token).get(title) or call("POST", "/knowledge-bases", token, new)[1]["data"]
        docs = fetch(corpus, Path(tempfile.mkdtemp(prefix=f"{corpus['commit']}.", dir=root)))
        files = sorted(p for p in docs.rglob("*") if p.suffix in NATIVE | AS_TEXT)[: limit or None]
        sent: dict[int, int] = {}
        for file in files:
            path = f"{corpus['path']}/{file.relative_to(docs)}"
            status = upload(token, kb["id"], file, path + ".txt" * (file.suffix in AS_TEXT))
            sent[status] = sent.get(status, 0) + 1
        documents, counts = total(token, kb["id"]), {}
        for _ in range(720):
            counts = {s: total(token, kb["id"], s) for s in ("completed", "failed")}
            if sum(counts.values()) >= documents:
                break
            time.sleep(5)
        print(f"{title}: {len(files)} files, uploads {sent}, {documents} documents, {counts}")


def retrieve_key() -> None:
    if sys.stdout.isatty():
        sys.exit("weknora: pipe this into scripts/keys.sh set WEKNORA_API_KEY; it prints a key")
    token, tenant = login()
    titles = {f"{n}@{c['commit']}" for n, c in PINS["corpus"].items()}
    ids = [kb["id"] for title, kb in bases(token).items() if title in titles]
    body = {"name": "dsh-worker-retrieve", "capabilities": ["retrieve"], "knowledge_base_ids": ids}
    status, reply = call("POST", f"/tenants/{tenant}/api-keys", token, body)
    if status != 201:
        sys.exit(f"weknora: key not created ({status})")
    # The plaintext is `token`; `api_key` comes back masked (internal/handler/tenant.go:688-693).
    sys.stdout.write(reply["data"]["token"] + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["bootstrap", "ingest", "retrieve-key"])
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    {"bootstrap": bootstrap, "retrieve-key": retrieve_key}.get(
        args.command, lambda: ingest(args.limit)
    )()
