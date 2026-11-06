"""Raw research observations; fixed zero weight, no invented OPRA alpha (ADR-0016 O1/O2)."""

from dataclasses import dataclass
from decimal import Decimal

from nautilus_trader.model import InstrumentId


@dataclass(frozen=True)
class OptionsFactor:
    instrument_id: InstrumentId
    source: str
    revision: str
    evidence_sha256: str
    available_ns: int
    metric: str
    value: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise ValueError("Nautilus InstrumentId required")
        if any(not isinstance(v, str) or not v for v in (self.source, self.revision, self.metric)):
            raise ValueError("source, revision and raw metric required")
        if len(self.evidence_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.evidence_sha256
        ):
            raise ValueError("evidence SHA-256 required")
        if type(self.available_ns) is not int or self.available_ns < 0:
            raise ValueError("integer availability clock required")
        if self.value is not None and (
            not isinstance(self.value, Decimal) or not self.value.is_finite()
        ):
            raise ValueError("raw value must be a finite Decimal or unknown")

    @property
    def weight(self) -> Decimal:
        return Decimal(0)  # An admission boundary, not a tunable threshold.

    def value_at(self, now_ns: int) -> Decimal | None:
        return self.value if self.available_ns <= now_ns else None
