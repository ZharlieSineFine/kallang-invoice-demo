"""Where things live. Paths come from INVOICEFLOW_ROOT, or the folder holding pyproject.toml."""

import os
from datetime import date, datetime
from functools import cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml


def repo_root() -> Path:
    override = os.environ.get("INVOICEFLOW_ROOT")
    if override:
        return Path(override)
    return _discovered_root()


@cache
def _discovered_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("cannot find the repo root; set INVOICEFLOW_ROOT")


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Read ``KEY=VALUE`` pairs from ``.env`` into the environment.

    Real environment variables win, so ``LLM_MODE=replay make demo-data`` works without
    editing the file. Values may be quoted and may carry a trailing ``# comment``.
    Returns only the variables that were actually set.
    """
    env_path = path or repo_root() / ".env"
    if not env_path.is_file():
        return {}
    loaded: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        if key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


def config_path(name: str) -> Path:
    return repo_root() / "config" / f"{name}.yaml"


def load_config(name: str) -> dict[str, Any]:
    path = config_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path.name} (looked in {path.parent})")
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def data_dir() -> Path:
    return Path(os.environ.get("INVOICEFLOW_DATA", repo_root() / "data"))


def golden_dir() -> Path:
    return repo_root() / "tests" / "fixtures" / "golden"


def company_timezone() -> str:
    """Kallang's time zone name (``config/company.yaml``); the DAGs schedule in it."""
    return str(load_config("company").get("timezone", "Asia/Singapore"))


def singapore_today() -> date:
    """Today in Kallang's timezone, so date checks do not depend on the host or container."""
    return datetime.now(ZoneInfo("Asia/Singapore")).date()


def data_relative(path: str | None) -> str | None:
    """A path under data/ as stored in Postgres: relative, so host and containers both find it."""
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(data_dir().resolve()))
    except ValueError:
        return path
