"""content/redirects.tsv -> .htaccess rewrite rules, checked with a small mod_rewrite emulator."""
import re

import pytest

from photosite import redirects


def emulate(htaccess: str, path: str, host: str, https: bool = True):
    """Follow the mod_rewrite rules of a generated .htaccess for one request.
    Returns the redirect target, or None if the request is served as is.
    Covers what the build writes: REQUEST_URI/HTTPS/HTTP_HOST conditions,
    [OR], [NC], [S=n], [L], [R=301]."""
    lines = [l.strip() for l in htaccess.splitlines()]
    start = lines.index("RewriteEngine On") + 1
    end = lines.index("</IfModule>", start)
    rules, conds = [], []
    for l in lines[start:end]:
        if l.startswith("RewriteCond"):
            _, var, pat, *flags = l.split()
            conds.append((var, pat, flags[0] if flags else ""))
        elif l.startswith("RewriteRule"):
            _, pat, target, *flags = l.split()
            rules.append((conds, pat, target, flags[0] if flags else ""))
            conds = []
    env = {"%{REQUEST_URI}": path, "%{HTTPS}": "on" if https else "off", "%{HTTP_HOST}": host}
    i = 0
    while i < len(rules):
        conds, pat, target, flags = rules[i]
        ok, pending_or = True, False
        results = []
        for var, cpat, cflags in conds:
            neg = cpat.startswith("!")
            cpat = cpat[1:] if neg else cpat
            val = env[var]
            hit = (val == cpat[1:]) if cpat.startswith("=") else \
                bool(re.search(cpat, val, re.I if "NC" in cflags else 0))
            results.append((hit != neg, "OR" in cflags))
        # combine: consecutive [OR] conditions form one group, groups are ANDed
        group = []
        for res, is_or in results:
            group.append(res)
            if not is_or:
                ok = ok and any(group)
                group = []
        if group:
            ok = ok and any(group)
        if ok and re.search(pat, path.lstrip("/")):
            if target == "-":
                m = re.search(r"S=(\d+)", flags)
                i += 1 + (int(m.group(1)) if m else 0)
                continue
            if "R=" in flags:
                return target.replace("%{REQUEST_URI}", path)
        i += 1
    return None


@pytest.fixture
def site(config, catalog, tmp_path):
    from photosite.render import Site
    config.content_dir = tmp_path / "content"
    config.content_dir.mkdir()
    return Site(config, catalog, {}, "production")


def write_tsv(site, text):
    (site.config.content_dir / "redirects.tsv").write_text(text, encoding="utf-8")


def test_redirects_follow_photos_galleries_and_pages(site, catalog):
    photo = next(iter(catalog.photos.values()))
    theme = catalog.themes[0]
    write_tsv(site, "\n".join([
        "# comment",
        "/p/print-options\t/prints/",
        "C0000AAAAAAAAAAA\t/themes/\tcollection",
        f"G0000BBBBBBB.BBB\ttheme:{theme.slug}",
        f"I0000CCCC_CCC.CC\tphoto:{photo.stem}\tnote",
        "I0000DDDDDDDDDDD\tphoto:no-such-photo",
    ]) + "\n")
    ht = site.htaccess()
    base, host = "https://example.test", "example.test"
    photo_url = base + site.canonical_photo_url(photo)

    # an image wins over the gallery and collection in the same address
    assert emulate(ht, "/portfolio/C0000AAAAAAAAAAA/G0000BBBBBBB.BBB/I0000CCCC_CCC.CC", host) == photo_url
    assert emulate(ht, "/gallery-image/Some-Name/G0000BBBBBBB.BBB/I0000CCCC_CCC.CC", host) == photo_url
    assert emulate(ht, "/image/I0000CCCC_CCC.CC", host) == photo_url
    # an image the list doesn't know falls back to its gallery
    assert emulate(ht, "/gallery-image/X/G0000BBBBBBB.BBB/I0000ZZZZZZZZZZZ", host) == f"{base}/{theme.slug}/"
    assert emulate(ht, "/gallery/Name/G0000BBBBBBB.BBB/", host) == f"{base}/{theme.slug}/"
    assert emulate(ht, "/gallery-collection/Portfolio/C0000AAAAAAAAAAA", host) == f"{base}/themes/"
    assert emulate(ht, "/p/print-options", host) == f"{base}/prints/"
    assert emulate(ht, "/p/print-options/", host) == f"{base}/prints/"
    # anything else under an old section goes home, not to a 404
    assert emulate(ht, "/gallery/Unknown/G0000QQQQQQQQQQQ/", host) == f"{base}/"
    # a missing photo: home page, and a warning
    assert emulate(ht, "/image/I0000DDDDDDDDDDD", host) == f"{base}/"
    assert any("no-such-photo" in w for w in site.catalog.warnings)
    # the dot in an id is literal, not "any character"
    assert emulate(ht, "/image/I0000CCCC_CCCxCC", host) == f"{base}/"


def test_new_site_pages_are_untouched(site, catalog):
    photo = next(iter(catalog.photos.values()))
    write_tsv(site, f"I0000CCCC_CCC.CC\tphoto:{photo.stem}\n/index\t/\n")
    ht = site.htaccess()
    host = "example.test"
    for path in ["/", "/themes/", "/locations/", "/about/", "/prints/", "/index.html",
                 "/img/abc.webp", site.canonical_photo_url(photo)]:
        assert emulate(ht, path, host) is None, path
    # the host/https redirect still works, after the old-address list
    assert emulate(ht, "/themes/", "www.example.test") == "https://example.test/themes/"
    assert emulate(ht, "/themes/", host, https=False) == "https://example.test/themes/"
    assert emulate(ht, "/index", host) == "https://example.test/"


def test_no_redirects_file_means_no_list(site):
    ht = site.htaccess()
    assert "Old addresses" not in ht and "RewriteEngine On" in ht


def test_load_tolerates_spaces_and_rejects_half_lines(tmp_path):
    f = tmp_path / "redirects.tsv"
    f.write_text("I0000AAAAAAAAAAA   /themes/\n\n# x\n", encoding="utf-8")
    assert redirects.load(f) == [("I0000AAAAAAAAAAA", "/themes/", 1)]
    f.write_text("I0000AAAAAAAAAAA\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        redirects.load(f)
