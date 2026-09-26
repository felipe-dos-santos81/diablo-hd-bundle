import json

import numpy as np

from builders import cel_frame, dun_bytes, min_bytes, pcx, sheet, til_bytes
from fakes import FakeArchive
from dtx.extract import extract_with
from dtx.handlers import sha1
from dtx.mpq import ArchiveStack

PAL = bytes(range(256)) * 3
KEY = "levels\\l1data\\l1"
COLUMN = [(0, 0)] * 8 + [(1, 0), (0, 0)]
BASE = {
    "levels\\towndata\\town.pal": PAL,
    "levels\\l1data\\l1_1.pal": PAL,
    f"{KEY}.cel": sheet([bytes([10]) * 1024]),
    f"{KEY}.min": min_bytes([COLUMN]),
    f"{KEY}.til": til_bytes([(0, 0, 0, 0)]),
    f"{KEY}.sol": bytes([0]),
    "levels\\l1data\\a.dun": dun_bytes([[1]]),
    "ui_art\\title.pcx": pcx(np.zeros((2, 2), np.uint8), np.zeros((256, 3), np.uint8)),
    "data\\good.cel": sheet([cel_frame([[1, 2]])]),
    "sfx\\x.wav": b"RIFF",
}


def run(tmp_path, files, **kw):
    archives = [FakeArchive("DIABDAT.MPQ", files, unnamed=["File00000001.xxx"])]
    if "hellfire" in kw:
        archives.insert(0, FakeArchive("hellfire.mpq", kw.pop("hellfire")))
    stack = ArchiveStack(archives)
    kw.setdefault("verify", True)
    return extract_with(stack, tmp_path / "out", widths={"data\\good.cel": 2}, variants={}, palettes={}, **kw)


def test_full_run_writes_report_and_manifest(tmp_path):
    report = run(tmp_path, BASE)
    out = tmp_path / "out"
    assert report["summary"]["failed"] == 0
    assert (out / "assets/levels/l1data/l1/tileset.json").exists()
    assert (out / "assets/levels/l1data/a.dun/layout.json").exists()
    assert (out / "assets/ui_art/title.pcx/meta.json").exists()
    assert (out / "assets/data/good.cel/meta.json").exists()
    assert (out / "palettes/levels/l1data/l1_1.pal.json").exists()
    saved = json.loads((out / "report.json").read_text())
    assert {"path": "sfx\\x.wav", "reason": "not graphics"} in saved["skipped"]
    assert saved["unnamed"] == {"DIABDAT.MPQ": ["File00000001.xxx"]}
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["hd_contract"]["scale"].startswith("integer")
    assert any(a["path"] == "data\\good.cel" and a["record"] == "assets/data/good.cel/meta.json"
               for a in manifest["assets"])


def test_second_run_is_unchanged_unless_forced(tmp_path):
    run(tmp_path, BASE)
    again = run(tmp_path, BASE)
    assert again["summary"]["exported"] == 0 and again["summary"]["unchanged"] > 0
    forced = run(tmp_path, BASE, force=True)
    assert forced["summary"]["unchanged"] == 0


def test_one_bad_file_does_not_stop_export(tmp_path):
    # Review Focus 5 (isolation)
    report = run(tmp_path, {**BASE, "data\\bad.cel": b"\xff\xff\xff\xff\x00\x00"})
    assert report["summary"]["failed"] == 1
    assert report["failed"][0]["path"] == "data\\bad.cel"
    assert (tmp_path / "out/assets/data/good.cel/meta.json").exists()


def test_identical_versions_export_once(tmp_path):
    # Review Focus 4
    report = run(tmp_path, BASE, hellfire={"data\\good.cel": BASE["data\\good.cel"]})
    assert not (tmp_path / "out/assets/@DIABDAT.MPQ").exists()
    assert [r["archive"] for r in report["exported"] if r["path"] == "data\\good.cel"] == ["hellfire.mpq"]


def test_different_versions_export_archive_copy(tmp_path):
    # Review Focus 4
    newer = sheet([cel_frame([[3, 4]])])
    run(tmp_path, BASE, hellfire={"data\\good.cel": newer})
    assert (tmp_path / "out/assets/data/good.cel/meta.json").exists()
    assert (tmp_path / "out/assets/@DIABDAT.MPQ/data/good.cel/meta.json").exists()


