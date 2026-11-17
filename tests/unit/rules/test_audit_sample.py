"""The random audit sample of auto-passed invoices (CR-012)."""

from __future__ import annotations

import hashlib
from decimal import Decimal

from invoiceflow.rules.audit import AuditSample

SHA = "73448bbea448bcca7401abc0b926a8ca7fa560970de4a31f7037899219a0dd7d"


def _fingerprints(count: int) -> list[str]:
    return [hashlib.sha256(str(n).encode()).hexdigest() for n in range(count)]


def test_the_same_file_always_gets_the_same_draw():
    sample = AuditSample(percent=Decimal("10"), seed="s")
    assert {sample.picks(SHA) for _ in range(5)} == {sample.picks(SHA)}


def test_about_the_configured_share_is_picked():
    sample = AuditSample(percent=Decimal("10"), seed="s")
    picked = sum(sample.picks(sha) for sha in _fingerprints(10_000))
    assert 850 <= picked <= 1150


def test_another_seed_draws_other_files():
    shas = _fingerprints(500)
    first = {sha for sha in shas if AuditSample(Decimal("10"), "a").picks(sha)}
    second = {sha for sha in shas if AuditSample(Decimal("10"), "b").picks(sha)}
    assert first != second


def test_zero_picks_nothing_and_a_hundred_picks_everything():
    shas = _fingerprints(200)
    assert not any(AuditSample(Decimal("0"), "s").picks(sha) for sha in shas)
    assert all(AuditSample(Decimal("100"), "s").picks(sha) for sha in shas)


def test_a_padded_fingerprint_draws_the_same():
    sample = AuditSample(percent=Decimal("50"), seed="s")
    assert sample.picks(SHA + "  ") is sample.picks(SHA)


def test_the_config_sets_ten_percent(rules_config):
    sample = AuditSample.from_config(rules_config)
    assert sample is not None
    assert sample.percent == Decimal("10")
    assert sample.seed


def test_no_audit_block_means_no_sample():
    assert AuditSample.from_config({}) is None
