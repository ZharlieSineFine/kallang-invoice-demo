"""AppTest coverage for the six pages and the main review actions."""

from __future__ import annotations

import tempfile
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.airflow import AirflowSettings
from app.pages import batches, dashboard, queue, review, trace, upload

ROOT = Path(__file__).resolve().parents[3]


def _script(body: str) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="ws7-apptest-"))
    path = directory / "page.py"
    path.write_text(
        f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n{body}\n",
        encoding="utf-8",
    )
    return path


def _run(page, backend, **kwargs) -> AppTest:
    module = page.__name__.split(".")[-1]
    path = _script(f"from app.pages import {module}\n{module}.render(*__args, **__kwargs)")
    at = AppTest(path, default_timeout=30, args=(backend,), kwargs=kwargs)
    at.run(timeout=30)
    assert not at.exception, [str(exc) for exc in at.exception]
    return at


def _run_main(backend) -> AppTest:
    path = _script("from app.main import render\nrender(*__args, **__kwargs)")
    at = AppTest(path, default_timeout=30, args=(backend,), kwargs={})
    at.run(timeout=30)
    assert not at.exception, [str(exc) for exc in at.exception]
    return at


def _set_doc(at: AppTest, doc_id) -> AppTest:
    at.session_state["selected_doc_id"] = doc_id
    return at


def _titles(at: AppTest) -> list[str]:
    return [title.value for title in at.title]


class _FakeReader:
    """Stands in for the background inbox reader (app.local_intake.InboxReader)."""

    def __init__(self):
        self.starts = 0

    def start(self) -> bool:
        self.starts += 1
        return True

    def progress(self):
        from app.local_intake import InboxProgress

        return InboxProgress()


def test_upload_page_without_airflow_says_the_app_reads_the_inbox(tmp_path):
    at = _run(upload, None, inbox=tmp_path, settings=AirflowSettings(), reader=_FakeReader())
    assert _titles(at) == ["Upload"]
    assert any("data/inbox" in caption.value for caption in at.caption)
    assert not at.link_button
    assert any("the app reads the inbox itself" in caption.value for caption in at.caption)


def test_upload_page_with_airflow_links_to_the_dag(tmp_path):
    settings = AirflowSettings(base_url="http://127.0.0.1:8080", configured=True)
    at = _run(upload, None, inbox=tmp_path, settings=settings, reader=_FakeReader())
    assert at.link_button[0].url == "http://127.0.0.1:8080/dags/invoice_intake"


def test_queue_page_lists_documents_and_opens_review(fake_backend):
    at = _run(queue, fake_backend)
    assert _titles(at) == ["Queue"]
    assert at.dataframe
    assert any("SAV-2026-0413" in frame.value.to_string() for frame in at.dataframe)
    at.get_by_key("queue_open").click().run()
    assert at.session_state["page"] == "Review"
    assert at.session_state["selected_doc_id"]


def test_review_page_shows_replay_badge_and_flagged_box(fake_backend, mismatch_bundle):
    at = _set_doc(
        AppTest(
            _script("from app.pages import review\nreview.render(*__args, **__kwargs)"),
            default_timeout=30,
            args=(fake_backend,),
            kwargs={},
        ),
        mismatch_bundle.document.doc_id,
    )
    at.run(timeout=30)
    assert not at.exception
    assert _titles(at) == ["Review"]
    markdown = "\n".join(item.value for item in at.markdown)
    assert ":violet-badge[Replayed response]" in markdown
    # Findings render as raw HTML so the message stays verbatim (no LaTeX math mangling).
    assert "R02" in markdown
    assert "S$1,080.00" in markdown
    assert at.image
    at.get_by_key("review_field").set_value("subtotal").run()
    assert len(at.image) >= 2


def test_review_correct_clears_r02_then_approve_sets_approved(fake_backend, mismatch_bundle):
    doc_id = mismatch_bundle.document.doc_id
    at = _set_doc(_run(review, fake_backend), doc_id)
    at.run(timeout=30)
    at.get_by_key("review_field").set_value("subtotal").run()
    at.get_by_key(f"fix_value_{doc_id}_subtotal").set_value("1,080.00").run()
    at.get_by_key("btn_correct").click().run(timeout=30)
    assert any(call[0] == "correct" for call in fake_backend.calls)
    after = fake_backend.bundles[doc_id]
    assert "R02" not in {finding.rule_id for finding in after.findings}
    assert after.field("subtotal").value_norm == "1080.00"
    assert after.field("subtotal").source.value == "REVIEWER"
    at.get_by_key("btn_approve").click().run(timeout=30)
    assert fake_backend.bundles[doc_id].document.status.value == "APPROVED"


def test_review_reject_sets_rejected(fake_backend, mismatch_bundle):
    doc_id = mismatch_bundle.document.doc_id
    at = _set_doc(_run(review, fake_backend), doc_id)
    at.run(timeout=30)
    at.get_by_key("btn_reject").click().run(timeout=30)
    assert fake_backend.bundles[doc_id].document.status.value == "REJECTED"


