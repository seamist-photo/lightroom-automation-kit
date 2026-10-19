"""Read a Lightroom Classic catalog (.lrcat) without opening Lightroom.

A ``.lrcat`` file is a plain SQLite database. Lightroom keeps it open with
write-ahead logging, so everything here connects in read-only mode
(``mode=ro`` + ``PRAGMA query_only``) and never touches the writer.

Two things this module refuses to guess:

1. **Which catalog is the real one.** Lightroom happily leaves empty shells
   around (a freshly created catalog is ~2 MB while a real one is hundreds of
   MB). ``health()`` reports table counts so an empty shell is obvious instead
   of being mistaken for "the user has no photos".
2. **Whether a filename is unique.** ``_MIS7102.NEF`` can exist in two
   sessions taken months apart. ``find_by_stem()`` returns every copy with its
   path and capture time, and flags the stem as a collision.

The developed-settings blob is a Lua table serialised as text, not JSON, so
``parse_lua_table()`` is a small hand-written parser. There is no Lua
dependency.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

__all__ = [
    "DEFAULT_DEVELOP_KEYS",
    "connect",
    "default_prefs_dirs",
    "catalogs_from_prefs",
    "scan_for_catalogs",
    "health",
    "photo_count",
    "find_by_stem",
    "photo_paths_sql",
    "parse_lua_table",
    "develop_settings",
    "export_develop",
    "style_report",
]

# Sliders that describe the "user's ruler". Not exhaustive, just the ones that
# carry most of the intent in a normal wedding/portrait edit.
DEFAULT_DEVELOP_KEYS = [
    "Exposure2012",
    "Contrast2012",
    "Highlights2012",
    "Shadows2012",
    "Whites2012",
    "Blacks2012",
    "Clarity2012",
    "Dehaze",
    "Vibrance",
    "Saturation",
    "Temperature",
    "Tint",
    "Texture",
]

# Tables worth counting when judging whether a catalog is real.
_COUNT_TABLES = [
    "Adobe_images",
    "AgLibraryFile",
    "AgLibraryFolder",
    "AgLibraryRootFolder",
    "Adobe_imageDevelopSettings",
    "Adobe_libraryImageDevelopHistoryStep",
    "AgLibraryCollection",
    "Adobe_imageDevelopSnapshots",
]


# --------------------------------------------------------------------------
# locating a catalog
# --------------------------------------------------------------------------

def default_prefs_dirs() -> List[Path]:
    """Per-platform directories that hold Lightroom Classic preferences."""
    home = Path.home()
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        return [Path(appdata) / "Adobe" / "Lightroom"]
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / "Adobe" / "Lightroom"]
    # Linux is not a supported Lightroom platform; kept for Wine/cross-checking.
    return [
        home / ".wine" / "drive_c" / "users" / os.environ.get("USER", "user")
        / "AppData" / "Roaming" / "Adobe" / "Lightroom",
        home / ".config" / "Adobe" / "Lightroom",
    ]


_LIBRARY_TO_LOAD = re.compile(r'libraryToLoad\d*\s*=\s*"((?:[^"\\]|\\.)*)"')


def catalogs_from_prefs(prefs_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Return catalogs Lightroom has been told to open, newest key first.

    Reads ``*Preferences.agprefs`` (a Lua-ish text file) and pulls every
    ``libraryToLoad`` entry. ``libraryToLoad20`` is the most recent on modern
    versions but the suffix is not stable, so all are returned with the key
    name attached.
    """
    dirs = [prefs_dir] if prefs_dir else default_prefs_dirs()
    out: List[Dict[str, Any]] = []
    for d in dirs:
        if not d or not d.exists():
            continue
        for prefs in sorted(d.glob("*Preferences.agprefs")):
            try:
                text = prefs.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in _LIBRARY_TO_LOAD.finditer(text):
                raw = m.group(1).replace("\\\\", "\\")
                p = Path(raw)
                out.append(
                    {
                        "key": m.group(0).split("=")[0].strip(),
                        "path": str(p),
                        "exists": p.exists(),
                        "prefs_file": str(prefs),
                    }
                )
    return out


