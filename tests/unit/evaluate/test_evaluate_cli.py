"""Evaluation CLI: baseline, report writing, and the gate."""

from invoiceflow.evaluate.cli import main


def test_baseline_writes_file(tmp_path):
    rc = main(["--baseline", "--out", str(tmp_path)])
    assert rc == 0
    baseline = tmp_path / "baseline.json"
    assert baseline.is_file()
    assert '"accuracy": 100.0' in baseline.read_text(encoding="utf-8")


def test_default_writes_json_and_markdown(tmp_path, capsys):
    rc = main(["--out", str(tmp_path)])
    assert rc == 0
    assert list(tmp_path.glob("eval_*.json"))
    assert list(tmp_path.glob("eval_*.md"))
    assert "accuracy 100.00%" in capsys.readouterr().out


def test_gate_passes_against_baseline(tmp_path):
    main(["--baseline", "--out", str(tmp_path)])
    assert main(["--gate", "--out", str(tmp_path)]) == 0


def test_gate_fails_without_baseline(tmp_path):
    assert main(["--gate", "--out", str(tmp_path)]) == 2
