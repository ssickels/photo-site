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
