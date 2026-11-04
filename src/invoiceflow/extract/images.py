"""Image handling for extraction: which images to send and how to encode/hash them.

``images.mode`` decides whether page images are sent:

- ``auto``  — send whatever ``image_paths`` the request carries (WS6 sets them for scans).
- ``always`` — force images (the benchmark uses this to test digital PDFs with images).
- ``never``  — never send images, even for scans.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

IMAGES_MODES = ("auto", "always", "never")


def select_images(mode: str, image_paths: tuple[str, ...]) -> tuple[str, ...]:
    """Return the page images to send for the configured mode."""
    if mode == "never":
        return ()
    if mode in ("auto", "always"):
        return image_paths
    raise ValueError(f"unknown images mode {mode!r} (expected one of {IMAGES_MODES})")


def image_sha256(path: str | Path) -> str:
    """SHA-256 of an image file's bytes, used in the replay cache key."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def image_hashes(image_paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(image_sha256(path) for path in image_paths)


def encode_image_base64(path: str | Path) -> str:
    """Base64-encode an image file (no data URI prefix, as Ollama expects)."""
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")
