import pytest

from invoiceflow.pipeline.golden import load_golden


@pytest.fixture(scope="session")
def golden():
    return load_golden()


@pytest.fixture(scope="session")
def clean(golden):
    return golden.by_sha(golden.fixtures[0].sha256)


@pytest.fixture(scope="session")
def mismatch(golden):
    return next(f for f in golden.fixtures if f.fixture_id == "golden-a-total-mismatch")
