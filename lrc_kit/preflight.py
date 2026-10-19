"""Check Lightroom plugin Lua *before* making anyone restart Lightroom.

Why this exists: a Lua error inside Lightroom surfaces as a single modal and
the only way to retry is for a human to click again. Syntax errors, path
normalisation, extension handling, field parsing and dedupe priority are all
pure logic that can be settled offline in a second.

Two levels, deliberately separated:

``syntax``  uses a real **Lua 5.1** compiler (``luac5.1 -p``) when available.
            This matters: Lightroom runs Lua 5.1, while the lupa Python binding
            ships Lua 5.4/5.5 and rejects constructs that are perfectly legal in
            5.1 (``attempt to assign to const variable`` is the classic false
            positive). Checking with the same major version Lightroom uses
            removes that whole class of confusion.

``logic``   concatenates the target file and a test snippet into one chunk and
            runs it under lupa with stub ``Lr*`` namespaces, so ``local
            functions`` from the target are callable directly. Stubs only prove
            "loads and the pure logic works"; they do not emulate Lightroom.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

__all__ = ["LuaUnavailable", "PreflightResult", "find_lua_compiler", "syntax_check", "logic_test"]

# Ordered by preference: 5.1 matches Lightroom exactly.
_LUA_COMPILERS = ("luac5.1", "luac-5.1", "luac", "luac5.4", "luac5.3")

STUBS = r"""
_G.import = function(name)
  return setmetatable({}, { __index = function(_, k) return function() return false end end })
end
for _, ns in ipairs({'LrView','LrDialogs','LrTasks','LrApplication','LrFileUtils','LrPrefs',
  'LrFunctionContext','LrSocket','LrExportSession','LrDevelopController','LrBinding','LrPathUtils',
  'LrStringUtils','LrColor','LrDate','LrLogger','LrSelection','LrMetadata'}) do
  _G[ns] = setmetatable({}, { __index = function(_, k) return function() return false end end })
end
_G.LrTasks.sleep = function() end
_G.LrTasks.pcall = function(fn, ...) return pcall(fn, ...) end
_G.LrTasks.startAsyncTask = function() return true end
"""

_RUN_SNIPPET = """function()
  local f, err = load(_G.__SRC, 'preflight')
  if not f then return "COMPILE_ERROR :: " .. tostring(err) end
  local ok, res = pcall(f)
  if not ok then return "RUNTIME_ERROR :: " .. tostring(res) end
  if res == nil then return "(no return value: the test snippet must end with return)" end
  return tostring(res)
