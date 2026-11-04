"""Streamlit entry point: ``uv run streamlit run app/main.py``.

The pages are separate modules so ``streamlit.testing.v1.AppTest`` can render one page with
an injected fake backend. The sidebar radio is also the Queue page's navigation target
(``st.session_state["page"] = "Review"``).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit puts app/ on sys.path, not the repo root. Make ``import app.*`` work when this
# file is run as a script.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app.pages import batches, dashboard, queue, review, story, trace, upload  # noqa: E402

PAGES = {
    "Demo": story.render,
    "Upload": upload.render,
    "Queue": queue.render,
    "Review": review.render,
    "Trace": trace.render,
    "Dashboard": dashboard.render,
    "Batches": batches.render,
}


def render(backend=None) -> None:
    st.set_page_config(
        page_title="Kallang invoice review",
        page_icon="🧾",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.sidebar.title("Kallang Track 10")
    st.sidebar.caption("Invoice review · local demo · synthetic data")
    page = st.sidebar.radio("Page", list(PAGES), key="page")
    st.sidebar.divider()
    st.sidebar.toggle(
        "Technical view",
        key="technical_view",
        help="Show raw artifacts next to the friendly views: JSON, rule versions, model, SQL.",
    )
    PAGES[page](backend)


if __name__ == "__main__":
    render()
