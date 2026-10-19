"""Build a tiny but structurally faithful .lrcat for tests.

The point is not to imitate every column Lightroom writes, only the four-table
join that resolves a photo to a path, plus the two tables that hold develop
settings and edit history. Anything tested against this fixture is therefore
testing the same queries that run against a real catalog.

Includes a deliberate filename collision: ``_MIS7102`` exists in two different
shoot folders, which is the case that silently breaks naive stem matching.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE AgLibraryRootFolder (id INTEGER PRIMARY KEY, absolutePath TEXT, name TEXT);
CREATE TABLE AgLibraryFolder (id INTEGER PRIMARY KEY, pathFromRoot TEXT, rootFolder INTEGER);
CREATE TABLE AgLibraryFile (id INTEGER PRIMARY KEY, baseName TEXT, extension TEXT, folder INTEGER);
CREATE TABLE Adobe_images (id INTEGER PRIMARY KEY, rootFile INTEGER, captureTime TEXT, rating INTEGER, pick INTEGER);
CREATE TABLE Adobe_imageDevelopSettings (image INTEGER PRIMARY KEY, text TEXT);
CREATE TABLE Adobe_libraryImageDevelopHistoryStep (id INTEGER PRIMARY KEY, image INTEGER, name TEXT, dateCreated TEXT, valueString TEXT);
CREATE TABLE AgLibraryCollection (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE Adobe_imageDevelopSnapshots (id INTEGER PRIMARY KEY, image INTEGER);
"""

# (file_id, stem, ext, folder_id)
FILES = [
    (1, "_MIS7994", "NEF", 1),
    (2, "_MIS7995", "NEF", 1),
    (3, "_MIS7102", "NEF", 1),
    (4, "_MIS7102", "NEF", 2),
    (5, "_MIS8000", "JPG", 2),
]

SETTINGS = {
    1: 's = { Exposure2012 = 0.45, Highlights2012 = -32, Shadows2012 = 18, Temperature = 5450, Tint = 8, CameraProfile = "Adobe Standard" }',
    2: 's = { Exposure2012 = 0.40, Highlights2012 = -30, Shadows2012 = 20, Temperature = 5450, Tint = 8, Contrast2012 = 12 }',
    4: 'return { Exposure2012 = -0.15, Clarity2012 = 10, ToneCurvePV2012 = { 0, 0, 255, 255 }, Rating = nil }',
}


def build(path: str | Path, empty: bool = False) -> Path:
    """Create the fixture catalog at ``path`` and return it."""
    path = Path(path)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)

    conn.execute("INSERT INTO AgLibraryRootFolder VALUES (1, ?, 'E-drive')", ("E:\\\\",))
    conn.execute("INSERT INTO AgLibraryFolder VALUES (1, '2026/0907-sessionA', 1)")
    conn.execute("INSERT INTO AgLibraryFolder VALUES (2, '2026/0908-sessionB', 1)")

    if not empty:
        conn.executemany("INSERT INTO AgLibraryFile VALUES (?,?,?,?)", FILES)
        conn.executemany(
            "INSERT INTO Adobe_images VALUES (?,?,?,?,?)",
            [
                (1, 1, "2026-09-07T10:15:00", 5, 1),
                (2, 2, "2026-09-07T10:16:00", 3, 1),
                (3, 3, "2026-09-07T10:20:00", 2, 0),
                (4, 4, "2026-09-08T14:02:00", 4, 1),
                (5, 5, "2026-09-08T14:05:00", 1, 0),
            ],
        )
        for image_id, text in SETTINGS.items():
            conn.execute("INSERT INTO Adobe_imageDevelopSettings VALUES (?,?)", (image_id, text))
        # image 1 has been edited three times, image 3 has a settings row but no
        # history (the "row exists" trap), image 2 has neither.
        conn.executemany(
            "INSERT INTO Adobe_libraryImageDevelopHistoryStep VALUES (?,?,?,?,?)",
            [
                (1, 1, "Exposure", "2026-09-07T10:30:00", "+0.45"),
                (2, 1, "Highlights", "2026-09-07T10:31:00", "-32"),
                (3, 1, "Shadows", "2026-09-07T10:32:00", "+18"),
            ],
        )
        conn.execute("INSERT INTO AgLibraryCollection VALUES (1, 'Portfolio')")

    conn.commit()
    conn.close()
    return path


if __name__ == "__main__":  # pragma: no cover
    import sys

    out = build(sys.argv[1] if len(sys.argv) > 1 else "fixture.lrcat")
    print(f"wrote {out}")
