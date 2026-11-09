"""The eight K3 seal items, with the unavailable ones left visible."""

from __future__ import annotations

from dataclasses import dataclass

AVAILABLE = "AVAILABLE"
PARTIAL = "PARTIAL"
NOT_RUN = "NOT_RUN"
ABSENT = "ABSENT"


@dataclass(frozen=True, slots=True)
class SealItem:
    name: str
    status: str
    receipt: str
    reason: str = ""

    @property
    def ready(self) -> bool:
        return self.status == AVAILABLE


def build(
    *,
    section_receipt: object | None,
    cohort_hash: str,
    session_list_sha256: str,
    registry_sha256: str,
    registry_partial_reason: str,
    data_receipts: dict[str, str],
    implementation: dict[str, str],
    custodian_ruling: str | None,
    other_family_review: str | None,
) -> tuple[SealItem, ...]:
    items = [
        SealItem(
            "session_list",
            AVAILABLE if session_list_sha256 else ABSENT,
            session_list_sha256,
            "" if session_list_sha256 else "no sealed session list",
        ),
        SealItem(
            "cohort_controls",
            AVAILABLE if cohort_hash else ABSENT,
            cohort_hash,
            "" if cohort_hash else "no sealed cohort/control list",
        ),
        SealItem(
            "market_data",
            AVAILABLE if data_receipts else ABSENT,
            ",".join(f"{day}:{digest[:12]}" for day, digest in sorted(data_receipts.items())),
            "" if data_receipts else "no per-session data receipts",
        ),
        SealItem(
            "baseline",
            AVAILABLE if data_receipts else ABSENT,
            "prior-session cumulative curves; zero carried forward; no future session",
        ),
        SealItem("registry", PARTIAL, registry_sha256, registry_partial_reason),
        SealItem(
            "implementation",
            AVAILABLE,
            "; ".join(f"{key}={value}" for key, value in sorted(implementation.items())),
        ),
        SealItem(
            "triallog",
            AVAILABLE if custodian_ruling else NOT_RUN,
            custodian_ruling or "",
            ""
            if custodian_ruling
            else "ledger binding NOT_RUN: the TrialLog custodian has not ruled (U5)",
        ),
        SealItem(
            "other_family_review",
            AVAILABLE if other_family_review else ABSENT,
            other_family_review or "",
            "" if other_family_review else "no second-family review at these exact hashes",
        ),
    ]
    assert len(items) == 8
    return tuple(items)


def trial_ready(items: tuple[SealItem, ...]) -> bool:
    return all(item.ready for item in items)