def test_only_filter(tmp_path):
    report = run(tmp_path, BASE, only={"palette"})
    kinds = {r["kind"] for r in report["exported"]}
    assert kinds == {"palette"}


def test_only_run_keeps_full_report_and_merges_manifest(tmp_path):
    out = tmp_path / "out"
    run(tmp_path, BASE)
    full_report = (out / "report.json").read_text()
    before = json.loads((out / "manifest.json").read_text())["assets"]

    newer_pal = bytes(reversed(PAL))
    report = run(tmp_path, {**BASE, "levels\\towndata\\town.pal": newer_pal}, only={"palette"})

    assert (out / "report.json").read_text() == full_report
    only_report = json.loads((out / "report-only.json").read_text())
    assert only_report == report and {r["kind"] for r in only_report["exported"]} == {"palette"}
    after = json.loads((out / "manifest.json").read_text())["assets"]
    assert [a for a in after if a["kind"] != "palette"] == [a for a in before if a["kind"] != "palette"]
    town = [a for a in after if a["path"] == "levels\\towndata\\town.pal"]
    assert len(town) == 1 and town[0]["sha1"] == sha1(newer_pal)
    assert {a["path"] for a in after} == {a["path"] for a in before}


def test_full_run_writes_report_json_not_report_only(tmp_path):
    run(tmp_path, BASE)
    assert (tmp_path / "out/report.json").exists()
    assert not (tmp_path / "out/report-only.json").exists()


def _records(out):
    return [p for p in out.rglob("*.json") if p.name not in ("manifest.json", "report.json", "report-only.json")]


def test_records_carry_exporter_fingerprint_and_verified(tmp_path):
    from dtx.extract import exporter_fingerprint

    run(tmp_path, BASE)
    out = tmp_path / "out"
    fingerprint = exporter_fingerprint()
    assert json.loads((out / "manifest.json").read_text())["exporter"] == fingerprint
    records = _records(out)
    assert records
    for path in records:
        record = json.loads(path.read_text())
        assert record["exporter"] == fingerprint and record["verified"] is True, path


def test_changed_exporter_fingerprint_re_exports(tmp_path, monkeypatch):
    run(tmp_path, BASE)
    monkeypatch.setattr("dtx.extract.exporter_fingerprint", lambda: "0" * 40)
    again = run(tmp_path, BASE)
    assert again["summary"]["unchanged"] == 0 and again["summary"]["exported"] > 0
    assert run(tmp_path, BASE)["summary"]["exported"] == 0


def test_unverified_records_are_re_exported_by_a_verify_run(tmp_path):
    run(tmp_path, BASE, verify=False)
    assert run(tmp_path, BASE, verify=False)["summary"]["exported"] == 0
    verified = run(tmp_path, BASE, verify=True)
    assert verified["summary"]["unchanged"] == 0 and verified["summary"]["exported"] > 0
    # verified records also count as unchanged for a later run without --verify
    assert run(tmp_path, BASE, verify=False)["summary"]["exported"] == 0


def test_exporter_fingerprint_covers_python_sources_and_data(tmp_path):
    from dtx.extract import exporter_fingerprint

    pkg = tmp_path / "dtx"
    (pkg / "formats").mkdir(parents=True)
    (pkg / "data").mkdir()
    (pkg / "a.py").write_text("a")
    (pkg / "formats" / "b.py").write_text("b")
    (pkg / "data" / "widths.json").write_text("{}")
    (pkg / "a.pyc").write_bytes(b"x")
    first = exporter_fingerprint(pkg)
    assert len(first) == 40 and first == exporter_fingerprint(pkg)
    (pkg / "a.pyc").write_bytes(b"y")
    assert exporter_fingerprint(pkg) == first
    (pkg / "formats" / "b.py").write_text("b2")
    second = exporter_fingerprint(pkg)
    assert second != first
    (pkg / "data" / "widths.json").write_text("{\"x\": 1}")
    assert exporter_fingerprint(pkg) != second
