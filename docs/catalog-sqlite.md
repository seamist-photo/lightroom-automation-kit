# Reading a .lrcat directly

A Lightroom Classic catalog is a SQLite database. You do not need Lightroom, an
API, or an SDK to answer "what is in my catalog" - and you should not *write*
to it, because Lightroom has it open with a WAL journal.

```python
import sqlite3
conn = sqlite3.connect("file:/path/to/Catalog.lrcat?mode=ro", uri=True)
conn.execute("PRAGMA query_only=1")
```

Read-only connections work while Lightroom is running. Never open it read-write.

## Finding the active catalog

Lightroom stores the catalogs it has opened in
`*Preferences.agprefs`, under keys like `libraryToLoad20` (the numeric suffix
is not stable across versions). On Windows:

```
%APPDATA%\Adobe\Lightroom\Lightroom Classic 13 Preferences.agprefs
```

`lrc-kit catalog find` parses those entries and reports `exists` for each, which
also surfaces stale paths from old machines.

## The four-table path join

A photo's file path is assembled from four tables:

| table | column | meaning |
|---|---|---|
| `AgLibraryRootFolder` | `absolutePath` | volume root, e.g. `E:\` |
| `AgLibraryFolder` | `pathFromRoot` | path inside the root, forward slashes |
| `AgLibraryFile` | `baseName`, `extension` | **stem without extension**, and the extension |
| `Adobe_images` | `rootFile` | FK to `AgLibraryFile.id` |

```sql
SELECT f.baseName, f.extension, rf.absolutePath, fo.pathFromRoot
FROM Adobe_images img
JOIN AgLibraryFile       f  ON f.id  = img.rootFile
JOIN AgLibraryFolder     fo ON fo.id = f.folder
JOIN AgLibraryRootFolder rf ON rf.id = fo.rootFolder;
```

Gotchas:

- `baseName` has **no extension**. Matching a filename means comparing stems and
  keeping the extension separately.
- `pathFromRoot` uses forward slashes even on Windows; `absolutePath` may use
  backslashes. Normalise before joining or you get `E:\\2026//0907//file.NEF`.
- Capture time lives on `Adobe_images.captureTime`, not on the file table.

## Empty-shell catalogs

Lightroom creates valid catalogs with zero images, and users accumulate them:
a fresh catalog is around **2 MB**, a real one with a few thousand photos is
in the hundreds of MB. Point a script at the wrong one and it confidently
reports "the library is empty".

Always check the size and the row counts before drawing conclusions:

```python
health(conn)
# {'images': 0, 'verdict': 'EMPTY SHELL - no images; almost certainly not the active catalog'}
```

`AgLibraryCollection` may exist in a shell, so collections are not evidence of a
real catalog either.

## Filename collisions are normal

`_MIS7102.NEF` can exist in two different shoot folders months apart -
sequential in-camera numbering restarts. A stem lookup that assumes uniqueness
silently returns the wrong photo.

Two rules:

1. Return **every** copy with its full path and capture time, and flag stems
   with more than one match.
2. Disambiguate with a **folder substring** (shoot folder name), not with a date
   window. Derived JPEGs and the RAW they came from frequently carry different
   capture times, so a date filter drops photos it should have kept.

```python
find_by_stem(conn, ["_MIS7102"], session_hint="0907")
# collisions: [] because the folder hint narrowed it to one session
```

## Develop settings: text, not JSON

`Adobe_imageDevelopSettings.text` is a **Lua table serialised as text**:

```
s = { Exposure2012 = 0.45, Highlights2012 = -32, ToneCurvePV2012 = { 0, 0, 255, 255 }, CameraProfile = "Adobe Standard" }
```

`lrc-kit catalog develop` parses it (`catalog.parse_lua_table`). Do not use
`json.loads`, and do not regex a single slider out of it - tone curves and
nested tables will bite you.

**A settings row does not mean the photo was edited.** Lightroom writes a row
for every image, including untouched ones. Edit history is the honest signal:

```python
edit_step_count(conn, image_id)   # Adobe_libraryImageDevelopHistoryStep rows
```

That distinction is what separates "this photo has settings" from "this photo
was edited 3 times", and it changes any batch analysis you build on top.

## Performance

A full scan of ~9,400 images (four-table join plus settings parse) completes in
under 20 seconds on an ordinary desktop. No index tuning needed. Export the whole
catalog rather than sampling - edits are applied in batches, and sampling breaks
the batches apart, which is exactly the pattern you are looking for.
