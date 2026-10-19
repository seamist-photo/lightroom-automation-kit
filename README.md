# lrc-kit

Practical tooling for automating Adobe Lightroom Classic. Three small pieces,
each solving a problem that otherwise costs a full Lightroom restart, a manual
click, or a judgement call about colour.

```bash
pip install lrc-kit              # core: zero dependencies
pip install "lrc-kit[color]"     # adds numpy + pillow (colour verification)
pip install "lrc-kit[preflight]" # adds lupa (running Lua logic tests)
```

- **`preflight`** - compile-check plugin Lua with a real **Lua 5.1** compiler before
  making anyone restart Lightroom. Catches the errors, and the false errors, that
  cost hours.
- **`catalog`** - read a `.lrcat` directly (it is SQLite) without opening
  Lightroom: paths, ratings, develop settings, edit-history counts, and a
  consistency report on how a photographer actually edits.
- **`color`** - verify a colour match numerically (CIEDE2000, histogram EMD, per-zone
  Lab deltas) instead of squinting at two images.

Nothing here writes to a catalog. Nothing here needs Lightroom to be closed.

## Why these three

**The Lua problem.** A plugin error inside Lightroom is a modal dialog, and
retrying means a human clicking again. Worse, checking with the lupa Python
binding gives you Lua 5.4/5.5 semantics while Lightroom runs **5.1** - so legal
code fails with `attempt to assign to const variable` and you go hunting for a
logic bug that does not exist. `lrc-kit preflight syntax` uses `luac5.1 -p` when
it exists, because the fastest way to be right about Lua 5.1 is to use Lua 5.1.

```console
$ lrc-kit preflight syntax MyPlugin.lua
{"ok": true, "items": [{"file": "MyPlugin.lua", "status": "ok", "detail": ""}],
 "notes": ["checked with Lua 5.1.5  Copyright (C) 1994-2012 Lua.org, PUC-Rio"]}
```

**The catalog problem.** "The library is empty" is almost always the wrong
catalog: Lightroom leaves 2 MB shells around next to a real 300 MB catalog. And
`_MIS7102.NEF` existing in two different shoot folders is normal, not a bug.
Both are checked explicitly:

```console
$ lrc-kit catalog health /path/to/Catalog.lrcat --pretty
{
  "counts": {"Adobe_images": 5, "AgLibraryFile": 5, ...},
  "images": 5,
  "verdict": "suspiciously small (5 images) - double-check this is the active catalog"
}
```

**The colour problem.** Two renders can look "close" while being 6 dE apart in
the highlights. `color eval` returns distributions, not adjectives:

```console
$ lrc-kit color eval result.jpg reference.jpg --pretty
{"dE2000": {"mean": 1.83, "p90": 4.2, "pct_lt2": 71.4, ...},
 "verdict": "EXCELLENT (<2 dE: imperceptible)",
 "hist_emd": {"L": 0.91, "a": 0.34, "b": 0.52},
 "zone_delta_target_minus_result": {"shadow": {"dL": -1.2, "da": 0.4, ...}}}
```

CIEDE2000 is implemented from the CIE specification and verified against the
published Sharma et al. reference pairs in the test suite - not against its own
output.

## Documentation

The code is the small part. The expensive part is knowing why it has to look
that way:

| page | what it saves you |
|---|---|
| [plugin-loading-and-execution-contexts](docs/plugin-loading-and-execution-contexts.md) | Why your plugin "is running" but its `Init.lua` never executed, and the three execution contexts that each have different rules for yielding and write locks |
| [catalog-sqlite](docs/catalog-sqlite.md) | The four-table path join, empty-shell detection, filename collisions, and why a develop-settings row does not mean a photo was edited |
| [xmp-and-profiles](docs/xmp-and-profiles.md) | Three unrelated things called "XMP", and why a delivered preset dropped next to the photos does nothing |
| [raw-decoding](docs/raw-decoding.md) | Why proprietary compressed RAW (e.g. Nikon HE-NEF) cannot be decoded by the open stack at all - a codec gap, not a quality difference |
| [prior-art](docs/prior-art.md) | What else exists, measured rather than remembered, and when to use it instead of writing anything |

`examples/minimal-bridge/` is a working four-file plugin skeleton that
demonstrates the load-bearing patterns: eager-load flags, auto-start from an
init script, a write path that takes the catalog lock, and a status panel that
never kills a running server.

## Design rules

These are not style preferences; each one came from a wrong answer we shipped
first.

1. **A number or an exit code, never a narrative.** Every check returns JSON or a
   non-zero status.
2. **Never write to the catalog.** Read-only connections only. Settings go
   through the plugin API or through `.xmp` sidecars.
3. **Do not sample.** Edits are applied in batches; sampling destroys the pattern
   you are analysing.
4. **Prefer the real runtime.** Lua 5.1 compiler over a newer embedded
   interpreter; real file fixtures over mocks of the database schema.
5. **State the provenance.** Findings that need proprietary data to reproduce
   are marked as such in their page rather than presented as CI-verified.

## Platform support

Tested on Windows 11 and Linux. The catalog and preflight code is
platform-independent (`sqlite3`, `luac`); macOS paths for preferences are
implemented but less exercised. Lightroom Classic itself is Windows/macOS only.

## Status

Early but honest: 38 tests, `python -m unittest discover`, no network, no
proprietary fixtures, colour math verified against published reference data.

## License

MIT. See [LICENSE](LICENSE).
