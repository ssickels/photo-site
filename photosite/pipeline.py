"""Glue: config -> scan -> metadata -> catalog -> images -> dist/<target>/."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import Config
from .images import ImageResult, link_into, process_images
from .metadata import file_hashes, read_raw_metadata, scan_publish
from .model import Catalog, build_catalog
from .render import Site


@dataclass
class BuildResult:
    catalog: Catalog
    images: ImageResult | None
    timings: dict = field(default_factory=dict)
    exiftool_reads: int = 0
    scan_warnings: list = field(default_factory=list)
    pages: int = 0


def load_catalog(config: Config, timings: dict | None = None) -> tuple[Catalog, int, list]:
    t = timings if timings is not None else {}
    t0 = time.perf_counter()
    files, scan_warnings = scan_publish(config.publish_dir)
    t["scan"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    hashes = file_hashes(files, config.cache_dir)
    t["hash"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    raw, n_read = read_raw_metadata(files, config.cache_dir)
    t["metadata"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    catalog = build_catalog(config, files, raw, hashes)
    t["model"] = time.perf_counter() - t0
    return catalog, n_read, scan_warnings


def build(config: Config, target: str = "production", workers: int | None = None,
          progress=None) -> BuildResult:
    timings: dict = {}
    catalog, n_read, scan_warnings = load_catalog(config, timings)

    t0 = time.perf_counter()
    images = process_images(list(catalog.photos.values()), config.images, config.cache_dir,
                            config.site.get("default_copyright", ""), workers, progress)
    timings["images"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    out = config.output_dir / target
    link_into(images.records, config.cache_dir, out / "img")
    pages = Site(config, catalog, images.records, target).render(out)
    timings["output"] = time.perf_counter() - t0
    res = BuildResult(catalog, images, timings, n_read, scan_warnings)
    res.pages = pages
    return res
