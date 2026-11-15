"""Render HTML pages, static assets, sitemap and robots.txt into dist/<target>/.

URL layout (all root-relative):
    /                               home
    /themes/                        themes index
    /<theme>/  /<theme>/<photo>/    theme gallery, photo page
    /locations/                     curated location list
    /locations/<loc>/  .../<photo>/ location gallery, photo page
    /<page>/                        content/<page>.md (about, contact)
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import markdown
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .config import Config
from .model import Catalog, LocationGallery, Photo, Theme

ROOT = Path(__file__).resolve().parent.parent

# Approximate tile heights for the justified grid (keep in sync with site.css
# --row-h). Tiles grow up to ~1.6x to fill a row; used only for `sizes`.
ROW_H_MOBILE, ROW_H_DESKTOP, ROW_GROW = 150, 260, 1.6
# How much of the viewport height the photo-page image may use (site.css).
PHOTO_CHROME = "6.8rem"
LOGO_H = 53                  # px; matches --logo-h in site.css
TURNSTILE_ACTION = "photography-contact"   # tells this form's tokens apart on a shared widget
EAGER_ASPECT = 6.0      # tiles until the summed aspect ratio passes this load eagerly


@dataclass
class Context:
    """A sequence of photos a photo page can belong to (theme or location)."""
    kind: str                     # "theme" | "location"
    name: str
    url: str
    photos: list
    obj: object


def _srcset(rec: dict, fmt: str) -> str:
    return ", ".join(f"/img/{s[fmt]['file']} {s['w']}w" for s in rec["sizes"])


def _pick(rec: dict, width: int) -> dict:
    """Smallest derivative at least `width` wide (or the largest)."""
    return next((s for s in rec["sizes"] if s["w"] >= width), rec["sizes"][-1])


class Site:
    def __init__(self, config: Config, catalog: Catalog, records: dict, target: str = "production"):
        self.config, self.catalog, self.records = config, catalog, records
        self.target = config.target(target)
        self.static_urls: dict[str, str] = {}
        self.logo: dict | None = None               # set by copy_static if static/img/logo.png exists
        self.env = Environment(loader=FileSystemLoader(str(ROOT / "templates")),
                               autoescape=select_autoescape(["html", "xml"]),
                               undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
        self.env.globals.update(site=config.site, target=self.target, static=self.static,
                                img=self.img, nav=self.nav_items, fmt_date=fmt_date,
                                placeholder=config.images.placeholder,
                                logo=lambda: self.logo, turnstile_action=TURNSTILE_ACTION)
        self.pages: list[tuple[str, Path]] = []     # (url, file) for sitemap
        self.canonical_urls: list[str] = []

    # ------------------------------------------------------------ urls
    @staticmethod
    def theme_url(t: Theme) -> str:
        return f"/{t.slug}/"

    @staticmethod
    def gallery_url(g: LocationGallery) -> str:
        return f"/locations/{g.slug}/"

    def canonical_photo_url(self, p: Photo) -> str:
        return f"{self.theme_url(p.canonical_theme)}{p.id}/"

    def absolute(self, url: str) -> str:
        return self.target["base_url"] + url

    def static(self, name: str) -> str:
        return self.static_urls[name]

    def nav_items(self):
        items = [("Themes", "/themes/", "themes"), ("Locations", "/locations/", "locations")]
        if (self.config.content_dir / "about.md").exists():
            items.append(("About", "/about/", "about"))
        if self.config.site.get("blog_url"):
            items.append(("Blog", self.config.site["blog_url"], "blog"))
        return items

    # ----------------------------------------------------------- images
    def img(self, p: Photo, sizes: str) -> dict:
        """Everything a template needs for one <picture>."""
        rec = self.records[p.id]
        fallback = _pick(rec, 960)
        return {"w": rec["width"], "h": rec["height"], "ar": rec["width"] / rec["height"],
                "src": f"/img/{fallback['jpeg']['file']}",
                "jpeg_srcset": _srcset(rec, "jpeg"), "webp_srcset": _srcset(rec, "webp"),
                "sizes": sizes, "color": rec["color"], "lqip": rec["lqip"], "alt": p.alt,
                "og": self.absolute(f"/img/{_pick(rec, 1600)['jpeg']['file']}")}

    def tile_sizes(self, p: Photo) -> str:
        ar = self.records[p.id]["width"] / self.records[p.id]["height"]
        m = round(ar * ROW_H_MOBILE * ROW_GROW)
        d = round(ar * ROW_H_DESKTOP * ROW_GROW)
        return f"(max-width: 40em) min(100vw, {m}px), min(100vw, {d}px)"

    @staticmethod
    def card_sizes() -> str:
        return "(max-width: 40em) 100vw, (max-width: 70em) 50vw, 33vw"

    def photo_sizes(self, p: Photo, chrome: str = PHOTO_CHROME) -> str:
        """Rendered width of an image fitted to the viewport height (see site.css)."""
        ar = self.records[p.id]["width"] / self.records[p.id]["height"]
        return f"min(100vw, calc((100vh - {chrome}) * {ar:.4f}))"

    def tiles(self, ctx: Context) -> list[dict]:
        out, acc = [], 0.0
        for p in ctx.photos:
            im = self.img(p, self.tile_sizes(p))
            out.append({"photo": p, "img": im, "url": f"{ctx.url}{p.id}/",
                        "eager": acc < EAGER_ASPECT})
            acc += im["ar"]
        return out

    # ----------------------------------------------------------- output
    def write(self, out: Path, url: str, template: str, *, canonical: str | None = None,
              in_sitemap: bool = True, **ctx) -> None:
        canonical = canonical or url
        html = self.env.get_template(template).render(
            url=url, canonical=self.absolute(canonical), **ctx)
        rel = url.strip("/")
        path = out / rel / "index.html" if not rel.endswith(".html") else out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        if in_sitemap and canonical == url:
            self.canonical_urls.append(url)

    def copy_static(self, out: Path) -> None:
        """Copy static/ with a content hash in css/js/png/svg names (cache forever)."""
        src_root = ROOT / "static"
        for f in sorted(src_root.rglob("*")):
            if not f.is_file() or f.name.startswith("."):
                continue
            rel = f.relative_to(src_root).as_posix()
            if rel.startswith("root/"):
                dest_rel = rel[len("root/"):]          # favicon.ico etc. at site root
            elif f.suffix in (".css", ".js", ".png", ".svg"):
                h = hashlib.sha256(f.read_bytes()).hexdigest()[:8]
                stem = rel.rsplit(".", 1)[0]
                dest_rel = f"static/{stem}.{h}{f.suffix}"
            else:
                dest_rel = f"static/{rel}"
            dest = out / dest_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            self.static_urls[rel] = "/" + dest_rel
        if "img/logo.png" in self.static_urls:          # optional; text title otherwise
            from PIL import Image
            with Image.open(src_root / "img/logo.png") as im:
                w, h = im.size
            self.logo = {"src": self.static_urls["img/logo.png"],
                         "dark": self.static_urls.get("img/logo-dark.png"),
                         "width": round(LOGO_H * w / h), "height": LOGO_H}

    def context_crumbs(self, g) -> list[tuple[str, str | None]]:
        """(name, url) for each ancestor of a location gallery's node."""
        out, node = [], self.catalog.tree
        for seg in g.node.path[:-1]:
            node = node.children[seg]
            anc = self.catalog.gallery_for_path(node.path)
            out.append((node.name, self.gallery_url(anc) if anc else None))
        return out

    def render(self, out: Path) -> int:
        out.mkdir(parents=True, exist_ok=True)
        for child in out.iterdir():                  # everything but img/ is regenerated
            if child.name == "img":
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        self.copy_static(out)
        cat = self.catalog

        # contexts photo pages can live in
        contexts = [Context("theme", t.name, self.theme_url(t), t.photos, t) for t in cat.themes]
        contexts += [Context("location", g.name, self.gallery_url(g), g.photos, g)
                     for g in cat.galleries]

        hero = cat.hero
        self.write(out, "/", "home.html", section="home", hero=hero,
                   hero_img=self.img(hero, self.photo_sizes(hero, "9rem")) if hero else None,
                   themes=[(t, self.theme_url(t)) for t in cat.themes])
        self.write(out, "/themes/", "cards.html", section="themes", title="Themes",
                   cards=[self._card(t.name, self.theme_url(t), t.cover, len(t.photos),
                                     t.description) for t in cat.themes])
        self.write(out, "/locations/", "cards.html", section="locations", title="Locations",
                   cards=[self._card(g.name, self.gallery_url(g), g.cover, len(g.photos),
                                     " › ".join(g.context)) for g in cat.curated_galleries])

        for ctx in contexts:
            g = ctx.obj
            self.write(out, ctx.url, "gallery.html",
                       section="themes" if ctx.kind == "theme" else "locations",
                       title=ctx.name, context=self.context_crumbs(g) if ctx.kind == "location" else [],
                       description=getattr(g, "description", ""), tiles=self.tiles(ctx))
            for i, p in enumerate(ctx.photos):
                self._photo_page(out, ctx, i)

        for md in sorted(self.config.content_dir.glob("*.md")) if self.config.content_dir.exists() else []:
            title, body = render_markdown(md.read_text(encoding="utf-8"))
            form = md.stem == "contact" and self.config.contact.form
            self.write(out, f"/{md.stem}/", "contact.html" if form else "page.html",
                       section=md.stem, title=title or md.stem.title(), body=body,
                       contact=self.config.contact)
            if form:
                self.write_contact_php(out / "contact")

        self.write(out, "/404.html", "404.html", section="", title="Not found", in_sitemap=False)
        (out / "robots.txt").write_text(self.robots())
        (out / "sitemap.xml").write_text(self.sitemap())
        return len(list(out.rglob("*.html")))

    def _card(self, name, url, cover, count, subtitle):
        return {"name": name, "url": url, "count": count, "subtitle": subtitle,
                "img": self.img(cover, self.card_sizes()) if cover else None}

    def _photo_page(self, out: Path, ctx: Context, i: int) -> None:
        p = ctx.photos[i]
        prev = ctx.photos[i - 1] if i > 0 else None
        nxt = ctx.photos[i + 1] if i + 1 < len(ctx.photos) else None
        url = f"{ctx.url}{p.id}/"
        crumbs = [[(name, self.gallery_url(g) if g else None) for name, g in trail]
                  for trail in self.catalog.breadcrumbs(p)]
        nxt_img = self.img(nxt, self.photo_sizes(nxt)) if nxt else None
        self.write(out, url, "photo.html", canonical=self.canonical_photo_url(p),
                   section="themes" if ctx.kind == "theme" else "locations",
                   title=p.meta.title or ctx.name, photo=p, img=self.img(p, self.photo_sizes(p)),
                   ctx=ctx, index=i, total=len(ctx.photos),
                   prev_url=f"{ctx.url}{prev.id}/" if prev else None,
                   next_url=f"{ctx.url}{nxt.id}/" if nxt else None, next_img=nxt_img,
                   crumbs=crumbs, themes=[(t.name, self.theme_url(t)) for t in p.themes])

    def write_contact_php(self, dest: Path) -> None:
        """The form handler and its settings, next to /contact/index.html."""
        c, t = self.config.contact, self.target
        for name in ("contact-lib.php", "send.php"):
            shutil.copy2(ROOT / "php" / name, dest / name)
        settings = {
            "mail_to": c.mail_to,
            "mail_from": c.mail_from,
            "subject_tag": (f"[{t['name']}] " if t["name"] != "production" else "") + c.subject,
            "return_page": "/contact/",
            "turnstile_secret": c.turnstile_secret,
            "action": TURNSTILE_ACTION,
            "rl_prefix": "photosite_contact_",
            "rl_max": 5,
            "rl_window": 3600,
            "min_fill_ms": 3000,
            "site_label": t["base_url"] or t["name"],
        }
        # A PHP file that only returns an array: requesting it shows nothing,
        # so the secret and address can't be read over the web.
        blob = json.dumps(settings).replace("\\", "\\\\").replace("'", "\\'")
        (dest / "config.php").write_text(
            "<?php\n// Written by the build from site.yaml and the private site.local.yaml.\n"
            f"return json_decode('{blob}', true);\n", encoding="utf-8")

    # ----------------------------------------------------------- extras
    def robots(self) -> str:
        if self.target["noindex"]:
            return "User-agent: *\nDisallow: /\n"
        return f"User-agent: *\nAllow: /\n\nSitemap: {self.absolute('/sitemap.xml')}\n"

    def sitemap(self) -> str:
        urls = "".join(f"  <url><loc>{escape(self.absolute(u))}</loc></url>\n"
                       for u in self.canonical_urls)
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"{urls}</urlset>\n")


def fmt_date(p: Photo) -> str:
    if p.meta.date_source == "mtime":
        return ""
    d = p.meta.date
    return f"{d:%B} {d.day}, {d.year}"


def render_markdown(text: str) -> tuple[str, str]:
    """Returns (title from the first '# ' heading, html body without it)."""
    lines = text.splitlines()
    title = ""
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            del lines[i]
            break
        if line.strip():
            break
    body = markdown.markdown("\n".join(lines), extensions=["extra", "smarty"])
    return title, body
