from invoiceflow.extract import CacheEntry, ExtractionRecorder, cache_key


def _key(**overrides):
    base = {
        "model": "m",
        "prompt_version": "p",
        "schema_version": "s",
        "page_texts": ("a",),
        "image_hashes": ("h",),
        "params": {"temperature": 0},
    }
    base.update(overrides)
    return cache_key(**base)


def test_cache_key_deterministic():
    assert _key() == _key()


def test_cache_key_sensitive_to_every_input():
    assert _key(page_texts=("b",)) != _key()
    assert _key(image_hashes=("i",)) != _key()
    assert _key(params={"temperature": 1}) != _key()
    assert _key(model="other") != _key()
    assert _key(prompt_version="q") != _key()
    assert _key(schema_version="t") != _key()


def test_cache_key_ignores_param_order():
    a = cache_key(
        model="m",
        prompt_version="p",
        schema_version="s",
        page_texts=("a",),
        image_hashes=(),
        params={"seed": 42, "temperature": 0},
    )
    b = cache_key(
        model="m",
        prompt_version="p",
        schema_version="s",
        page_texts=("a",),
        image_hashes=(),
        params={"temperature": 0, "seed": 42},
    )
    assert a == b


def test_recorder_roundtrip(tmp_path):
    recorder = ExtractionRecorder(tmp_path)
    key = _key()
    entry = CacheEntry(
        key=key,
        result={"model": "m", "raw_output": "{}"},
        durations={"total_duration_ns": 5},
        context_warning=True,
    )
    recorder.save(entry)
    assert recorder.load(key) == entry
    assert (tmp_path / f"{key}.json").is_file()


def test_recorder_missing_returns_none(tmp_path):
    assert ExtractionRecorder(tmp_path).load("0" * 64) is None
