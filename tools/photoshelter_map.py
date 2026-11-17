#!/usr/bin/env python3
"""Write content/redirects.tsv: where each old PhotoShelter address should go.

Inputs (saved while PhotoShelter was still live):
  content/photoshelter/sitemap.xml     PhotoShelter's sitemap: every image id with
                                       its file name, title and caption
  content/photoshelter/blog-links.txt  PhotoShelter addresses found in the blog,
                                       which tie image ids to gallery ids

Images are matched to published photos by file name (PhotoShelter turned
"_MG_1234-Edit" into "MG-1234-Edit"), then by camera number plus title or
caption. An image that isn't on the new site goes to its old gallery's
counterpart, or to a place named in its caption.

Run once; content/redirects.tsv is then the list to edit by hand.
    .venv/bin/python tools/photoshelter_map.py
"""
from __future__ import annotations

import collections
import difflib
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from photosite.config import load_config  # noqa: E402
from photosite.pipeline import load_catalog  # noqa: E402

ID = r"[A-Za-z0-9_.\-]{11}"
THEMES = "C0000wOSyQBHuCBA"
LOCATIONS = "C0000VInEPX_018w"

# PhotoShelter galleries and collections -> new pages
KNOWN = {
    THEMES: ("/themes/", "Portfolio by Theme"),
    LOCATIONS: ("/locations/", "Portfolio by Location"),
    "G00005MNCz1xoRgg": ("theme:black-white", "Black and White"),
    "G0000iYUDB8M6Dug": ("theme:details", "Details"),
    "G0000HnQxoIoDSTw": ("/themes/", "Eclipse (not on the new site)"),
    "G0000jF3mcceoYuo": ("theme:landscapes", "Landscapes and Coastlines"),
    "G0000UJnGqItsJF8": ("theme:landscapes", "Long Exposure"),
    "G0000bMWFjPcjwbU": ("theme:music", "Music"),
    "G0000e3oAPU57keY": ("theme:plants-and-flowers", "Plants and Flowers"),
    "G0000MxBZJ2MiGbE": ("theme:landscapes", "Rivers, Streams, and Waterfalls"),
    "G0000o9cfAm6WuZ4": ("theme:the-built-environment", "The Built Environment"),
    "G0000Oo3cxN0LmTY": ("theme:wildlife", "Wildlife"),
    "G0000om2O9xeh7Us": ("theme:architectural-photography", "Architectural Photography"),
    "G0000egn0fHxs0V4": ("/", "Recent Additions"),
    "G0000Q7.l6PB_r5o": ("location:california", "California"),
    "G0000dP71E4odEPI": ("location:canada", "Canada"),
    "G0000EoEVO7xpJaE": ("location:florida", "Florida"),
    "G0000nGm3XpHQ_98": ("location:iceland", "Iceland"),
    "G0000hhW3uImZ_j0": ("location:italy", "Italy"),
    "G0000Nl_XKfOAOHI": ("location:maine", "Maine"),
    "G0000ibj6psGULdE": ("location:scotland", "Scotland"),
    "G0000J3Ix12l8IAw": ("location:tennessee", "Smoky Mountains"),
    "G0000CJ4.DWWUHFk": ("location:virginia", "Virginia"),
    "G00006BmAwYlT18g": ("location:washington-d-c", "Washington D.C."),
    "G0000TuoOdL7a5Sc": ("location:norway", "Norway (linked from the Amazing Auroras post)"),
    "G0000PJFYcBOQuzE": ("location:scotland", "Scotland (linked from the Scotland posts)"),
}
HINTS = [  # title/caption words -> page, for images that aren't on the new site
    (r"trombone shorty|concert|festival", "theme:music"),
    (r"smok(y|ies)", "location:tennessee"),
    (r"steenbok|elephant|yawn|penguin|weaver|toucan|reindeer|wood duck", "theme:wildlife"),
    (r"eclipse|corona|diamond ring", "/themes/"),
]
PAGES = [  # old page -> new page
    ("/index", "/"), ("/archive", "/"), ("/search-page", "/"), ("/gallery-list", "/themes/"),
    ("/p/print-options", "/prints/"), ("/p/contact", "/contact/"),
]


def full(s: str) -> str:
    s = re.sub(r"\.(jpe?g|png|tiff?)$", "", s, flags=re.I).split("~")[0]
    return re.sub(r"[^a-z0-9]", "", re.sub(r"^\d{8}-", "", s).lower())


def number(s: str) -> str:
    s = re.sub(r"^\d{8}-", "", s.split("~")[0]).lower()
    m = re.search(r"(img|mg|dsc)[-_ ]?(\d{3,5})", s)
    if m:
        return m.group(1) + m.group(2).lstrip("0")
    m = re.search(r"(\d{4,5})", s)
    return m.group(1).lstrip("0") if m else full(s)


