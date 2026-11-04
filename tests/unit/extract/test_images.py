import base64
import hashlib

import pytest

from invoiceflow.extract import encode_image_base64, image_hashes, select_images


def test_select_images_never():
    assert select_images("never", ("a.png", "b.png")) == ()


def test_select_images_auto_and_always_pass_through():
    paths = ("a.png", "b.png")
    assert select_images("auto", paths) == paths
    assert select_images("always", paths) == paths
    assert select_images("auto", ()) == ()


def test_select_images_unknown_raises():
    with pytest.raises(ValueError, match="images mode"):
        select_images("sometimes", ("a.png",))


def test_encode_and_hash(tmp_path):
    path = tmp_path / "page.png"
    path.write_bytes(b"\x89PNG fake bytes")
    assert encode_image_base64(path) == base64.b64encode(b"\x89PNG fake bytes").decode()
    assert image_hashes((str(path),)) == (hashlib.sha256(b"\x89PNG fake bytes").hexdigest(),)
