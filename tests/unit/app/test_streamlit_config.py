"""The review app's Streamlit settings (``.streamlit/config.toml``)."""

from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[3] / ".streamlit" / "config.toml"


def _config() -> dict:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def test_the_app_is_always_light():
    # With no theme set, Streamlit follows the browser or macOS appearance, so a Mac in dark
    # mode showed a black app (2026-11-19).
    assert _config()["theme"]["base"] == "light"


def test_main_buttons_use_the_apps_blue_not_streamlits_red():
    # Next, Approve, Save correction and the export button; the user found red unpleasant.
    assert _config()["theme"]["primaryColor"] == "#1565c0"


def test_the_app_keeps_its_own_page_list_and_a_small_toolbar():
    client = _config()["client"]
    assert client["showSidebarNavigation"] is False
    assert client["toolbarMode"] == "minimal"
