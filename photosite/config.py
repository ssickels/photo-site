"""Load and validate site.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    """A problem in site.yaml the user has to fix."""


@dataclass
class ImageSettings:
    widths: list[int] = field(default_factory=lambda: [480, 960, 1600, 2400])
    jpeg_quality: int = 82
    webp_quality: int = 82
    webp_method: int = 5
    workers: int = 0
    placeholder: str = "color"      # color | blur | none  (doesn't affect files)

    def fingerprint(self) -> dict:
        """The settings that change derivative bytes (workers doesn't)."""
        return {
            "widths": sorted(self.widths),
            "jpeg_quality": self.jpeg_quality,
            "webp_quality": self.webp_quality,
            "webp_method": self.webp_method,
        }

    def __post_init__(self):
        if self.placeholder not in ("color", "blur", "none"):
            raise ConfigError("images.placeholder must be color, blur or none")


@dataclass
class Config:
    root: Path                      # project directory (where site.yaml lives)
    site: dict
    publish_dir: Path
    output_dir: Path
    cache_dir: Path
    themes: dict                    # folder name -> overrides (ordered)
    home: dict
    location_root: str
    cover_root: str
    location_galleries: list
    location_labels: dict
    location_tree: bool
    images: ImageSettings
    deploy: dict
    content_dir: Path = None

    def target(self, name: str) -> dict:
        """Per-target settings: base_url and noindex (staging defaults to noindex)."""
        t = dict((self.deploy or {}).get(name) or {})
        base = str(t.get("base_url") or self.site.get("base_url") or "").rstrip("/")
        # production is never noindex, whatever site.yaml says
        noindex = False if name == "production" else bool(t.get("noindex", True))
        return {"name": name, "base_url": base, "noindex": noindex}


def _resolve(root: Path, p: str | os.PathLike) -> Path:
    p = Path(os.path.expanduser(str(p)))
    return p if p.is_absolute() else (root / p)


def load_config(path: str | os.PathLike = "site.yaml", *, publish=None,
                output=None, cache=None) -> Config:
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    root = path.parent

    paths = data.get("paths") or {}
    themes = data.get("themes") or {}
    if not isinstance(themes, dict):
        raise ConfigError("`themes` must be a mapping of folder name -> options")
    themes = {str(k): (v or {}) for k, v in themes.items()}

    galleries = data.get("location_galleries") or []
    if not isinstance(galleries, list):
        raise ConfigError("`location_galleries` must be a list")
    for i, g in enumerate(galleries):
        if isinstance(g, str):
            galleries[i] = {"node": g}
        elif not isinstance(g, dict) or not g.get("node"):
            raise ConfigError(f"location_galleries[{i}] needs a `node`")

    img = data.get("images") or {}
    known = set(ImageSettings.__dataclass_fields__)
    unknown = set(img) - known
    if unknown:
        raise ConfigError(f"unknown images settings: {', '.join(sorted(unknown))}")
    images = ImageSettings(**img)
    if not images.widths or any(int(w) <= 0 for w in images.widths):
        raise ConfigError("images.widths must be a list of positive integers")
    images.widths = sorted(int(w) for w in images.widths)

    labels = {str(k).lower(): str(v) for k, v in (data.get("location_labels") or {}).items()}

    return Config(
        root=root,
        site=data.get("site") or {},
        publish_dir=_resolve(root, publish or paths.get("publish", "publish")),
        output_dir=_resolve(root, output or paths.get("output", "dist")),
        cache_dir=_resolve(root, cache or paths.get("cache", ".cache")),
        themes=themes,
        home=data.get("home") or {},
        location_root=str(data.get("location_root") or "Places"),
        cover_root=str(data.get("cover_root") or "Covers"),
        location_galleries=galleries,
        location_labels=labels,
        location_tree=bool(data.get("location_tree", False)),
        images=images,
        deploy=data.get("deploy") or {},
        content_dir=_resolve(root, paths.get("content", "content")),
    )
