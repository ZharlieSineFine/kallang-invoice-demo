"""Shared fixtures for the WS1 generator unit tests."""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from generator.plans import build_plans
from generator.seeds import Seeds, load_seeds
from invoiceflow.settings import repo_root


@pytest.fixture(scope="session")
def seeds() -> Seeds:
    return load_seeds(repo_root())


@pytest.fixture(scope="session")
def plans():
    return build_plans(42)
