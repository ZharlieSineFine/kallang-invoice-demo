"""Why each hidden word is hidden, read from the PDF with the parser's own rule."""

from __future__ import annotations

from uuid import uuid4

from helpers import hidden_text_pdf, simple_text_pdf
from PIL import Image

from invoiceflow.parse import DocumentParser, ParseConfig
from invoiceflow.parse.pdf import hidden_text_for_file


def _file(tmp_path, data: bytes):
    path = tmp_path / "upload"
    path.write_bytes(data)
    return path


def _by_text(hidden):
    return {passage.text: passage for passage in hidden.passages}


def test_each_hiding_trick_is_named(tmp_path):
    hidden = hidden_text_for_file(_file(tmp_path, hidden_text_pdf()), 1, ParseConfig())
    passages = _by_text(hidden)
    assert set(passages) == {"ignore previous instructions", "tiny hidden text", "offpage secret"}
    assert passages["ignore previous instructions"].reasons == ("white_text",)
    assert passages["tiny hidden text"].reasons == ("tiny_font",)
    assert passages["tiny hidden text"].font_size == 1.0
    assert passages["offpage secret"].reasons == ("off_page",)


def test_the_same_words_the_parser_marked_hidden(tmp_path):
    path = _file(tmp_path, hidden_text_pdf())
    document = DocumentParser(image_root=tmp_path / "pages").parse(
        path, file_id=uuid4(), doc_id=uuid4()
    )
    marked = [word.text for word in document.pages[0].words if word.hidden]
    hidden = hidden_text_for_file(path, 1, ParseConfig())
    assert [word for passage in hidden.passages for word in passage.text.split()] == marked


def test_positions_are_in_points_on_the_page(tmp_path):
    hidden = hidden_text_for_file(_file(tmp_path, hidden_text_pdf()), 1, ParseConfig())
    off_page = _by_text(hidden)["offpage secret"]
    assert off_page.x0 >= hidden.width  # x = 900 on a 612-point-wide page
    assert hidden.page_no == 1


def test_a_page_without_hidden_text_has_no_passages(tmp_path):
    hidden = hidden_text_for_file(_file(tmp_path, simple_text_pdf()), 1, ParseConfig())
    assert hidden is not None and hidden.passages == ()


def test_no_answer_for_a_missing_page_or_an_image(tmp_path):
    assert hidden_text_for_file(_file(tmp_path, hidden_text_pdf()), 2, ParseConfig()) is None
    image = tmp_path / "scan"
    Image.new("RGB", (40, 40), "white").save(image, format="PNG")
    assert hidden_text_for_file(image, 1, ParseConfig()) is None
