"""Smoke test for the CLI: every command must at least parse and run.

The `%(json)s` in a help string crashed argparse once because help text is
%-formatted; a test that merely calls `build_parser()` catches that class of
breakage before a user does.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from lrc_kit.cli import build_parser, main
from tests.fixtures.make_catalog import build


class CliTests(unittest.TestCase):
    def test_parser_builds(self):
        parser = build_parser()
        self.assertIsNotNone(parser)

    def test_help_exits_cleanly(self):
        with self.assertRaises(SystemExit) as ctx:
            build_parser().parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_catalog_health_emits_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build(Path(tmp) / "c.lrcat")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["catalog", "health", str(path)])
            self.assertEqual(code, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["images"], 5)

    def test_preflight_syntax_returns_nonzero_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.lua"
            bad.write_text("local x = \n", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["preflight", "syntax", str(bad)])
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(buf.getvalue())["ok"])

    def test_missing_catalog_exits_2(self):
        buf = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stdout(buf):
            code = main(["catalog", "health", "/nonexistent/x.lrcat"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
