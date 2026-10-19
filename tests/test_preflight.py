"""Tests for the Lua preflight: syntax checking runs a real compiler."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lrc_kit import preflight

GOOD = """
local LrTasks = import 'LrTasks'
local function normalise(p)
  return (p:gsub('\\\\\\\\', '/')):lower()
end
return { normalise = normalise }
"""

BAD = """
local function broken(
  return 1
"""

# Legal in Lua 5.1 (what Lightroom runs) but rejected by Lua 5.4+.
FIVE_ONE_ONLY = """
local t = {}
for i = 1, 3 do t[i] = i end
local acc = 0
for _, v in ipairs(t) do acc = acc + v end
return { acc = acc }
"""


class SyntaxTests(unittest.TestCase):
    def _write(self, tmpdir, name, body):
        p = Path(tmpdir) / name
        p.write_text(body, encoding="utf-8")
        return p

    def test_good_file_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "good.lua", GOOD)
            res = preflight.syntax_check([p])
            self.assertTrue(res.ok, res.to_dict())
            self.assertEqual(res.items[0]["status"], "ok")

    def test_bad_file_fails_with_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "bad.lua", BAD)
            res = preflight.syntax_check([p])
            self.assertFalse(res.ok)
            self.assertEqual(res.items[0]["status"], "syntax_error")
            self.assertTrue(res.items[0]["detail"])

    def test_plain_lua_51_construct_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._write(tmp, "plain.lua", FIVE_ONE_ONLY)
            res = preflight.syntax_check([p])
            self.assertTrue(res.ok, res.to_dict())

    def test_missing_file_reported(self):
        res = preflight.syntax_check(["/nonexistent/x.lua"])
        self.assertFalse(res.ok)
        self.assertEqual(res.items[0]["status"], "missing")

    def test_compiler_is_lua_51_when_available(self):
        exe = preflight.find_lua_compiler()
        if not exe:
            self.skipTest("no Lua compiler installed")
        version = preflight.luac_version(exe) or ""
        self.assertIn("5.", version)


class LogicTests(unittest.TestCase):
    def setUp(self):
        try:
            import lupa  # noqa: F401
        except ImportError:
            self.skipTest("lupa not installed (pip install lrc-kit[preflight])")

    def test_snippet_can_call_local_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.lua"
            target.write_text(
                "local function double(n) return n * 2 end\nreturn { double = double }\n",
                encoding="utf-8",
            )
            test = Path(tmp) / "test.lua"
            test.write_text(
                "local out = {}\n"
                "local function chk(name, cond) out[#out+1] = (cond and 'OK  ' or 'FAIL ') .. name end\n"
                "chk('double(21)', double(21) == 42)\n"
                "return table.concat(out, '\\n')\n",
                encoding="utf-8",
            )
            res = preflight.logic_test(target, test)
            self.assertTrue(res.ok, res.to_dict())
            self.assertIn("OK", res.items[0]["detail"])

    def test_failing_assertion_is_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.lua"
            target.write_text("local function double(n) return n * 2 end\nreturn {}\n", encoding="utf-8")
            test = Path(tmp) / "test.lua"
            test.write_text("return 'FAIL double(1) == 3'\n", encoding="utf-8")
            res = preflight.logic_test(target, test)
            self.assertFalse(res.ok)


if __name__ == "__main__":
    unittest.main()