def words(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def main() -> int:
    config = load_config(ROOT / "site.yaml")
    catalog, _, _ = load_catalog(config)
    src = config.content_dir / "photoshelter"
    sitemap = (src / "sitemap.xml").read_text(encoding="utf-8")
    links = (src / "blog-links.txt").read_text(encoding="utf-8")

    images = {}
    for m in re.finditer(r"/image/(I0000" + ID + r")</loc><image:image><image:loc>[^<]*/([^/<]+)</image:loc>"
                         r"(?:<image:title>([^<]*)</image:title>)?(?:<image:caption>([^<]*)</image:caption>)?",
                         sitemap):
        images[m.group(1)] = (html.unescape(m.group(2)), html.unescape(m.group(3) or ""),
                              html.unescape(m.group(4) or ""))

    photos = list(catalog.photos.values())
    by_number = collections.defaultdict(list)
    for p in photos:
        by_number[number(p.stem)].append(p)

    # image -> photo
    matched = {}
    for iid, (file, title, caption) in images.items():
        best, best_s = None, -1.0
        cands = by_number.get(number(file), [])
        for p in cands:
            s = (3 if full(p.stem) == full(file) else 0) \
                + (2 if title and words(title) == words(p.meta.title) else 0) \
                + (difflib.SequenceMatcher(None, words(caption), words(p.meta.caption)).ratio()
                   if caption and p.meta.caption else 0)
            if s > best_s:
                best, best_s = p, s
        # camera counters repeat over the years: a bare number match needs support
        if best and (best_s >= 1.5 or (len(cands) == 1 and best_s >= 0.5)):
            matched[iid] = best

    # galleries and images seen together in blog links (/portfolio/C/G/I, /gallery-image/x/G/I)
    seen = collections.defaultdict(set)
    for line in links.splitlines():
        g = re.search(r"(G0000" + ID + ")", line)
        i = re.search(r"(I0000" + ID + ")", line)
        if g:
            seen[g.group(1)]
            if i:
                seen[g.group(1)].add(i.group(1))

    galleries = sorted(catalog.galleries, key=lambda g: len(g.photos))

    def place_in(text: str):
        """The location gallery a caption names. A deep, generic name ("Mountains"
        under Scotland) only counts when a parent place is named too."""
        t = f" {words(text)} "
        best = None
        for g in galleries:
            names = [*g.context, g.name]
            hits = sum(1 for n in names if len(n) >= 4 and f" {words(n)} " in t)
            if f" {words(g.name)} " not in t or not (hits >= 2 or len(names) <= 2):
                continue
            key = (hits, len(names), -len(g.photos))
            if best is None or key > best[0]:
                best = (key, g)
        return (f"location:{best[1].slug}", best[1].name) if best else None

    rows, notes = [], collections.Counter()

    # galleries we have no name for: the place or theme most of their photos share
    targets = dict(KNOWN)
    for gid, iids in sorted(seen.items()):
        if gid in targets:
            continue
        ph = [matched[i] for i in iids if i in matched]
        votes = collections.Counter()
        for p in ph:
            for g in galleries:
                if p in g.photos:
                    votes[(f"location:{g.slug}", g.name, -len(g.photos))] += 1
        if votes:
            (t, name, _), n = max(votes.items(), key=lambda kv: (kv[1], kv[0][2]))
            targets[gid] = (t, f"unnamed gallery; {n} of its {len(ph)} known photos are in {name}")
        elif (places := collections.Counter(h for i in iids if i in images
                                            and (h := place_in(" ".join(images[i][1:]))))):
            (t, name), n = places.most_common(1)[0]
            targets[gid] = (t, f"unnamed gallery; {n} of its images' captions name {name}")
        else:
            targets[gid] = ("/", "unnamed gallery; no known photos")

    rows.append("# Old PhotoShelter address -> new page. Written by tools/photoshelter_map.py,")
    rows.append("# then edit freely. Left column: a PhotoShelter id (I... image, G... gallery,")
    rows.append("# C... collection; matched anywhere in the old address) or an exact old path.")
    rows.append("# Right column: photo:<file name stem>, theme:<slug>, location:<gallery slug>,")
    rows.append("# or a path on the new site. Optional third column: a note.")
    rows.append("")
    rows.append("# --- pages")
    for old, new in PAGES:
        rows.append(f"{old}\t{new}")
    rows.append("")
    rows.append("# --- collections and galleries")
    for k, (t, note) in targets.items():
        rows.append(f"{k}\t{t}\t{note}")
    rows.append("")
    rows.append("# --- images")
    gallery_of = {i: g for g, iids in seen.items() for i in iids}
    for iid, (file, title, caption) in images.items():
        label = f"{file} · {title}"[:70]
        if iid in matched:
            rows.append(f"{iid}\tphoto:{matched[iid].stem}\t{label}")
            notes["matched"] += 1
            continue
        if iid in gallery_of and targets[gallery_of[iid]][0] != "/":
            t, why = targets[gallery_of[iid]][0], "its old gallery"
        elif (hint := next((h for h in HINTS if re.search(h[0], f"{title} {caption}", re.I)), None)):
            t, why = hint[1], f"hint {hint[0]}"
        elif (hit := place_in(f"{title} {caption}")):
            t, why = hit[0], f"caption names {hit[1]}"
        else:
            t, why = "/", "no match"
        notes[why.split()[0]] += 1
        rows.append(f"{iid}\t{t}\tnot on the new site ({why}) · {label}")

    out = config.content_dir / "redirects.tsv"
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}: {len(images)} images "
          f"({notes['matched']} matched to photos, {notes['its']} to their old gallery, "
          f"{notes['caption']} by a place in the caption, {notes['hint']} by title words, {notes['no']} to the home page), "
          f"{len(targets)} galleries/collections, {len(PAGES)} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
