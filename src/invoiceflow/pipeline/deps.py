"""Real pipeline dependencies: the integrator's wiring of the Phase 1 workstreams.

Each Phase 1 module implements a contract protocol; this module assembles them into the
``PipelineDeps`` the pipeline runs on. ``golden_deps`` (``pipeline/stubs.py``) remains for
tests that need the recorded fixtures.
"""

from __future__ import annotations

from typing import Any

from invoiceflow.coding import assign as coding_assign
from invoiceflow.contracts import (
    CodingMaster,
    NormalizedInvoice,
    PurchaseOrder,
    Vendor,
)
from invoiceflow.extract import build_client, load_model_config
from invoiceflow.locate import Locator
from invoiceflow.normalize import Normalizer, VendorMatcher
from invoiceflow.parse import DocumentParser
from invoiceflow.pipeline.stages import PipelineDeps
from invoiceflow.rules import Router, build_rules
from invoiceflow.settings import load_config


class Coder:
    """Adapts WS8's ``assign`` function to the ``Coder`` protocol."""

    def assign(
        self,
        invoice: NormalizedInvoice,
        vendor: Vendor | None,
        po: PurchaseOrder | None,
        master: CodingMaster,
    ):
        return coding_assign(invoice, vendor, po, master)


def build_deps(rules_config: dict[str, Any] | None = None) -> PipelineDeps:
    """The real pipeline: WS2 parse, WS3 extract, WS4 normalize/locate, WS5 rules, WS8 coding."""
    rules_config = rules_config or load_config("rules")
    return PipelineDeps(
        text_extractor=DocumentParser(),
        llm_client=build_client(load_model_config()),
        vendor_matcher=VendorMatcher(),
        normalizer=Normalizer(),
        coder=Coder(),
        locator=Locator(),
        rules=build_rules(rules_config),
        router=Router(rules_config),
    )