def scan_for_catalogs(roots: Sequence[Path], max_depth: int = 3) -> List[Dict[str, Any]]:
    """Walk a few levels looking for ``*.lrcat`` files with their size."""
    found: List[Dict[str, Any]] = []
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            if len(Path(dirpath).parts) - base_depth >= max_depth:
                dirnames[:] = []
            for fn in filenames:
                if fn.lower().endswith(".lrcat"):
                    p = Path(dirpath) / fn
                    try:
                        size = p.stat().st_size
                    except OSError:
                        size = -1
                    found.append({"path": str(p), "size_bytes": size})
    return sorted(found, key=lambda x: -x["size_bytes"])


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a catalog read-only. Safe while Lightroom has it open."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"catalog not found: {p}")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=1")
    conn.row_factory = sqlite3.Row
    return conn


# --------------------------------------------------------------------------
# health / counting
# --------------------------------------------------------------------------

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def health(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Table counts plus an explicit empty-shell verdict.

    Lightroom creates a valid-looking but photo-less catalog more often than
    people expect; mistaking it for the real catalog produces the confident and
    wrong conclusion "the library is empty".
    """
    counts: Dict[str, int] = {}
    for t in _COUNT_TABLES:
        if _table_exists(conn, t):
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    images = counts.get("Adobe_images", 0)
    if not counts:
        verdict = "not a Lightroom catalog (no known tables)"
    elif images == 0:
        verdict = "EMPTY SHELL - no images; almost certainly not the active catalog"
    elif images < 100:
        verdict = f"suspiciously small ({images} images) - double-check this is the active catalog"
    else:
        verdict = f"looks real ({images} images)"
    return {"counts": counts, "images": images, "verdict": verdict}


def photo_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM Adobe_images").fetchone()[0]


# --------------------------------------------------------------------------
# photo paths and stem lookup
# --------------------------------------------------------------------------

# Joins the four tables that together describe a file on disk.
_PHOTO_SQL = """
SELECT img.id            AS image_id,
       f.baseName        AS stem,
       f.extension       AS ext,
       rf.absolutePath   AS root_path,
       fo.pathFromRoot   AS folder_path,
       img.captureTime   AS capture_time,
       img.rating        AS rating,
       img.pick          AS pick
FROM Adobe_images img
JOIN AgLibraryFile   f  ON f.id  = img.rootFile
JOIN AgLibraryFolder fo ON fo.id = f.folder
JOIN AgLibraryRootFolder rf ON rf.id = fo.rootFolder
"""


# Same join plus the develop-settings blob. Built by appending AFTER the FROM
# clause: a LEFT JOIN placed before it (easy to do with a naive string replace)
# is a syntax error, which is worth stating because the failure looks like a
# fixture problem rather than a SQL problem.
_PHOTO_SQL_WITH_SETTINGS = _PHOTO_SQL.replace(
    "FROM Adobe_images img",
    "FROM Adobe_images img\nLEFT JOIN Adobe_imageDevelopSettings ds ON ds.image = img.id",
).replace(
    "img.pick          AS pick",
    "img.pick          AS pick,\n       ds.text           AS settings_text",
)


def photo_paths_sql() -> str:
    """Expose the join so callers can build their own queries."""
    return _PHOTO_SQL


def _join_path(root_path: Optional[str], folder_path: Optional[str], stem: str, ext: Optional[str]) -> str:
    root = (root_path or "").strip()
    folder = (folder_path or "").strip().strip("/\\")
    name = stem + ("." + ext if ext else "")
    parts = [p for p in [root.rstrip("/\\"), folder.replace("\\", "/"), name] if p]
    sep = "\\" if re.match(r"^[A-Za-z]:", root) or "\\" in root else "/"
    if sep == "\\":
        return "\\".join(x.replace("/", "\\") for x in parts)
    return "/".join(parts)


def find_by_stem(
    conn: sqlite3.Connection,
    stems: Iterable[str],
    session_hint: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Locate photos by filename stem, reporting every copy.

    ``session_hint`` is a substring of the folder path (for example a shoot
    folder name). Prefer it over date filtering: derived JPEGs often carry a
    different capture date than the RAW sitting next to them, so a date window
    silently drops the photos you asked for.
    """
    stems = [s.strip() for s in stems if s and s.strip()]
    if not stems:
        return {"requested": 0, "found": {}, "missing": [], "collisions": []}

    matches: Dict[str, List[Dict[str, Any]]] = {}
    for stem in stems:
        rows = conn.execute(_PHOTO_SQL + " WHERE f.baseName = ?", (stem,)).fetchall()
        entries = []
        for r in rows:
            path = _join_path(r["root_path"], r["folder_path"], r["stem"], r["ext"])
            entries.append(
                {
                    "image_id": r["image_id"],
                    "path": path,
                    "capture_time": r["capture_time"],
                    "rating": r["rating"],
                    "pick": r["pick"],
                    "folder": (r["folder_path"] or "").replace("\\", "/"),
                }
            )
        if session_hint:
            entries = [e for e in entries if session_hint.lower() in e["path"].lower()]
        if date_from:
            entries = [e for e in entries if (e["capture_time"] or "")[:10] >= date_from]
        if date_to:
            entries = [e for e in entries if (e["capture_time"] or "")[:10] <= date_to]
        if entries:
            matches[stem] = entries

    return {
        "requested": len(stems),
        "found": matches,
        "missing": [s for s in stems if s not in matches],
        "collisions": [s for s, v in matches.items() if len(v) > 1],
    }


# --------------------------------------------------------------------------
# Lua table parser (develop settings live here)
# --------------------------------------------------------------------------

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'"}


def _strip_assignment(text: str) -> str:
    """Drop a leading ``s =`` / ``return`` wrapper if present."""
    t = text.strip()
    m = re.match(r"^(?:return\s+)?(?:[A-Za-z_]\w*\s*=\s*)?", t)
    if m and m.end() and t[m.end():].lstrip().startswith("{"):
        return t[m.end():].lstrip()
    return t


def parse_lua_table(text: str) -> Dict[str, Any]:
    """Parse a Lightroom develop-settings Lua table into a dict.

    Handles nested tables, arrays, quoted strings with escapes, numbers
    (including scientific notation), booleans and ``nil``. Anything it does not
    understand raises ``ValueError`` rather than silently returning a partial
    dict, because a half-parsed develop profile is worse than none.
    """
    if text is None:
        raise ValueError("empty develop settings")
    s = _strip_assignment(text)
    pos = 0
    n = len(s)

    def skip_ws(i: int) -> int:
        while i < n and s[i] in " \t\r\n,":
            i += 1
        return i

    def parse_value(i: int) -> tuple[Any, int]:
        i = skip_ws(i)
        if i >= n:
            raise ValueError("unexpected end of input")
        ch = s[i]
        if ch == "{":
            return parse_table(i)
        if ch in "\"'":
            quote = ch
            i += 1
            buf = []
            while i < n:
                c = s[i]
                if c == "\\" and i + 1 < n:
                    nxt = s[i + 1]
                    buf.append(_ESCAPES.get(nxt, nxt))
                    i += 2
                    continue
                if c == quote:
                    return "".join(buf), i + 1
                buf.append(c)
                i += 1
            raise ValueError("unterminated string")
        if s.startswith("true", i):
            return True, i + 4
        if s.startswith("false", i):
            return False, i + 5
        if s.startswith("nil", i):
            return None, i + 3
        m = _NUM.match(s, i)
        if m:
            raw = m.group(0)
            val = float(raw) if ("." in raw or "e" in raw.lower()) else int(raw)
            return val, m.end()
        m = _IDENT.match(s, i)
        if m:
            # bare identifier as a value: keep it as a string, do not invent a symbol
            return m.group(0), m.end()
        raise ValueError(f"cannot parse value at offset {i}: {s[i:i+30]!r}")

    def parse_table(i: int) -> tuple[Dict[str, Any], int]:
        assert s[i] == "{"
        i += 1
        out: Dict[str, Any] = {}
        array_index = 1
        while True:
            i = skip_ws(i)
            if i >= n:
                raise ValueError("unterminated table")
            if s[i] == "}":
                return out, i + 1
            # key?
            if s[i] == "[":
                j = s.index("]", i)
                key_raw = s[i + 1:j].strip()
                if key_raw[:1] in ("'", '"'):
                    key_raw = key_raw.strip("'\"")
                key = int(key_raw) if key_raw.lstrip("-").isdigit() else key_raw
                i = skip_ws(j + 1)
                if i < n and s[i] == "=":
                    val, i = parse_value(i + 1)
                    out[key] = val
                    continue
                raise ValueError(f"expected '=' after [{key_raw}]")
            m = _IDENT.match(s, i)
            if m:
                save = i
                ident = m.group(0)
                j = skip_ws(m.end())
                if j < n and s[j] == "=":
                    val, i = parse_value(j + 1)
                    out[ident] = val
                    continue
                i = save
            # positional value
            val, i = parse_value(i)
            out[array_index] = val
            array_index += 1

    value, _ = parse_value(0)
    if not isinstance(value, dict):
        raise ValueError("develop settings did not parse to a table")
    return value


def develop_settings(conn: sqlite3.Connection, image_id: int) -> Optional[Dict[str, Any]]:
    """Parsed develop sliders for one image, or None when the row is absent."""
    row = conn.execute(
        "SELECT text FROM Adobe_imageDevelopSettings WHERE image = ?", (image_id,)
    ).fetchone()
    if row is None or not row["text"]:
        return None
    return parse_lua_table(row["text"])


def edit_step_count(conn: sqlite3.Connection, image_id: int) -> int:
    """How many develop-history steps an image has.

    This, not the existence of a settings row, is what tells you whether a
    photo was actually edited: Lightroom writes a settings row for every image,
    including untouched ones.
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM Adobe_libraryImageDevelopHistoryStep WHERE image = ?",
        (image_id,),
    ).fetchone()
    return row[0] if row else 0


# --------------------------------------------------------------------------
# bulk export + style report
# --------------------------------------------------------------------------

def export_develop(
    conn: sqlite3.Connection,
    out_path: str | Path,
    rating_min: Optional[int] = None,
    gz: bool = True,
) -> Dict[str, Any]:
    """Stream every image's develop settings to JSONL(.gz).

    Exporting all of it (rather than sampling) is deliberate: edits are applied
    in batches, and sampling breaks the batches apart so the very pattern you
    are looking for disappears.
    """
    out_path = Path(out_path)
    sql = _PHOTO_SQL_WITH_SETTINGS
    if rating_min is not None:
        sql += " WHERE img.rating >= ?"
    rows = conn.execute(sql, (rating_min,) if rating_min is not None else ())

    opener = gzip.open if gz else open
    written = 0
    unparsed = 0
    kwargs = {"encoding": "utf-8"} if not gz else {}
    with opener(out_path, "wt", **kwargs) as fh:
        for r in rows or []:
            rec: Dict[str, Any] = {
                "image_id": r["image_id"],
                "stem": r["stem"],
                "path": _join_path(r["root_path"], r["folder_path"], r["stem"], r["ext"]),
                "capture_time": r["capture_time"],
                "rating": r["rating"],
                "pick": r["pick"],
            }
            text = r["settings_text"]
            if text:
                try:
                    rec["settings"] = parse_lua_table(text)
                except ValueError:
                    unparsed += 1
                    rec["settings"] = None
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
    return {"written": written, "unparsed": unparsed, "path": str(out_path)}


def _median(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _stdev(vals: List[float]) -> Optional[float]:
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    return var ** 0.5


def style_report(
    conn: sqlite3.Connection,
    keys: Optional[Sequence[str]] = None,
    rating_min: Optional[int] = None,
) -> Dict[str, Any]:
    """Summarise how consistently this photographer edits.

    Answers "could this habit be learned or automated" with distributions
    instead of an opinion:

    * per-slider non-zero share and median - the photographer's ruler
    * edits per image - concentrated on a few sliders means learnable
    * white-balance cardinality per day - one value means applied in bulk
    * exposure stdev per shoot day - your own spread is the honest ceiling for
      any "reproduce exactly" promise
    """
    keys = list(keys or DEFAULT_DEVELOP_KEYS)
    sql = _PHOTO_SQL_WITH_SETTINGS
    if rating_min is not None:
        sql += " WHERE img.rating >= ?"

    per_key_nonzero = {k: 0 for k in keys}
    per_key_values: Dict[str, List[float]] = {k: [] for k in keys}
    params_per_image: List[int] = []
    day_exposure: Dict[str, List[float]] = {}
    day_temps: Dict[str, set] = {}
    total = 0
    parsed = 0

    for r in conn.execute(sql, (rating_min,) if rating_min is not None else ()):
        total += 1
        text = r["settings_text"]
        if not text:
            continue
        try:
            s = parse_lua_table(text)
        except ValueError:
            continue
        parsed += 1
        touched = 0
        for k in keys:
            v = s.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                per_key_values[k].append(float(v))
                if abs(float(v)) > 1e-9:
                    per_key_nonzero[k] += 1
                    touched += 1
        params_per_image.append(touched)
        day = (r["capture_time"] or "")[:10]
        if day:
            exp = s.get("Exposure2012")
            if isinstance(exp, (int, float)) and not isinstance(exp, bool):
                day_exposure.setdefault(day, []).append(float(exp))
            temp = s.get("Temperature")
            if isinstance(temp, (int, float)) and not isinstance(temp, bool):
                day_temps.setdefault(day, set()).add(round(float(temp)))

    sliders = {}
    for k in keys:
        vals = per_key_values[k]
        sliders[k] = {
            "present": len(vals),
            "nonzero": per_key_nonzero[k],
            "nonzero_pct": round(100.0 * per_key_nonzero[k] / parsed, 1) if parsed else None,
            "median": round(_median(vals), 3) if vals else None,
        }

    exposure_spread = {
        day: {"n": len(v), "median": round(_median(v), 2), "stdev": round(_stdev(v), 2) if _stdev(v) is not None else None}
        for day, v in sorted(day_exposure.items())
        if len(v) >= 3
    }
    wb_per_day = {day: len(v) for day, v in sorted(day_temps.items()) if v}

    concentrated = sorted(sliders.items(), key=lambda kv: -kv[1]["nonzero"])
    top = [k for k, v in concentrated if v["nonzero_pct"] and v["nonzero_pct"] >= 50]

    return {
        "images_total": total,
        "images_with_settings": parsed,
        "sliders": sliders,
        "params_touched_per_image": {
            "median": _median([float(x) for x in params_per_image]),
            "p90": sorted(params_per_image)[int(0.9 * (len(params_per_image) - 1))] if params_per_image else None,
        },
        "top_sliders": top,
        "exposure_stdev_by_day": exposure_spread,
        "distinct_temperature_by_day": wb_per_day,
        "reading": (
            "editing is concentrated on a few sliders - a rule/parameter model is plausible"
            if len(top) <= 6
            else "editing spreads across many sliders - learning it would need per-photo judgement"
        ),
    }
