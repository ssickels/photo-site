"""Old addresses -> new pages, from content/redirects.tsv, as Apache rewrite rules.

Each line: an old key, a target, and an optional note, separated by tabs.
  key     an id from the old site's addresses (matched as a whole path segment
          anywhere in the address, e.g. PhotoShelter's I0000.../G0000.../C0000...),
          or an exact old path starting with "/"
  target  photo:<file name stem> | theme:<slug> | location:<gallery slug or name>
          | a path on the new site ("/", "/prints/")
Targets name photos and galleries rather than URLs, so redirects follow a
photo when it moves to another theme. A target that no longer exists falls
back to the home page, with a warning.
"""
from __future__ import annotations

import re
from pathlib import Path

# Old PhotoShelter sections: anything under these that the list doesn't
# cover still goes somewhere sensible instead of a 404.
OLD_SECTIONS = ("image", "gallery", "gallery-image", "gallery-collection", "portfolio")
ID_KIND_ORDER = {"I": 0, "G": 1, "C": 2}     # most specific first: an image address contains its gallery


def load(path: Path) -> list[tuple[str, str, int]]:
    """(key, target, line number) for each entry."""
    if not path.is_file():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            parts = line.split(None, 2)           # tolerate spaces instead of tabs
        if len(parts) < 2:
            raise ValueError(f"{path.name} line {n}: needs an old address and a target")
        out.append((parts[0], parts[1], n))
    return out


def rules(entries, resolve, base: str, where: str, warnings: list) -> list[str]:
    """Apache lines (inside an already-open <IfModule mod_rewrite.c> with
    RewriteEngine On). `resolve(target)` returns a site path or None."""
    if not entries:
        return []
    ids, paths = [], []
    for key, target, n in entries:
        url = resolve(target)
        if url is None:
            warnings.append(f"{where} line {n}: {target!r} isn't on the site; {key} goes to the home page")
            url = "/"
        (paths if key.startswith("/") else ids).append((key, url))
    ids.sort(key=lambda kv: ID_KIND_ORDER.get(kv[0][:1], 3))

    body = [f"  RewriteRule (^|/){re.escape(k)}(/|$) {base}{u} [R=301,L,QSD]" for k, u in ids]
    body += [f"  RewriteRule ^{re.escape(k.strip('/'))}/?$ {base}{u} [R=301,L,QSD]" for k, u in paths]
    body.append(f"  RewriteRule ^({'|'.join(OLD_SECTIONS)})(/|$) {base}/ [R=301,L,QSD]")

    first = sorted({*OLD_SECTIONS, *(k.strip("/").split("/")[0] for k, _ in paths)})
    alts = "|".join(re.escape(s) for s in first)
    return [
        f"  # Old addresses ({where}). Requests outside these sections skip the list.",
        f"  RewriteCond %{{REQUEST_URI}} !^/({alts})(/|$)",
        f"  RewriteRule ^ - [S={len(body)}]",
        *body,
        "",
    ]