def test_review_confirm_records_the_action(fake_backend, clean_bundle):
    doc_id = clean_bundle.document.doc_id
    at = _set_doc(_run(review, fake_backend), doc_id)
    at.run(timeout=30)
    at.get_by_key("review_field").set_value("subtotal").run()
    at.get_by_key("btn_confirm").click().run(timeout=30)
    assert any(call[0] == "confirm" for call in fake_backend.calls)


def test_release_hold_requires_a_comment(on_hold_backend, mismatch_bundle):
    doc_id = mismatch_bundle.document.doc_id
    at = _set_doc(_run(review, on_hold_backend), doc_id)
    at.run(timeout=30)
    at.get_by_key("btn_release").click().run(timeout=30)
    assert any("comment" in error.value for error in at.error)
    at.get_by_key("hold_comment").set_value("Checked with finance.").run()
    at.get_by_key("btn_release").click().run(timeout=30)
    assert any(call[0] == "release_hold" for call in on_hold_backend.calls)


def test_trace_page_shows_runs_and_events(fake_backend, mismatch_bundle):
    at = _set_doc(_run(trace, fake_backend), mismatch_bundle.document.doc_id)
    at.run(timeout=30)
    assert _titles(at) == ["Trace"]
    assert any("Runs" in markdown.value for markdown in at.markdown)
    assert at.dataframe


def test_dashboard_page_labels_the_evaluation_synthetic(fake_backend, evaluation):
    fake_backend.evaluation = evaluation
    at = _run(dashboard, fake_backend)
    assert _titles(at) == ["Dashboard"]
    markdown = "\n".join(item.value for item in at.markdown)
    assert ":violet-badge[SYNTHETIC EVALUATION]" in markdown
    assert any(metric.label == "Documents processed" for metric in at.metric)


def test_dashboard_page_says_when_no_evaluation_exists(fake_backend):
    at = _run(dashboard, fake_backend)
    assert any("No evaluation report yet" in info.value for info in at.info)


def test_batches_page_lists_a_batch(fake_backend):
    at = _run(batches, fake_backend)
    assert _titles(at) == ["Batches"]
    assert any("B-001" in frame.value.to_string() for frame in at.dataframe)


def test_main_navigation_switches_pages(fake_backend):
    at = _run_main(fake_backend)
    assert "Demo" in _titles(at)  # the guided story is what opens first
    at.sidebar.radio[0].set_value("Dashboard").run(timeout=30)
    assert "Dashboard" in _titles(at)


def test_pages_have_no_streamlit_exceptions(fake_backend, mismatch_bundle):
    """A cheap guard: every page renders once with the fixture bundles."""
    for page in (upload, queue, review, trace, dashboard, batches):
        kwargs = (
            {"inbox": None, "settings": AirflowSettings(), "reader": _FakeReader()}
            if page is upload
            else {}
        )
        at = _set_doc(
            _run(page, fake_backend, **kwargs),
            mismatch_bundle.document.doc_id,
        )
        at.run(timeout=30)
        assert not at.exception, f"{page.__name__}: {[str(e) for e in at.exception]}"


class _FakeUpload:
    def __init__(self, name="synthetic-invoice.pdf", body=b"%PDF-1.7 synthetic invoice"):
        self.name, self._body, self.file_id = name, body, f"id-{name}"

    def getvalue(self) -> bytes:
        return self._body


def _uploads(monkeypatch, files):
    import streamlit as st

    def fake_uploader(*args, **kwargs):
        assert kwargs.get("accept_multiple_files") is True
        return list(files)

    monkeypatch.setattr(st, "file_uploader", fake_uploader)


def test_upload_page_saves_several_files_and_starts_reading(monkeypatch, tmp_path):
    _uploads(monkeypatch, [_FakeUpload(), _FakeUpload("second.pdf", b"%PDF-1.7 second")])
    reader = _FakeReader()
    at = _run(upload, None, inbox=tmp_path, settings=AirflowSettings(), reader=reader)
    assert sorted(p.name.split("-", 1)[1] for p in tmp_path.iterdir()) == [
        "second.pdf",
        "synthetic-invoice.pdf",
    ]
    assert any("Saved 2 files" in success.value for success in at.success)
    assert reader.starts == 1


def test_a_file_is_saved_once_even_when_the_page_reruns(monkeypatch, tmp_path):
    # After a file is read it leaves the inbox; a rerun must not put it back, or it would be
    # read again and counted as a discarded duplicate.
    _uploads(monkeypatch, [_FakeUpload()])
    reader = _FakeReader()
    at = _run(upload, None, inbox=tmp_path, settings=AirflowSettings(), reader=reader)
    for path in tmp_path.iterdir():
        path.unlink()  # read and moved out
    at.run(timeout=30)
    assert not list(tmp_path.iterdir())
    assert reader.starts == 1


