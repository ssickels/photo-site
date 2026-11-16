"""Travels: one page per trip, from a Markdown file in content/travels/.

    ---
    dates: 2026-01-19 to 2026-01-27      # or a single date
    place: norway                        # optional: a place keyword (as in location_galleries)
    cover: 20260121-DSC01234-Edit        # optional: photo for the Travels index card
    photos: [...]                        # optional: only these photos (stems or ids)
    exclude: [...]                       # optional: leave these out
    by_day: true                         # optional: group photos under a heading per day
    ---
    # Winter in Norway

    The story of the trip, in Markdown.

    ## 2026-01-23 North Cape
    Optional text for one day, shown under that day's heading. Anything
    after the date becomes part of the heading ("Friday, January 23 ·
    North Cape"). A day with text but no photos still gets its section.

The build picks every published photo taken within the dates (and, with
`place`, at that place or anywhere below it), oldest first. Photos must be
published in some theme; the trip page doesn't add photos of its own.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import Config, ConfigError
from .model import Catalog, Photo, resolve_node

DAY_HEADING = re.compile(r"^##[ \t]+(\d{4}-\d{2}-\d{2})\b[ \t]*(.*?)[ \t]*#*[ \t]*$", re.M)
FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass
class Trip:
    slug: str
    title: str
    start: dt.date
    end: dt.date
    body_md: str
    source: Path
    place: str = ""
    photos: list = field(default_factory=list)
    cover: Photo | None = None
    by_day: bool = True
    notes: dict = field(default_factory=dict)       # date -> (heading extra, markdown)

    @property
    def days(self) -> list[tuple[dt.date, list]]:
        """(date, photos) for every day with photos or a note, in order."""
        by: dict[dt.date, list] = {d: [] for d in self.notes}
        for p in self.photos:
            by.setdefault(p.date.date(), []).append(p)
        return sorted(by.items())

    @property
    def date_range(self) -> str:
        return date_range(self.start, self.end)


def date_range(a: dt.date, b: dt.date) -> str:
    if a == b:
        return f"{a:%B} {a.day}, {a.year}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{a:%B} {a.day}–{b.day}, {a.year}"
    if a.year == b.year:
        return f"{a:%B} {a.day} – {b:%B} {b.day}, {a.year}"
    return f"{a:%B} {a.day}, {a.year} – {b:%B} {b.day}, {b.year}"


def _date(v, where: str) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v).strip())
    except ValueError:
        raise ConfigError(f"{where}: {v!r} isn't a date (use YYYY-MM-DD)") from None


def _dates(meta: dict, where: str) -> tuple[dt.date, dt.date]:
    if "dates" in meta:
        v = meta["dates"]
        parts = re.split(r"\s+to\s+|\s+–\s+|\s+-\s+", str(v).strip()) if isinstance(v, str) else [v]
        start = _date(parts[0], where)
        end = _date(parts[-1], where)
    elif "start" in meta:
        start = _date(meta["start"], where)
        end = _date(meta.get("end", meta["start"]), where)
    else:
        raise ConfigError(f"{where}: needs `dates: YYYY-MM-DD to YYYY-MM-DD`")
    if end < start:
        raise ConfigError(f"{where}: the end date is before the start date")
    return start, end


def split_day_notes(body: str, where: str, warnings: list) -> tuple[str, dict]:
    """Intro text, and {date: (heading extra, markdown)} from `## YYYY-MM-DD ...` sections."""
    marks = list(DAY_HEADING.finditer(body))
    notes: dict = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        try:
            d = dt.date.fromisoformat(m.group(1))
        except ValueError:
            warnings.append(f"{where}: '## {m.group(1)}' isn't a real date")
            continue
        if d in notes:
            warnings.append(f"{where}: two notes for {d}; using the first")
            continue
        notes[d] = (m.group(2).strip(), body[m.end():end].strip())
    return (body[:marks[0].start()] if marks else body), notes


def load_trips(config: Config, catalog: Catalog, warnings: list) -> list[Trip]:
    folder = config.content_dir / "travels"
    if not folder.is_dir():
        return []
    trips = []
    for md in sorted(folder.glob("*.md")):
        if md.name.startswith(("_", ".")):
            continue
        where = f"content/travels/{md.name}"
        text = md.read_text(encoding="utf-8")
        m = FRONT.match(text)
        meta = (yaml.safe_load(m.group(1)) or {}) if m else {}
        body = text[m.end():] if m else text
        if not isinstance(meta, dict):
            raise ConfigError(f"{where}: the part between the --- lines must be `key: value` lines")
        start, end = _dates(meta, where)
        slug = str(meta.get("slug") or md.stem).lower()
        if not SLUG_OK.match(slug):
            raise ConfigError(f"{where}: file name / slug {slug!r} may only use a-z, 0-9 and -")

        title = str(meta.get("title") or "")
        heading = re.match(r"\s*#\s+(.+)\n", body)
        if heading:
            title = title or heading.group(1).strip()
            body = body[heading.end():]
        intro, notes = split_day_notes(body, where, warnings)
        trip = Trip(slug=slug, title=title or slug, start=start, end=end, body_md=intro,
                    source=md, by_day=bool(meta.get("by_day", True)), notes=notes)
        for d in notes:
            if not start <= d <= end:
                warnings.append(f"{where}: the note for {d} is outside the trip's dates")
        if notes and not trip.by_day:
            warnings.append(f"{where}: day notes are ignored with by_day: false")

        pool = [p for p in catalog.photos.values()
                if p.meta.date_source != "mtime" and start <= p.date.date() <= end]
        if meta.get("place"):
            node = resolve_node(str(meta["place"]), catalog.tree, config.location_root)
            if node is None:
                warnings.append(f"{where}: place {meta['place']!r} matches no place keyword")
                pool = []
            else:
                trip.place = node.name
                pool = [p for p in pool if any(loc[:len(node.path)] == node.path
                                               for loc in p.locations)]
        def find(names, what):
            out = []
            for n in names or []:
                n = str(n)
                hit = next((p for p in catalog.photos.values() if n in (p.id, p.stem)), None)
                if hit is None:
                    warnings.append(f"{where}: {what} names {n!r}, which isn't a published photo")
                else:
                    out.append(hit)
            return out

        if meta.get("photos"):
            chosen = find(meta["photos"], "photos")
            outside = [p.id for p in chosen if not start <= p.date.date() <= end]
            if outside:
                warnings.append(f"{where}: {', '.join(outside)} taken outside the trip's dates")
            pool = chosen
        excluded = {p.id for p in find(meta.get("exclude"), "exclude")}
        trip.photos = sorted({p.id: p for p in pool if p.id not in excluded}.values(),
                             key=lambda p: (p.date, p.id))
        if not trip.photos:
            warnings.append(f"{where}: no published photos match its dates and place; left out")
            continue
        cover = find([meta["cover"]], "cover") if meta.get("cover") else []
        trip.cover = cover[0] if cover else trip.photos[0]
        trips.append(trip)

    slugs = {}
    for t in trips:
        if t.slug in slugs:
            raise ConfigError(f"two trips have the slug {t.slug!r}")
        slugs[t.slug] = t
    return sorted(trips, key=lambda t: t.start, reverse=True)


def _node_name(catalog: Catalog, path: tuple) -> str:
    node = catalog.tree
    for seg in path:
        if seg not in node.children:
            return path[-1]
        node = node.children[seg]
    return node.name


def suggest_trips(config: Config, catalog: Catalog, min_photos: int = 5, gap_days: int = 5) -> str:
    """Likely trips: runs of published photos taken within `gap_days` of each
    other in the same region (the first two levels of the place keyword),
    with ready-to-paste lines for a trip file. Trips that already have a file
    are marked."""
    warnings: list = []
    existing = load_trips(config, catalog, warnings)

    def region(p):
        return tuple(p.locations[0][:2]) if p.locations else ()

    photos = sorted((p for p in catalog.photos.values() if p.meta.date_source != "mtime"),
                    key=lambda p: p.date)
    runs: list[dict] = []
    for p in photos:
        r, d = region(p), p.date.date()
        run = next((x for x in reversed(runs[-3:])
                    if x["region"] == r and (d - x["end"]).days <= gap_days), None)
        if run:
            run["end"] = d
            run["photos"].append(p)
        else:
            runs.append({"region": r, "start": d, "end": d, "photos": [p]})

    lines = [f"Likely trips (at least {min_photos} published photos, in the same region, "
             f"no more than {gap_days} days apart). Newest first.", ""]
    for run in sorted(runs, key=lambda x: x["start"], reverse=True):
        if len(run["photos"]) < min_photos or not run["region"]:
            continue
        done = [t.slug for t in existing if t.start <= run["end"] and run["start"] <= t.end]
        places = {}
        for p in run["photos"]:
            for loc in p.locations:
                name = _node_name(catalog, loc[:3])
                places[name] = places.get(name, 0) + 1
        top = ", ".join(n for n, _ in sorted(places.items(), key=lambda kv: -kv[1])[:4])
        head = (f"{date_range(run['start'], run['end'])}  ·  {len(run['photos'])} photos  ·  "
                f"{top}" + (f"   [has a page: {', '.join(done)}]" if done else ""))
        lines += [head,
                  f"    dates: {run['start']} to {run['end']}",
                  f"    place: {run['region'][-1]}", ""]
    return "\n".join(lines).rstrip() + "\n"
