"""Export CLI: writes the reconcilable golden fixture and skips the mismatch."""

from invoiceflow.export.cli import main


def test_export_cli_writes_csv_and_skips_mismatch(tmp_path, capsys):
    rc = main(["--out", str(tmp_path)])
    assert rc == 0

    out = capsys.readouterr().out
    assert "skipping SAV-2026-0413" in out

    csv_files = list(tmp_path.glob("*.csv"))
    manifest_files = list(tmp_path.glob("*.manifest.json"))
    assert len(csv_files) == 1
    assert len(manifest_files) == 1

    text = csv_files[0].read_bytes().decode("utf-8")
    assert '"SAV-2026-0412"' in text
    assert '"SAV-2026-0413"' not in text
    assert '"Equipment rental, PO 4500012345"' in text
