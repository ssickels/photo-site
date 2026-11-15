"""Build the fixture site, serve it with http.server, crawl it."""
import functools
import http.server
import re
import threading
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import pytest

from photosite.config import load_config
from photosite.pipeline import build
from tests.conftest import TEST_CONFIG


@pytest.fixture(scope="module")
def site(publish_dir, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("site")
    cfg = load_config(TEST_CONFIG, publish=publish_dir, output=tmp / "dist", cache=tmp / "cache")
    build(cfg, "production")
    build(cfg, "staging")
    return cfg


@pytest.fixture(scope="module")
def server(site):
    root = site.output_dir / "production"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs, self.imgs, self.tags = [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        for k in ("href", "src"):
            if a.get(k):
                self.refs.append(a[k])
        for k in ("srcset",):
            if a.get(k):
                self.refs += [part.strip().split()[0] for part in a[k].split(",")]
        if tag == "img" and not a.get("src", "").startswith("/static/"):   # photos, not the logo
            self.imgs.append(a)


def parse(html):
    p = Links()
    p.feed(html)
    return p


def test_crawl_has_no_broken_links_or_images(server):
    seen, queue, broken, pages = set(), ["/"], [], 0
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        try:
            with urllib.request.urlopen(server + path) as r:
                body = r.read()
                ctype = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            broken.append((path, e.code))
            continue
        if "html" in ctype:
            pages += 1
            for ref in parse(body.decode()).refs:
                u = urlparse(urljoin(server + path, ref))
                if u.netloc == urlparse(server).netloc and not ref.startswith("data:"):
                    queue.append(u.path)
    assert broken == []
    assert pages >= 40
    assert any(p.startswith("/img/") and p.endswith(".webp") for p in seen)


def test_every_page_reachable_from_home(site, server):
    root = site.output_dir / "production"
    files = {"/" + str(f.relative_to(root).parent).replace(".", "").strip("/") for f in root.rglob("index.html")}
    files = {f.rstrip("/") + "/" if f != "/" else "/" for f in files}
    reached, queue = set(), ["/"]
    while queue:
        path = queue.pop()
        if path in reached or not path.endswith("/"):
            continue
        reached.add(path)
        with urllib.request.urlopen(server + path) as r:
            for ref in parse(r.read().decode()).refs:
                u = urlparse(urljoin(server + path, ref))
                if u.netloc == urlparse(server).netloc:
                    queue.append(u.path)
    assert files - reached == set()


def test_img_markup_rules(site):
    root = site.output_dir / "production"
    for f in root.rglob("*.html"):
        p = parse(f.read_text())
        for img in p.imgs:
            for attr in ("width", "height", "srcset", "sizes", "alt", "loading"):
                assert img.get(attr), (f, attr, img)
            assert img["decoding"] == "async"
        tags = [t for t, _ in p.tags]
        # every <img> sits in a <picture> after a WebP <source>
        sources = [a for t, a in p.tags if t == "source" and "/logo" not in a.get("srcset", "")]
        assert len(sources) == len(p.imgs)
        assert all(s["type"] == "image/webp" for s in sources)
        assert tags.count("picture") == len(p.imgs) + 1        # + the header logo


def test_gallery_first_row_eager_rest_lazy(site):
    html = (site.output_dir / "production" / "landscapes" / "index.html").read_text()
    loading = [i["loading"] for i in parse(html).imgs]
    assert loading[0] == "eager" and loading[-1] == "lazy"
    assert loading == sorted(loading)          # all eager ones come first


def test_photo_page(site):
    root = site.output_dir / "production"
    html = (root / "locations" / "scotland" / "20230905-dsc05700" / "index.html").read_text()
    p = parse(html)
    main = p.imgs[0]
    assert main["fetchpriority"] == "high" and main["loading"] == "eager"
    canon = [a["href"] for t, a in p.tags if t == "link" and a.get("rel") == "canonical"]
    assert canon == ["https://example.test/landscapes/20230905-dsc05700/"]
    assert "Raasay from Skye" in html
    # two place paths -> two trails; Scotland links to its gallery, Isle of Skye doesn't
    assert html.count('class="crumbs"') == 2
    assert '<a href="/locations/scotland/">Scotland</a>' in html
    assert "<span>Isle of Skye</span>" in html
    assert 'data-next="' in html or 'data-prev="' in html


def test_photo_in_two_themes_canonical_is_first_theme(site):
    root = site.output_dir / "production"
    html = (root / "plants-and-flowers" / "20240615-dsc01234" / "index.html").read_text()
    assert 'rel="canonical" href="https://example.test/landscapes/20240615-dsc01234/"' in html
    assert '<a href="/landscapes/">Landscapes</a>, <a href="/plants-and-flowers/">Plants and Flowers</a>' in html


def test_no_metadata_photo_page(site):
    html = (site.output_dir / "production" / "plants-and-flowers" / "20200101-img-0001" / "index.html").read_text()
    assert 'alt="Photograph"' in html
    assert "January 1, 2020" in html             # date from filename


def test_locations_index_in_config_order(site):
    html = (site.output_dir / "production" / "locations" / "index.html").read_text()
    names = re.findall(r'class="card-name">([^<]+)<', html)
    assert names == ["Europe", "Scotland", "Maine", "Acadia / Mount Desert Island", "Georgia"]
    assert "Europe › United Kingdom" in html


def test_sitemap_has_only_canonical_urls(site):
    xml = (site.output_dir / "production" / "sitemap.xml").read_text()
    locs = re.findall(r"<loc>([^<]+)</loc>", xml)
    assert "https://example.test/landscapes/20240615-dsc01234/" in locs
    assert not any("/locations/scotland/2" in u for u in locs)
    assert not any("/plants-and-flowers/20240615-dsc01234/" in u for u in locs)
    assert len(locs) == len(set(locs))


def test_staging_is_noindex_production_is_not(site):
    prod, stag = site.output_dir / "production", site.output_dir / "staging"
    assert "Disallow: /" in (stag / "robots.txt").read_text()
    assert "Disallow" not in (prod / "robots.txt").read_text()
    for f in stag.rglob("*.html"):
        assert '<meta name="robots" content="noindex' in f.read_text(), f
    for f in prod.rglob("*.html"):
        assert 'name="robots"' not in f.read_text(), f


def test_production_noindex_cannot_be_enabled(site):
    site.deploy["production"] = {"noindex": True}
    assert site.target("production")["noindex"] is False


def test_location_tree_option(publish_dir, tmp_path):
    cfg = load_config(TEST_CONFIG, publish=publish_dir, output=tmp_path / "dist", cache=tmp_path / "cache")
    cfg.location_tree = True
    cfg.images.widths = [200]
    build(cfg)
    root = tmp_path / "dist" / "production"
    assert (root / "locations" / "usa" / "index.html").exists()
    assert (root / "locations" / "europe-united-kingdom-scotland-isle-of-skye" / "index.html").exists()
    html = (root / "landscapes" / "20230905-dsc05700" / "index.html").read_text()
    assert 'href="/locations/europe-united-kingdom-scotland-isle-of-skye/">Isle of Skye</a>' in html
    # the index still shows only the curated list
    idx = (root / "locations" / "index.html").read_text()
    assert idx.count('class="card"') == 5


def test_photo_stage_controls(site):
    root = site.output_dir / "production"
    first = (root / "landscapes" / "index.html").read_text()
    ids = re.findall(r'<li id="([^"]+)"', first)
    html = (root / "landscapes" / ids[1] / "index.html").read_text()
    assert 'class="nav nav-prev"' in html and 'class="nav nav-next"' in html
    assert f'class="close" href="/landscapes/#{ids[1]}"' in html
    assert f"2 of {len(ids)}" in html
    # no prev arrow on the first photo, no next arrow on the last
    assert "nav-prev" not in (root / "landscapes" / ids[0] / "index.html").read_text()
    assert "nav-next" not in (root / "landscapes" / ids[-1] / "index.html").read_text()


def test_logo_and_favicons(site):
    root = site.output_dir / "production"
    html = (root / "index.html").read_text()
    p = parse(html)
    logo = next(a for t, a in p.tags if t == "img" and "/static/img/logo." in a.get("src", ""))
    assert logo["alt"] and logo["width"] and logo["height"]
    assert any(t == "source" and "logo-dark." in a.get("srcset", "") for t, a in p.tags)
    for name in ("favicon.ico", "apple-touch-icon.png"):
        assert (root / name).is_file()
    assert 'rel="apple-touch-icon"' in html


def test_location_gallery_context_crumbs_link_to_ancestors(site):
    html = (site.output_dir / "production" / "locations" / "scotland" / "index.html").read_text()
    ctx = html.split('<p class="context crumbs">', 1)[1].split("</p>", 1)[0]
    assert '<a href="/locations/europe/">Europe</a>' in ctx
    assert "<span>United Kingdom</span>" in ctx           # no gallery for it in the test config


def test_every_page_loads_header_script(site):
    root = site.output_dir / "production"
    for f in [root / "index.html", root / "themes" / "index.html", root / "landscapes" / "index.html"]:
        assert '/static/js/header.' in f.read_text()


def test_text_title_when_there_is_no_logo(publish_dir, tmp_path, monkeypatch):
    import shutil
    import photosite.render as render
    root = tmp_path / "root"
    shutil.copytree(render.ROOT / "templates", root / "templates")
    shutil.copytree(render.ROOT / "static", root / "static",
                    ignore=shutil.ignore_patterns("logo.png", "logo-dark.png"))
    monkeypatch.setattr(render, "ROOT", root)
    cfg = load_config(TEST_CONFIG, publish=publish_dir, output=tmp_path / "dist", cache=tmp_path / "cache")
    build(cfg, "production")
    html = (tmp_path / "dist" / "production" / "index.html").read_text()
    assert '<a class="site-title text" href="/">' in html and "/static/img/logo" not in html


def test_menu_pages_follow_config_order(config, catalog):
    from photosite.render import Site
    config.menu_pages = ["prints", "about", "no-such-page"]
    labels = [label for label, _, _ in Site(config, catalog, {}).nav_items()]
    assert labels[:4] == ["Themes", "Locations", "Prints", "About"]
    assert len(labels) == 4 or labels[4] == "Blog"


def test_page_images_become_clean_responsive_figures(config, catalog, tmp_path):
    from PIL import Image
    from photosite.render import Site
    config.content_dir, config.cache_dir = tmp_path / "content", tmp_path / "cache"
    config.content_dir.mkdir()
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (44.0, 20.0, 0.0)}          # GPS
    Image.new("RGB", (1200, 1600), (90, 120, 150)).save(config.content_dir / "me.jpg", exif=exif)
    out = tmp_path / "out"
    body = ('<p><img alt="Me &amp; lake" src="me.jpg" />\n<em>By <a href="/x/">her</a>.</em></p>\n'
            '<p><img alt="remote" src="https://example.test/a.jpg" /></p>')
    html = Site(config, catalog, {}).page_images(body, out)
    assert html.count('<figure class="page-photo">') == 1
    assert 'alt="Me &amp; lake"' in html and '<figcaption>By <a href="/x/">her</a>.</figcaption>' in html
    assert 'width="1200" height="1600"' in html and 'type="image/webp"' in html
    assert 'src="https://example.test/a.jpg"' in html            # not a local file: untouched
    files = list((out / "static" / "pages").iterdir())
    assert files and all(f.name.startswith("me.") for f in files)
    for f in files:
        with Image.open(f) as im:
            assert not im.getexif()                               # no GPS, nothing