end"""

_TRAILING_RETURN = re.compile(r"\n\s*return\b[^\n]*\n?\s*$")


class LuaUnavailable(RuntimeError):
    """Raised when neither a Lua compiler nor lupa is installed."""


@dataclass
class PreflightResult:
    ok: bool
    items: List[Dict[str, str]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {"ok": self.ok, "items": self.items, "notes": self.notes}


def find_lua_compiler() -> Optional[str]:
    for name in _LUA_COMPILERS:
        path = shutil.which(name)
        if path:
            return path
    return None


def luac_version(path: Optional[str] = None) -> Optional[str]:
    exe = path or find_lua_compiler()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stderr or out.stdout).strip()


def _luac_check(exe: str, path: pathlib.Path) -> Dict[str, str]:
    proc = subprocess.run([exe, "-p", str(path)], capture_output=True, text=True, timeout=30)
    if proc.returncode == 0:
        return {"file": str(path), "status": "ok", "detail": ""}
    detail = (proc.stderr or proc.stdout or "").strip().replace(str(path), "")[:500]
    return {"file": str(path), "status": "syntax_error", "detail": detail}


def _lupa_syntax(paths: Iterable[pathlib.Path]) -> PreflightResult:
    try:
        from lupa import LuaRuntime  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise LuaUnavailable(
            "No Lua compiler found and lupa is not installed.\n"
            "Install a Lua 5.1 compiler (Debian/Ubuntu: apt install lua5.1; "
            "macOS: brew install lua@5.1) or `pip install lupa`."
        ) from exc

    lua = LuaRuntime()
    lua.execute(STUBS)
    result = PreflightResult(ok=True)
    result.notes.append("checked with lupa (Lua 5.4/5.5): `const variable` errors here are false positives")
    for p in paths:
        try:
            src = pathlib.Path(p).read_text(encoding="utf-8")
        except OSError as exc:
            result.ok = False
            result.items.append({"file": str(p), "status": "read_error", "detail": str(exc)})
            continue
        lua.globals()["__SRC"] = src
        verdict = lua.eval("""function()
            local f, err = load(_G.__SRC, 'syntax')
            if f then return 'OK' end
            return 'SYNTAX_ERROR :: ' .. tostring(err)
        end""")()
        if verdict == "OK":
            result.items.append({"file": str(p), "status": "ok", "detail": ""})
        else:
            result.ok = False
            result.items.append({"file": str(p), "status": "syntax_error", "detail": str(verdict)})
    return result


def syntax_check(paths: Iterable[str | pathlib.Path]) -> PreflightResult:
    """Compile-check Lua files. Prefers a real Lua 5.1 compiler."""
    files = [pathlib.Path(p) for p in paths]
    missing = [str(p) for p in files if not p.exists()]
    if missing:
        return PreflightResult(ok=False, items=[{"file": m, "status": "missing", "detail": ""} for m in missing])

    exe = find_lua_compiler()
    if exe:
        result = PreflightResult(ok=True)
        result.notes.append(f"checked with {luac_version(exe) or exe}")
        for p in files:
            item = _luac_check(exe, p)
            result.items.append(item)
            if item["status"] != "ok":
                result.ok = False
                if "const" in item["detail"] and "5.1" not in (luac_version(exe) or ""):
                    result.notes.append("`const variable` is a Lua 5.4+ only error; Lightroom's 5.1 accepts it")
        return result

    return _lupa_syntax(files)


def logic_test(
    target: str | pathlib.Path,
    test: str | pathlib.Path,
    data: Optional[str | pathlib.Path] = None,
) -> PreflightResult:
    """Run a test snippet in the same chunk as the target file.

    The target's trailing ``return <module table>`` is stripped so the snippet
    can be appended. ``%(json)s`` inside the snippet is replaced with the
    contents of ``data`` -- useful for replaying a real captured payload.
    """
    try:
        from lupa import LuaRuntime  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise LuaUnavailable("logic_test needs lupa: pip install lupa") from exc

    target_p = pathlib.Path(target)
    test_p = pathlib.Path(test)
    if not target_p.exists():
        return PreflightResult(ok=False, items=[{"file": str(target_p), "status": "missing", "detail": ""}])
    if not test_p.exists():
        return PreflightResult(ok=False, items=[{"file": str(test_p), "status": "missing", "detail": ""}])

    src = target_p.read_text(encoding="utf-8")
    tsrc = test_p.read_text(encoding="utf-8")
    if data:
        payload = json.loads(pathlib.Path(data).read_text(encoding="utf-8"))
        tsrc = tsrc.replace("%(json)s", json.dumps(payload, ensure_ascii=False))

    stripped = _TRAILING_RETURN.sub("\n", src)
    notes: List[str] = []
    if stripped == src:
        notes.append(f"no trailing `return` stripped from {target_p}; if you see a syntax error, check that file")
    # Leading `return` is required: a Lua chunk whose last statement is an
    # expression discards its value, so `(function() ... end)()` on its own
    # silently yields nil and every test looks like it returned nothing.
    chunk = "return (function()\n" + stripped + "\n" + tsrc + "\nend)()"

    lua = LuaRuntime()
    lua.execute(STUBS)
    lua.globals()["__SRC"] = chunk
    verdict = str(lua.eval(_RUN_SNIPPET)())
    ok = not any(tag in verdict for tag in ("COMPILE_ERROR", "RUNTIME_ERROR", "FAIL"))
    return PreflightResult(ok=ok, items=[{"file": str(test_p), "status": "ok" if ok else "failed", "detail": verdict}], notes=notes)
