"""Vendor matching: GST registration number or UEN first, then a fuzzy name fallback."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from invoiceflow.contracts import InvoiceExtraction, Vendor
from invoiceflow.normalize.text import clean_text, normalize_text

FUZZY_MATCH_MIN_SCORE = 90.0
_ID_PUNCTUATION = re.compile(r"[^0-9A-Z]")


def _id_key(value: str | None) -> str:
    text = clean_text(value)
    if text is None:
        return ""
    return _ID_PUNCTUATION.sub("", text.upper())


def _vendor_ids(vendor: Vendor) -> set[str]:
    return {key for key in (_id_key(vendor.gst_reg_no), _id_key(vendor.uen)) if key}


def _match_by_id(extraction: InvoiceExtraction, vendors: tuple[Vendor, ...]) -> Vendor | None:
    printed = (
        _id_key(extraction.supplier_gst_reg_no),
        _id_key(extraction.supplier_uen),
    )
    for key in printed:
        if not key:
            continue
        for vendor in vendors:
            if key in _vendor_ids(vendor):
                return vendor
    return None


def _match_by_name(extraction: InvoiceExtraction, vendors: tuple[Vendor, ...]) -> Vendor | None:
    name = normalize_text(extraction.supplier_name)
    if not name:
        return None
    best: Vendor | None = None
    best_score = 0.0
    for vendor in vendors:
        score = fuzz.WRatio(name, normalize_text(vendor.name))
        if score >= FUZZY_MATCH_MIN_SCORE and score > best_score:
            best = vendor
            best_score = score
    return best


def match_vendor(extraction: InvoiceExtraction, vendors: tuple[Vendor, ...]) -> Vendor | None:
    """GST/UEN exact match first; fall back to the best name at WRatio >= 90."""
    return _match_by_id(extraction, vendors) or _match_by_name(extraction, vendors)


class VendorMatcher:
    """The ``VendorMatcher`` protocol implementation."""

    def match(self, extraction: InvoiceExtraction, vendors: tuple[Vendor, ...]) -> Vendor | None:
        return match_vendor(extraction, vendors)
