"""Tests for the read-only catalog layer (stdlib unittest, no dependencies)."""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from lrc_kit import catalog
from tests.fixtures.make_catalog import build


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = build(Path(self.tmp.name) / "fixture.lrcat")
        self.conn = catalog.connect(str(self.path))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    # ---- connection ----
    def test_connect_is_read_only(self):
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM Adobe_images")

    def test_missing_catalog_raises(self):
        with self.assertRaises(FileNotFoundError):
            catalog.connect("/nonexistent/nowhere.lrcat")

    # ---- health ----
    def test_health_counts(self):
        h = catalog.health(self.conn)
        self.assertEqual(h["images"], 5)
        self.assertEqual(h["counts"]["AgLibraryFile"], 5)
        self.assertIn("suspiciously small", h["verdict"])

    def test_empty_catalog_is_flagged_as_shell(self):
        empty_path = build(Path(self.tmp.name) / "empty.lrcat", empty=True)
        conn = catalog.connect(str(empty_path))
        try:
            h = catalog.health(conn)
            self.assertEqual(h["images"], 0)
            self.assertIn("EMPTY SHELL", h["verdict"])
        finally:
            conn.close()

    # ---- stem lookup ----
    def test_collision_is_reported_not_hidden(self):
        res = catalog.find_by_stem(self.conn, ["_MIS7102"])
        self.assertEqual(len(res["found"]["_MIS7102"]), 2)
        self.assertIn("_MIS7102", res["collisions"])

    def test_session_hint_disambiguates(self):
        res = catalog.find_by_stem(self.conn, ["_MIS7102"], session_hint="0907")
        self.assertEqual(len(res["found"]["_MIS7102"]), 1)
        self.assertIn("0907-sessionA", res["found"]["_MIS7102"][0]["path"])
        self.assertEqual(res["collisions"], [])

    def test_missing_stem_listed(self):
        res = catalog.find_by_stem(self.conn, ["_MIS7994", "_MIS0000"])
        self.assertEqual(res["missing"], ["_MIS0000"])

    def test_windows_path_join(self):
        res = catalog.find_by_stem(self.conn, ["_MIS8000"])
        path = res["found"]["_MIS8000"][0]["path"]
        self.assertTrue(path.startswith("E:\\"), path)
        self.assertTrue(path.endswith("_MIS8000.JPG"), path)

    # ---- develop settings ----
    def test_parse_scalar_and_nested(self):
        got = catalog.parse_lua_table(
            's = { Exposure2012 = -0.15, ToneCurvePV2012 = { 0, 0, 255, 255 }, CameraProfile = "Adobe Standard" }'
        )
        self.assertAlmostEqual(got["Exposure2012"], -0.15)
        self.assertEqual(got["ToneCurvePV2012"][3], 255)
        self.assertEqual(got["CameraProfile"], "Adobe Standard")

    def test_parse_return_prefix_and_bools(self):
        got = catalog.parse_lua_table("return { Auto = true, Missing = nil, Name = 'x' }")
        self.assertTrue(got["Auto"])
        self.assertIsNone(got["Missing"])
        self.assertEqual(got["Name"], "x")

    def test_parse_rejects_garbage(self):
        with self.assertRaises(ValueError):
            catalog.parse_lua_table("not a table at all")

    def test_develop_settings_for_image(self):
        s = catalog.develop_settings(self.conn, 1)
        self.assertAlmostEqual(s["Exposure2012"], 0.45)
        self.assertEqual(s["Temperature"], 5450)

    def test_settings_absent_returns_none(self):
        self.assertIsNone(catalog.develop_settings(self.conn, 5))

    def test_edit_steps_not_settings_row(self):
        # image 1: three history steps; image 3: settings row but zero steps
        self.assertEqual(catalog.edit_step_count(self.conn, 1), 3)
        self.assertEqual(catalog.edit_step_count(self.conn, 3), 0)

    # ---- style report ----
    def test_style_report_shape(self):
        rep = catalog.style_report(self.conn)
        self.assertEqual(rep["images_total"], 5)
        self.assertEqual(rep["images_with_settings"], 3)
        self.assertIn("Exposure2012", rep["sliders"])
        self.assertGreaterEqual(rep["sliders"]["Exposure2012"]["nonzero"], 3)
        self.assertTrue(rep["reading"])

    def test_style_report_rating_filter(self):
        rep = catalog.style_report(self.conn, rating_min=4)
        self.assertEqual(rep["images_total"], 2)

    # ---- export ----
    def test_export_jsonl_gz(self):
        out = Path(self.tmp.name) / "dump.jsonl.gz"
        res = catalog.export_develop(self.conn, out)
        self.assertEqual(res["written"], 5)
        self.assertEqual(res["unparsed"], 0)
        with gzip.open(out, "rt", encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh]
        self.assertEqual(len(rows), 5)
        self.assertAlmostEqual(rows[0]["settings"]["Exposure2012"], 0.45)

    def test_export_plain_and_filtered(self):
        out = Path(self.tmp.name) / "dump.jsonl"
        res = catalog.export_develop(self.conn, out, rating_min=4, gz=False)
        self.assertEqual(res["written"], 2)
        self.assertTrue(out.read_text(encoding="utf-8").strip())


class PrefsTests(unittest.TestCase):
    def test_reads_active_catalog_from_agprefs(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefs_dir = Path(tmp)
            fake_catalog = prefs_dir / "My Catalog.lrcat"
            fake_catalog.write_bytes(b"x")
            (prefs_dir / "Lightroom Classic 13 Preferences.agprefs").write_text(
                'libraryToLoad20 = "%s",\nlibraryToLoad19 = "C:\\\\old\\\\Old Catalog.lrcat",\n' % str(fake_catalog).replace("\\", "\\\\"),
                encoding="utf-8",
            )
            found = catalog.catalogs_from_prefs(prefs_dir)
            self.assertEqual(len(found), 2)
            keys = {f["key"] for f in found}
            self.assertIn("libraryToLoad20", keys)
            newest = [f for f in found if f["key"] == "libraryToLoad20"][0]
            self.assertTrue(newest["exists"])


if __name__ == "__main__":
    unittest.main()
