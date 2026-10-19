"""Command line entry point: ``lrc-kit <group> <command> ...``

Every command prints JSON unless ``--pretty`` is given, so the output can be
piped into an agent, a diff, or another script without scraping prose.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, catalog, color_eval, preflight


def _emit(payload, pretty: bool) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None))


def _csv(value: str):
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lrc-kit", description="Practical tooling for Lightroom Classic automation.")
    p.add_argument("--version", action="version", version=f"lrc-kit {__version__}")
    sub = p.add_subparsers(dest="group", required=True)

    # ---- catalog ----
    cat = sub.add_parser("catalog", help="read a .lrcat without opening Lightroom")
    cat_sub = cat.add_subparsers(dest="cmd", required=True)

    find = cat_sub.add_parser("find", help="locate catalogs from preferences")
    find.add_argument("--fake-prefs-dir", help="point at a directory holding *Preferences.agprefs (for tests)")
    find.add_argument("--scan", nargs="*", help="extra roots to scan for *.lrcat")
    find.add_argument("--pretty", action="store_true")

    health = cat_sub.add_parser("health", help="table counts and empty-shell verdict")
    health.add_argument("catalog")
    health.add_argument("--pretty", action="store_true")

    photos = cat_sub.add_parser("find-photos", help="locate photos by filename stem, reporting every copy")
    photos.add_argument("catalog")
    photos.add_argument("--stems", required=True, help="comma separated filename stems (no extension)")
    photos.add_argument("--session", help="substring of the folder path, e.g. a shoot folder name")
    photos.add_argument("--from", dest="date_from", help="YYYY-MM-DD (prefer --session instead)")
    photos.add_argument("--to", dest="date_to", help="YYYY-MM-DD")
    photos.add_argument("--pretty", action="store_true")

    style = cat_sub.add_parser("style", help="summarise this photographer's editing consistency")
    style.add_argument("catalog")
    style.add_argument("--rating-min", type=int)
    style.add_argument("--pretty", action="store_true")

    export = cat_sub.add_parser("export", help="stream every image's develop settings to JSONL(.gz)")
    export.add_argument("catalog")
    export.add_argument("--out", required=True)
    export.add_argument("--rating-min", type=int)
    export.add_argument("--no-gz", action="store_true")
    export.add_argument("--pretty", action="store_true")

    develop = cat_sub.add_parser("develop", help="parsed develop settings for one image id")
    develop.add_argument("catalog")
    develop.add_argument("--image-id", type=int, required=True)
    develop.add_argument("--pretty", action="store_true")

    # ---- preflight ----
    pre = sub.add_parser("preflight", help="check Lua plugin code without restarting Lightroom")
    pre_sub = pre.add_subparsers(dest="cmd", required=True)

    syn = pre_sub.add_parser("syntax", help="compile-check .lua files (uses Lua 5.1 when available)")
    syn.add_argument("files", nargs="+")
    syn.add_argument("--pretty", action="store_true")

    lt = pre_sub.add_parser("test", help="run a test snippet in the same chunk as the target file")
    lt.add_argument("target")
    lt.add_argument("test")
    lt.add_argument("--data", help="JSON file; %%(json)s in the snippet is replaced with its contents")
    lt.add_argument("--pretty", action="store_true")

    # ---- color ----
    col = sub.add_parser("color", help="numeric colour verification")
    col_sub = col.add_subparsers(dest="cmd", required=True)

    ev = col_sub.add_parser("eval", help="compare a result render against a target reference")
    ev.add_argument("result")
    ev.add_argument("target")
    ev.add_argument("--pretty", action="store_true")

    me = col_sub.add_parser("measure", help="Lab statistics of one image, as slider hints")
    me.add_argument("image")
    me.add_argument("--pretty", action="store_true")

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.group == "catalog":
            if args.cmd == "find":
                prefs = Path(args.fake_prefs_dir) if args.fake_prefs_dir else None
                payload = {"from_prefs": catalog.catalogs_from_prefs(prefs)}
                if args.scan:
                    payload["scanned"] = catalog.scan_for_catalogs([Path(p) for p in args.scan])
                _emit(payload, args.pretty)
                return 0

            conn = catalog.connect(args.catalog)
            try:
                if args.cmd == "health":
                    _emit(catalog.health(conn), args.pretty)
                elif args.cmd == "find-photos":
                    _emit(
                        catalog.find_by_stem(
                            conn, _csv(args.stems), args.session, args.date_from, args.date_to
                        ),
                        args.pretty,
                    )
                elif args.cmd == "style":
                    _emit(catalog.style_report(conn, rating_min=args.rating_min), args.pretty)
                elif args.cmd == "export":
                    _emit(catalog.export_develop(conn, args.out, args.rating_min, gz=not args.no_gz), args.pretty)
                elif args.cmd == "develop":
                    _emit(
                        {
                            "image_id": args.image_id,
                            "settings": catalog.develop_settings(conn, args.image_id),
                            "edit_steps": catalog.edit_step_count(conn, args.image_id),
                        },
                        args.pretty,
                    )
                else:  # pragma: no cover - argparse guards this
                    raise SystemExit(f"unknown catalog command {args.cmd}")
            finally:
                conn.close()
            return 0

        if args.group == "preflight":
            if args.cmd == "syntax":
                res = preflight.syntax_check(args.files)
            else:
                res = preflight.logic_test(args.target, args.test, args.data)
            _emit(res.to_dict(), args.pretty)
            return 0 if res.ok else 1

        if args.group == "color":
            if args.cmd == "eval":
                _emit(color_eval.evaluate(args.result, args.target), args.pretty)
            else:
                _emit(color_eval.measure(args.image), args.pretty)
            return 0

    except preflight.LuaUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
