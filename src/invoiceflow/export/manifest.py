"""Manifest JSON for an export batch and the SHA-256 of the CSV bytes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Manifest:
    batch_id: str
    row_count: int
    total: Decimal
    csv_sha256: str
    mapping_version: str
    model: str
    prompt_version: str
    rule_version: str
    layout: str = "hypothetical"
    # One entry per InvoiceID: invoice_id, doc_id, vendor_no, reference, first_row, row_count.
    invoices: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["total"] = format(self.total, "f")
        data["invoices"] = [dict(entry) for entry in self.invoices]
        return data

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
