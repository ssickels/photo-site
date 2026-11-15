#!/usr/bin/env python3
"""Build the photo site from the Lightroom publish folder.

    ./build.py                       build dist/production
    ./build.py --target staging      build dist/staging (noindex)
    ./build.py locations             print the place-keyword tree with counts
    ./build.py sizes                 derivative file sizes per width and format
    ./build.py --deploy staging      build + deploy            (Phase 4)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Re-run under the project's .venv if started with another Python.
_VENV = ROOT / ".venv"
if (_VENV / "bin" / "python").exists() and Path(sys.prefix).resolve() != _VENV.resolve():
    import os
    os.execv(str(_VENV / "bin" / "python"), [str(_VENV / "bin" / "python"), __file__, *sys.argv[1:]])

from photosite.config import ConfigError, load_config  # noqa: E402
from photosite.images import size_report  # noqa: E402
from photosite.model import format_tree  # noqa: E402
from photosite.pipeline import build, load_catalog  # noqa: E402

TARGETS = ("staging", "production")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="build", choices=["build", "locations", "sizes"])
    ap.add_argument("--config", default=str(ROOT / "site.yaml"))
    ap.add_argument("--publish", help="publish folder (overrides site.yaml)")
    ap.add_argument("--out", help="output folder (overrides site.yaml)")
    ap.add_argument("--cache", help="cache folder (overrides site.yaml)")
    ap.add_argument("--target", choices=TARGETS, default="production")
    ap.add_argument("--deploy", choices=TARGETS, help="build that target, then deploy it")
    ap.add_argument("--dry-run", action="store_true", help="with --deploy: show what would change")
    ap.add_argument("--workers", type=int, help="parallel image workers (default: CPU count)")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    try:
        config = load_config(args.config, publish=args.publish, output=args.out, cache=args.cache)
        if args.command == "locations":
            catalog, _, scan_warnings = load_catalog(config)
            print(format_tree(catalog, config))
            for w in scan_warnings + catalog.warnings:
                print(f"warning: {w}", file=sys.stderr)
            return 0
        if args.command == "sizes":
            print(size_report(config.cache_dir))
            return 0

        target = args.deploy or args.target
        t0 = time.perf_counter()

        def progress(i, n, pid):
            if not args.quiet and sys.stdout.isatty():
                print(f"\r  images {i}/{n}  {pid:<40}", end="", flush=True)

        res = build(config, target, args.workers, progress)
        if res.images.rendered and not args.quiet and sys.stdout.isatty():
            print()
        total = time.perf_counter() - t0
    except (ConfigError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    cat, img = res.catalog, res.images
    for msg in res.scan_warnings + cat.warnings + img.warnings:
        print(f"warning: {msg}")
    if not args.quiet:
        for msg in cat.info:
            print(f"info: {msg}")
        themes = ", ".join(f"{t.name} {len(t.photos)}" for t in cat.themes)
        print(f"{len(cat.photos)} photos  |  themes: {themes}  |  "
              f"{len(cat.galleries)} location galleries")
        print(f"images: {len(img.rendered)} rendered, {img.reused} reused, "
              f"{img.removed_files} stale files removed")
        print("time: " + "  ".join(f"{k} {v:.2f}s" for k, v in res.timings.items())
              + f"  | total {total:.2f}s  (exiftool read {res.exiftool_reads} files)")
        print(f"output: {(config.output_dir / target).resolve()}  ({res.pages} pages)")

    if args.deploy:
        print("deploy: not implemented yet (Phase 4)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
