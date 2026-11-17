"""Click-to-load embeds: an <iframe> pasted into a Markdown page (a Google
Maps "Embed a map" snippet, say) becomes a placeholder link. Nothing is
requested from the other site until the visitor clicks it; static/js/embed.js
then swaps in the real iframe. Without JavaScript the link opens the map in
a new tab.
"""
from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

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
        e = lambda s: html.escape(s, quote=True)
        return (f'<figure class="embed" style="--embed-ar:{ratio}">'
                f'<a class="embed-load" href="{e(src)}" target="_blank" rel="noopener" '
                f'data-embed="{e(src)}" data-title="{e(title)}"'
                f'{" data-fullscreen" if re.search(r"allowfullscreen", attrs, re.I) else ""}>'
                f'<span class="embed-label">Show {"map" if name == "Google Maps" else e(title)}</span>'
                f'<span class="embed-note">Loads {e(name)}, which may set cookies</span>'
                f'</a></figure>')
    return IFRAME.sub(placeholder, body)