def test_with_airflow_the_upload_goes_to_the_dag_not_the_app(monkeypatch, tmp_path):
    import httpx

    class _Refused:
        def post(self, *args, **kwargs):
            raise httpx.ConnectError("refused")

    _uploads(monkeypatch, [_FakeUpload()])
    reader = _FakeReader()
    settings = AirflowSettings(base_url="http://127.0.0.1:8080", configured=True)
    at = _run(upload, None, inbox=tmp_path, settings=settings, client=_Refused(), reader=reader)
    assert reader.starts == 0
    assert any("Could not start invoice_intake" in warning.value for warning in at.warning)


def test_with_airflow_one_run_reads_every_uploaded_file(monkeypatch, tmp_path):
    class _Accepting:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            import httpx

            self.calls.append(kwargs["json"])
            return httpx.Response(
                200, json={"dag_run_id": "manual__1"}, request=httpx.Request("POST", url)
            )

    _uploads(monkeypatch, [_FakeUpload(), _FakeUpload("second.pdf", b"%PDF-1.7 second")])
    client, reader = _Accepting(), _FakeReader()
    settings = AirflowSettings(
        base_url="http://api-server:8080", ui_url="http://127.0.0.1:8080", configured=True
    )
    at = _run(upload, None, inbox=tmp_path, settings=settings, client=client, reader=reader)
    assert reader.starts == 0
    assert len(client.calls) == 1
    assert len(client.calls[0]["conf"]["files"]) == 2
    assert any("invoice_intake started" in success.value for success in at.success)
    run_link = "http://127.0.0.1:8080/dags/invoice_intake/runs/manual__1"
    assert run_link in [button.url for button in at.link_button]


def test_review_line_item_and_coding_editors_save(monkeypatch, fake_backend, mismatch_bundle):
    import pandas as pd
    import streamlit as st

    def fake_editor(frame, **kwargs):
        edited = frame.copy()
        if "gl_account" in edited.columns:
            edited.loc[edited.index[0], "gl_account"] = "610100"
            edited.loc[edited.index[0], "cost_center"] = "KG1200"
            edited.loc[edited.index[0], "tax_code"] = "ZP"
        else:
            edited.loc[edited["line_no"] == 4, "amount"] = 90.0
        return pd.DataFrame(edited)

    monkeypatch.setattr(st, "data_editor", fake_editor)
    doc_id = mismatch_bundle.document.doc_id
    at = _set_doc(_run(review, fake_backend), doc_id)
    at.run(timeout=30)
    at.get_by_key("btn_save_lines").click().run(timeout=30)
    assert any(call[0] == "edit_line_items" for call in fake_backend.calls)
    assert fake_backend.bundles[doc_id].document.status.value == "AUTO_PASSED"
    at.get_by_key("btn_save_coding").click().run(timeout=30)
    assert any(call[0] == "recode" for call in fake_backend.calls)
    assert fake_backend.bundles[doc_id].coding_lines[0].coding_source.value == "REVIEWER"


def test_trace_page_handles_a_document_with_no_actions(fake_backend, clean_bundle):
    at = _set_doc(_run(trace, fake_backend), clean_bundle.document.doc_id)
    at.run(timeout=30)
    assert any("No reviewer actions" in caption.value for caption in at.caption)
    assert any("No findings" in caption.value for caption in at.caption)


def test_queue_page_handles_an_empty_database(fake_backend):
    fake_backend.bundles = {}
    at = _run(queue, fake_backend)
    assert any("No documents yet" in info.value for info in at.info)


def test_batches_page_handles_no_batches(fake_backend):
    fake_backend.batches = lambda: ()
    at = _run(batches, fake_backend)
    assert any("No export batches yet" in info.value for info in at.info)


def test_trace_page_handles_no_documents(fake_backend):
    fake_backend.bundles = {}
    at = _run(trace, fake_backend)
    assert any("No documents to trace" in info.value for info in at.info)


def test_picking_another_invoice_on_the_demo_page_sticks(fake_backend, clean_bundle):
    from app.pages import story

    at = _run(story, fake_backend)
    at.button(key="story_next").click().run(timeout=30)  # the Read step
    clean_id = clean_bundle.document.doc_id
    assert at.selectbox(key="story_document").value != clean_id

    at.selectbox(key="story_document").set_value(clean_id).run(timeout=30)
    assert not at.exception
    assert at.selectbox(key="story_document").value == clean_id
    assert at.session_state["selected_doc_id"] == clean_id

    at.run(timeout=30)  # and it stays picked on the next refresh
    assert at.selectbox(key="story_document").value == clean_id


def test_picking_another_document_on_the_review_page_sticks(fake_backend, clean_bundle):
    at = _run(review, fake_backend)
    first = at.selectbox(key="review_document").value
    other = next(doc_id for doc_id in fake_backend.bundles if doc_id != first)
    at.selectbox(key="review_document").set_value(other).run(timeout=30)
    assert at.selectbox(key="review_document").value == other
    assert at.session_state["selected_doc_id"] == other
