"""Frozen-protocol identity for the ranking e2e harness.

The K3 section was added by the Muse writer on 2026-11-09 in commit ba5116d.
Its precise byte range in ``docs/research/2026-11-06-ranking.md`` is from the
``# K3 ...`` heading through the line before ``## K2 preregistration``: 30,488
bytes, sha256 fecd378a...  The K2 section is unchanged by that fold: 39,202
bytes from ``# K2 historical`` to EOF, sha256 fc019b18...  A run that cannot
reproduce both digests is not a frozen-protocol run.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

K3_SECTION_SHA256 = "fecd378a5b40fc2d6d2e03b16dda605c9f82102dad8e95735ffef24a459aca0b"
K2_SECTION_SHA256 = "fc019b18602429f0f641588eed45467ca555f4bbc568284327f1a346dd33426f"
K2_FOLD_HEADING = b"## K2 preregistration"
K2_HEADING = b"# K2 historical"
K3_HEADING = b"# K3 "


class ProtocolError(ValueError):
    """The checkout does not carry the exact frozen protocol bytes."""


@dataclass(frozen=True, slots=True)
class SectionReceipt:
    path: Path
    k3_sha256: str | None
    k2_sha256: str
    k3_present: bool

    def require_frozen(self) -> None:
        if not self.k3_present:
            raise ProtocolError(
                "K3 section absent: the arms cannot run before the preregistration is in the doc"
            )


def _line_start(raw: bytes, needle: bytes, *, after: int = 0) -> int:
    """Return the offset of ``needle`` when it starts a line, else raise."""
    if raw.startswith(needle):
        return 0
    index = raw.find(b"\n" + needle, after)
    if index < 0:
        raise ProtocolError(f"section heading absent at line start: {needle!r}")
    return index + 1


def extract_section(raw: bytes, heading: bytes, *, stop: bytes | None = None) -> bytes:
    """Return the heading's byte range; with ``stop``, end at the stop line.

    The heading and the stop must both start a line, so a ``## K3`` mention in
    the preamble cannot shadow the real ``# K3`` title.  The returned slice
    includes the blank line that precedes the stop heading, which is why the
    K3 section hashes to exactly 30,488 bytes.
    """
    start = _line_start(raw, heading)
    if stop is None:
        return raw[start:]
    end = _line_start(raw, stop, after=start)
    return raw[start:end]


def verify_protocol(
    path: Path,
    *,
    expected_k3: str = K3_SECTION_SHA256,
    expected_k2: str = K2_SECTION_SHA256,
) -> SectionReceipt:
    raw = path.read_bytes()
    k2 = extract_section(raw, K2_HEADING)
    k2_sha = hashlib.sha256(k2).hexdigest()
    if k2_sha != expected_k2:
        raise ProtocolError(f"K2 section digest moved: {k2_sha}")
    try:
        k3 = extract_section(raw, K3_HEADING, stop=K2_FOLD_HEADING)
    except ProtocolError:
        return SectionReceipt(path, None, k2_sha, False)
    k3_sha = hashlib.sha256(k3).hexdigest()
    if k3_sha != expected_k3:
        raise ProtocolError(f"K3 section digest moved: {k3_sha}")
    return SectionReceipt(path, k3_sha, k2_sha, True)
