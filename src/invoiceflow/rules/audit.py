"""The random audit sample of auto-passed invoices (CR-012).

Auto-passed invoices reach SAP without a person, so reviewer corrections cannot measure how
often they are wrong. A share of them is picked at random for a person to check against the
page; the share with an error estimates the auto-pass error rate.

The draw comes from the file's fingerprint and a seed, so the same file always gets the same
draw: reloading the demo picks the same invoices. In production the seed is kept secret, so
nobody can tell from a file whether it will be audited.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

_SCALE = 10_000  # draws are compared in hundredths of a percent
_HEX_DIGITS = 8


@dataclass(frozen=True)
class AuditSample:
    percent: Decimal
    seed: str

    @classmethod
    def from_config(cls, rules_config: Mapping[str, Any] | None) -> AuditSample | None:
        audit = (rules_config or {}).get("audit")
        if not audit:
            return None
        return cls(percent=Decimal(str(audit["sample_percent"])), seed=str(audit["seed"]))

    def picks(self, sha256: str) -> bool:
        digest = hashlib.sha256(f"{self.seed}:{sha256.strip()}".encode()).hexdigest()
        draw = int(digest[:_HEX_DIGITS], 16) % _SCALE
        return draw < self.percent * _SCALE / 100
