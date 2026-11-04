"""Manifest and SHA-256 helpers."""

import json
from decimal import Decimal

from invoiceflow.export.manifest import Manifest, sha256_bytes


def test_manifest_serializes_decimal_as_string():
    manifest = Manifest(
        batch_id="b1",
        row_count=3,
        total=Decimal("2355.30"),
        csv_sha256="0" * 64,
        mapping_version="1",
        model="gemma4:12b",
        prompt_version="p1",
        rule_version="r1",
    )
    data = manifest.to_dict()
    assert data["total"] == "2355.30"
    assert isinstance(data["total"], str)
    json.loads(manifest.to_json())  # must be valid JSON


def test_sha256_of_bytes():
    assert sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
