"""Upload, Airflow trigger, and evaluation-report helpers (no database, no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.airflow import AirflowSettings, trigger_intake
from app.evaluation import latest_evaluation, load_evaluation
from app.upload import list_inbox, safe_filename, save_upload, upload_target


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "bad",
                request=httpx.Request("POST", "http://airflow/api"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, *, response=None, error=None):
        self.response = response or FakeResponse(200, {"dag_run_id": "manual__1"})
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def test_airflow_settings_read_env_and_strip_slash():
    settings = AirflowSettings.from_env(
        {
            "AIRFLOW_BASE_URL": "http://airflow:8080/",
            "AIRFLOW_DAG_ID": "invoice_intake",
            "AIRFLOW_USERNAME": "demo",
            "AIRFLOW_PASSWORD": "secret",
        }
    )
    assert settings.configured
    assert settings.base_url == "http://airflow:8080"
    # Airflow 3: the DAG page holds the grid; the REST API is /api/v2 (v1 was removed).
    assert settings.grid_url == "http://airflow:8080/dags/invoice_intake"
    assert settings.runs_url == "http://airflow:8080/api/v2/dags/invoice_intake/dagRuns"


def test_links_use_the_browser_address_and_the_api_uses_the_container_address():
    # In the full stack the review app reaches Airflow as api-server:8080, which the
    # presenter's browser cannot resolve; links use AIRFLOW_UI_URL instead.
    settings = AirflowSettings.from_env(
        {"AIRFLOW_BASE_URL": "http://api-server:8080", "AIRFLOW_UI_URL": "http://127.0.0.1:8080/"}
    )
    assert settings.runs_url.startswith("http://api-server:8080/api/v2/")
    assert settings.grid_url == "http://127.0.0.1:8080/dags/invoice_intake"
    assert settings.run_url("manual__2026-11-18T03:00:00+00:00") == (
        "http://127.0.0.1:8080/dags/invoice_intake/runs/manual__2026-11-18T03%3A00%3A00%2B00%3A00"
    )


def test_airflow_is_not_configured_without_a_base_url():
    settings = AirflowSettings.from_env({})
    assert not settings.configured
    assert settings.grid_url == "http://127.0.0.1:8080/dags/invoice_intake"


def test_trigger_starts_the_dag():
    client = FakeClient()
    settings = AirflowSettings.from_env({"AIRFLOW_BASE_URL": "http://airflow:8080"})
    result = trigger_intake(settings, files=(("invoice.pdf", "a" * 64),), client=client)
    assert result.started
    assert result.run_id == "manual__1"
    assert result.url == "http://airflow:8080/dags/invoice_intake/runs/manual__1"
    url, kwargs = client.calls[0]
    assert url.endswith("/api/v2/dags/invoice_intake/dagRuns")
    # Airflow 3 requires logical_date in the body; null lets Airflow choose.
    assert "logical_date" in kwargs["json"] and kwargs["json"]["logical_date"] is None
    assert kwargs["json"]["conf"]["files"] == [{"name": "invoice.pdf", "sha256": "a" * 64}]


def test_one_run_reads_every_file_of_an_upload():
    client = FakeClient()
    settings = AirflowSettings(base_url="http://airflow", configured=True)
    files = (("a.pdf", "a" * 64), ("b.pdf", "b" * 64))
    trigger_intake(settings, files=files, client=client)
    assert len(client.calls) == 1
    assert [f["name"] for f in client.calls[0][1]["json"]["conf"]["files"]] == ["a.pdf", "b.pdf"]


def test_trigger_uses_a_bearer_token_without_leaking_it():
    client = FakeClient()
    settings = AirflowSettings(
        base_url="http://airflow",
        token="token-value",
        configured=True,
    )
    result = trigger_intake(settings, files=(("x.pdf", "b" * 64),), client=client)
    assert result.started
    assert client.calls[0][1]["headers"]["Authorization"] == "Bearer token-value"
    assert "token-value" not in result.message


def test_trigger_falls_back_to_the_link_on_http_error():
    client = FakeClient(response=FakeResponse(401))
    settings = AirflowSettings(base_url="http://airflow", configured=True)
    result = trigger_intake(settings, files=(("x.pdf", "c" * 64),), client=client)
    assert not result.started
    assert "HTTP 401" in result.message
    assert result.url == "http://airflow/dags/invoice_intake"


def test_trigger_falls_back_on_connection_error():
    client = FakeClient(error=httpx.ConnectError("refused"))
    settings = AirflowSettings(base_url="http://airflow", configured=True)
    result = trigger_intake(settings, files=(("x.pdf", "d" * 64),), client=client)
    assert not result.started
    assert "ConnectError" in result.message


def test_unconfigured_trigger_does_not_post():
    client = FakeClient()
    result = trigger_intake(AirflowSettings(), files=(("x.pdf", "e" * 64),), client=client)
    assert not result.started
    assert client.calls == []
    assert "not configured" in result.message


def test_safe_filename_blocks_traversal():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename(r"..\..\evil.pdf") == "evil.pdf"
    assert safe_filename("..") == "upload.bin"
    assert safe_filename("invoice 1.pdf") == "invoice_1.pdf"


def test_save_upload_is_content_addressed_and_idempotent(tmp_path):
    first = save_upload("invoice.pdf", b"%PDF-1.7 synthetic", directory=tmp_path)
    second = save_upload("invoice.pdf", b"%PDF-1.7 synthetic", directory=tmp_path)
    assert first.path == second.path
    assert first.existed is False
    assert second.existed is True
    assert first.path.read_bytes() == b"%PDF-1.7 synthetic"
    assert first.path.name.startswith(first.sha256[:12])
    assert first.path == upload_target(tmp_path, "invoice.pdf", first.sha256)


def test_save_upload_rejects_empty_bytes(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        save_upload("empty.pdf", b"", directory=tmp_path)


def test_list_inbox_returns_newest_first(tmp_path):
    save_upload("a.pdf", b"a", directory=tmp_path)
    save_upload("b.pdf", b"b", directory=tmp_path)
    items = list_inbox(tmp_path)
    assert len(items) == 2
    assert {item.name.rsplit("-", 1)[-1] for item in items} == {"a.pdf", "b.pdf"}
    assert list_inbox(tmp_path / "missing") == ()


def test_evaluation_loader_normalizes_the_report(tmp_path):
    report = {
        "generated_at": "2026-11-04T00:00:00Z",
        "set_name": "synthetic",
        "document_count": 12,
        "metrics": {"accuracy": 0.98, "ignored": "x"},
    }
    (tmp_path / "latest.json").write_text(json.dumps(report), encoding="utf-8")
    summary = latest_evaluation(tmp_path)
    assert summary is not None
    assert summary.synthetic
    assert summary.document_count == 12
    assert summary.metrics["accuracy"] == 0.98
    assert summary.metrics["metrics.accuracy"] == 0.98
    assert "ignored" not in summary.metrics


def test_evaluation_loader_counts_a_document_list_and_marks_live(tmp_path):
    report = {"set_name": "live", "documents": [{"id": 1}, {"id": 2}]}
    path = tmp_path / "eval-1.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    summary = load_evaluation(path)
    assert summary is not None
    assert summary.document_count == 2
    assert summary.synthetic is False


def test_evaluation_loader_ignores_missing_or_broken_reports(tmp_path):
    assert latest_evaluation(tmp_path) is None
    broken = tmp_path / "latest.json"
    broken.write_text("{not json", encoding="utf-8")
    assert latest_evaluation(tmp_path) is None
    broken.write_text("[]", encoding="utf-8")
    assert latest_evaluation(tmp_path) is None
