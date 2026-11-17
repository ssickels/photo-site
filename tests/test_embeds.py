"""Pasted iframes become click-to-load placeholders: no third-party request until clicked."""
from photosite.embeds import click_to_load, provider
from photosite.render import render_markdown

MAP = ('<iframe src="https://www.google.com/maps/embed?pb=!1m18!2sLong%20Pond&amp;x=1" width="600" '
       'height="450" style="border:0;" allowfullscreen="" loading="lazy" '
       'referrerpolicy="strict-origin-when-cross-origin"></iframe>')


def test_markdown_iframe_becomes_placeholder():
    _, body = render_markdown(f"Some text.\n\n{MAP}\n\nMore text.\n")
    assert "<iframe" not in body
    assert 'data-embed="https://www.google.com/maps/embed?pb=!1m18!2sLong%20Pond&amp;x=1"' in body
    assert "--embed-ar:600 / 450" in body and "data-fullscreen" in body
    assert "Show map" in body and "Loads Google Maps" in body
    assert "<p>Some text.</p>" in body and "<p>More text.</p>" in body


def test_iframe_inside_a_paragraph_and_odd_sources():
    assert "<p>" not in click_to_load(f"<p>{MAP}</p>")
    plain = '<iframe src="http://example.com/x"></iframe>'
    assert click_to_load(plain) == plain                     # not https: left alone
    assert provider("https://www.youtube-nocookie.com/embed/abc") == "YouTube"
    assert provider("https://maps.example.org/e") == "maps.example.org"


def test_page_with_embed_gets_its_script(config, catalog, tmp_path):
    from photosite.render import Site
    site = Site(config, catalog, {}, "production")
    out = tmp_path / "out"
    site.copy_static(out)
    for url, md in (("/about/", f"# About\n\n{MAP}\n"), ("/prints/", "# Prints\n\nNo map.\n")):
        title, body = render_markdown(md)
        site.write(out, url, "page.html", section="", title=title, body=body)
    about = (out / "about" / "index.html").read_text(encoding="utf-8")
    prints = (out / "prints" / "index.html").read_text(encoding="utf-8")
    assert "js/embed." in about and "<iframe" not in about
    assert "js/embed." not in prints


def test_vimeo_plays_on_click_without_tracking():
    vid = ('<iframe src="https://player.vimeo.com/video/123456?h=abc" width="640" height="360" '
           'frameborder="0" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen '
           'title="Aurora #1"></iframe>')
    out = click_to_load(vid)
    assert 'href="https://player.vimeo.com/video/123456?h=abc"' in out
    assert 'data-embed="https://player.vimeo.com/video/123456?h=abc&amp;autoplay=1&amp;dnt=1"' in out
    assert 'data-allow="autoplay; fullscreen; picture-in-picture"' in out
    assert "Play Aurora #1" in out and "Loads Vimeo" in out and "--embed-ar:640 / 360" in out
    assert "autoplay" not in click_to_load(MAP)               # maps unchanged


def test_poster_shows_a_published_photo_until_the_click(config, catalog):
    from photosite.render import Site
    p = next(iter(catalog.photos.values()))
    rec = {"width": 1600, "height": 900, "color": "#123", "lqip": "",
           "sizes": [{"w": w, "jpeg": {"file": f"x-{w}.jpg"}, "webp": {"file": f"x-{w}.webp"}}
                     for w in (960, 1600)]}
    site = Site(config, catalog, {p.id: rec}, "production")
    vid = (f'<iframe src="https://player.vimeo.com/video/1" width="640" height="360" '
           f'poster="{p.stem}" title="Aurora #1"></iframe>')
    out = site.embed_posters(click_to_load(vid))
    assert 'class="embed has-poster"' in out and 'srcset="/img/x-960.webp 960w' in out
    assert "data-poster" not in out and "Play Aurora #1" in out
    missing = site.embed_posters(click_to_load(vid.replace(p.stem, "no-such-photo")))
    assert "<picture" not in missing and "data-poster" not in missing
    assert any("no-such-photo" in w for w in catalog.warnings)
