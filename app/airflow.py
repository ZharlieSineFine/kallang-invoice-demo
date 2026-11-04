"""Trigger ``invoice_intake`` through the Airflow REST API, with a link fallback.

Settings come from the environment and ``.env`` (``app.airflow`` never holds a secret).
When the trigger is not configured or the request fails, the Upload page shows the grid
link instead; the upload itself has already been saved to ``data/inbox/``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from invoiceflow.settings import load_env_file

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_DAG_ID = "invoice_intake"


@dataclass(frozen=True)
class AirflowSettings:
    base_url: str = DEFAULT_BASE_URL
    dag_id: str = DEFAULT_DAG_ID
    username: str | None = None
    password: str | None = None
    token: str | None = None
    configured: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AirflowSettings:
        load_env_file()
        values = env if env is not None else os.environ
        base = (values.get("AIRFLOW_BASE_URL") or "").strip().rstrip("/")
        return cls(
            base_url=base or DEFAULT_BASE_URL,
            dag_id=(values.get("AIRFLOW_DAG_ID") or DEFAULT_DAG_ID).strip(),
            username=(values.get("AIRFLOW_USERNAME") or "").strip() or None,
            password=values.get("AIRFLOW_PASSWORD") or None,
            token=(values.get("AIRFLOW_AUTH_TOKEN") or "").strip() or None,
            configured=bool(base),
        )

    @property
    def grid_url(self) -> str:
        return f"{self.base_url}/dags/{quote(self.dag_id)}/grid"

    @property
    def runs_url(self) -> str:
        return f"{self.base_url}/api/v1/dags/{quote(self.dag_id)}/dagRuns"


@dataclass(frozen=True)
class TriggerResult:
    started: bool
    message: str
    url: str
    run_id: str | None = None


def _auth(settings: AirflowSettings):
    if settings.token:
        return {"Authorization": f"Bearer {settings.token}"}, None
    if settings.username and settings.password:
        return {}, httpx.BasicAuth(settings.username, settings.password)
    return {}, None


def trigger_intake(
    settings: AirflowSettings,
    *,
    filename: str,
    sha256: str,
    client: Any | None = None,
) -> TriggerResult:
    url = settings.grid_url
    if not settings.configured:
        return TriggerResult(
            started=False,
            message=(
                "Airflow is not configured (set AIRFLOW_BASE_URL). "
                "The file is in data/inbox; start invoice_intake from the link."
            ),
            url=url,
        )
    headers, auth = _auth(settings)
    payload = {"conf": {"file_name": filename, "sha256": sha256, "source": "upload"}}
    try:
        if client is None:
            with httpx.Client(timeout=5.0) as http:
                response = http.post(settings.runs_url, headers=headers, auth=auth, json=payload)
        else:
            response = client.post(settings.runs_url, headers=headers, auth=auth, json=payload)
        response.raise_for_status()
        data = response.json() if callable(getattr(response, "json", None)) else {}
        run_id = data.get("dag_run_id") if isinstance(data, dict) else None
        return TriggerResult(
            started=True,
            message="invoice_intake started in Airflow.",
            url=url,
            run_id=str(run_id) if run_id else None,
        )
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        detail = f"HTTP {status}" if status else exc.__class__.__name__
        return TriggerResult(
            started=False,
            message=(
                f"Could not start invoice_intake in Airflow ({detail}). "
                "The file is in data/inbox; use the link."
            ),
            url=url,
        )


__all__ = ["AirflowSettings", "TriggerResult", "trigger_intake"]
