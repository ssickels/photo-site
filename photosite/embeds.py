"""Click-to-load embeds: an <iframe> pasted into a Markdown page (a Google
Maps "Embed a map" snippet, say) becomes a placeholder link. Nothing is
requested from the other site until the visitor clicks it; static/js/embed.js
then swaps in the real iframe. Without JavaScript the link opens the map in
a new tab. A poster="<photo file name>" attribute on the iframe shows that
published photo in the box until the click (Site.embed_posters fills it in).
"""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

IFRAME = re.compile(r"(?:<p>\s*)?<iframe\b([^>]*)>\s*</iframe>(?:\s*</p>)?", re.I | re.S)
NAMES = {"google.com/maps": "Google Maps", "youtube.com": "YouTube",
         "youtube-nocookie.com": "YouTube", "player.vimeo.com": "Vimeo"}


def _attr(attrs: str, name: str) -> str:
    m = re.search(rf'\b{name}\s*=\s*("([^"]*)"|\'([^\']*)\')', attrs, re.I)
    return html.unescape(m.group(2) if m.group(2) is not None else m.group(3)) if m else ""


def provider(src: str) -> str:
    u = urlsplit(src)
    where = u.netloc.lower().removeprefix("www.") + u.path
    return next((n for k, n in NAMES.items() if where.startswith(k)), u.netloc.removeprefix("www."))


VIDEO = {"YouTube", "Vimeo"}


def play_src(src: str, name: str) -> str:
    """The address the iframe loads after the click: videos start at once
    (the click was the visitor's "play"), and Vimeo is asked not to track."""
    if name not in VIDEO:
        return src
    u = urlsplit(src)
    q = dict(parse_qsl(u.query, keep_blank_values=True))
    q["autoplay"] = "1"
    if name == "Vimeo":
        q["dnt"] = "1"
    return urlunsplit(u._replace(query=urlencode(q)))


def click_to_load(body: str) -> str:
    def placeholder(m):
        attrs = m.group(1)
        src = _attr(attrs, "src")
        if not src.startswith("https://"):
            return m.group(0)
        w, h = _attr(attrs, "width"), _attr(attrs, "height")
        ratio = f"{w} / {h}" if w.isdigit() and h.isdigit() and int(h) else "4 / 3"
        name = provider(src)
        title = _attr(attrs, "title") or name
        allow = _attr(attrs, "allow") or ("autoplay; fullscreen; picture-in-picture" if name in VIDEO else "")
        e = lambda s: html.escape(s, quote=True)
        poster = _attr(attrs, "poster")
        label = ("Show map" if name == "Google Maps" else
                 f"\u25b6\ufe0e Play {e(title)}" if name in VIDEO else f"Show {e(title)}")
        return (f'<figure class="embed{" has-poster" if poster else ""}" style="--embed-ar:{ratio}">'
                f'<a class="embed-load" href="{e(src)}" target="_blank" rel="noopener" '
                f'data-embed="{e(play_src(src, name))}" data-title="{e(title)}"'
                f'{f" data-allow={chr(34)}{e(allow)}{chr(34)}" if allow else ""}'
                f'{" data-fullscreen" if name in VIDEO or re.search(r"allowfullscreen", attrs, re.I) else ""}'
                f'{" data-video" if name in VIDEO else ""}>'
                f'{f"<span class={chr(34)}embed-poster{chr(34)} data-poster={chr(34)}{e(poster)}{chr(34)}></span>" if poster else ""}'
                f'<span class="embed-label">{label}</span>'
                f'<span class="embed-note">Loads {e(name)}, which may set cookies</span>'
                f'</a></figure>')
    return IFRAME.sub(placeholder, body)
