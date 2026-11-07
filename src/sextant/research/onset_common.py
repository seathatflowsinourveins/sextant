"""Shared file, hash and raw-bar helpers for the #130 onset modules."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from sextant.data.alpaca_history import raw_path, read_raw, symbol_name, timestamp


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git(repository: Path, *args: str) -> bytes:
    # The credentialed Python command needs the paper key; local git does not.
    clean = {
        k: v
        for k, v in os.environ.items()
        if not any(s in k.upper() for s in ("KEY", "SECRET", "TOKEN", "PASSWORD"))
    }
    return subprocess.check_output(
        ["git", *args], cwd=repository, env=clean, stderr=subprocess.DEVNULL
    )


def read_sessions(path: Path) -> list[date]:
    body = json.loads(path.read_text())
    return [date.fromisoformat(item["date"]) for item in body]


def read_bars(
    raw_root: Path, symbol: str, day: date, *, ordered: bool = False
) -> list[dict[str, Any]]:
    path = raw_path(raw_root, "1min", symbol_name(symbol), day)
    if not path.exists():
        return []
    rows = read_raw(path)
    return sorted(rows, key=lambda row: timestamp(row["t"])) if ordered else rows
