"""Image derivatives: resized WebP + JPEG, sRGB, metadata stripped.

Derivatives live in <cache>/images/files/ named
    <photo-id>.<width>.<key>.<ext>
where key = hash(source sha256 + pipeline settings + copyright), so a file
name never changes meaning and can be cached forever by browsers.

A manifest records what was made for each photo. A photo is re-rendered
only when its key changes (source re-published or settings changed).
Files no manifest entry references are deleted.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageCms, ImageOps

PIPELINE_VERSION = 1          # bump when the rendering code changes output
SRGB = ImageCms.createProfile("sRGB")
SRGB_ICC = ImageCms.ImageCmsProfile(SRGB).tobytes()
EXIF_COPYRIGHT = 0x8298


@dataclass
class ImageResult:
    records: dict                                   # photo id -> manifest record
    rendered: list = field(default_factory=list)    # photo ids rendered this run
    reused: int = 0
    removed_files: int = 0
    warnings: list = field(default_factory=list)


def target_widths(src_w: int, widths: list[int]) -> list[int]:
    """Configured widths below the source width; never upscale.
    If the source is narrower than the largest configured width (e.g. a
    portrait), its own width becomes the top size."""
    out = [w for w in widths if w < src_w]
    if src_w <= max(widths):
        out.append(src_w)
    return sorted(set(out))


def derivative_key(source_hash: str, fingerprint: dict, copyright: str) -> str:
    blob = json.dumps([PIPELINE_VERSION, source_hash, fingerprint, copyright], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:8]


def _to_srgb(im: Image.Image, pid: str) -> tuple[Image.Image, str, list[str]]:
    icc = im.info.get("icc_profile")
    if not icc:
        return im.convert("RGB"), "untagged (assumed sRGB)", []
    try:
        prof = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        desc = ImageCms.getProfileDescription(prof).strip()
    except (OSError, ImageCms.PyCMSError):
        return im.convert("RGB"), "unreadable profile (assumed sRGB)", [
            f"{pid}: embedded ICC profile couldn't be read; assumed sRGB"]
    if "srgb" in desc.lower():
        return im.convert("RGB"), desc, []
    out = ImageCms.profileToProfile(
        im, prof, SRGB, renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
        outputMode="RGB", flags=ImageCms.Flags.BLACKPOINTCOMPENSATION)
    return out, f"converted from {desc}", [
        f"{pid}: profile is {desc!r}, not sRGB; converted. Check the Lightroom "
        f"publish service's color space setting."]


def _save_atomic(im: Image.Image, path: Path, fmt: str, **kw) -> int:
    tmp = path.with_name(path.name + ".tmp")
    im.save(tmp, fmt, **kw)
    os.replace(tmp, path)
    return path.stat().st_size


def render_photo(job: dict) -> dict:
    """Worker (runs in a subprocess). Returns a manifest record."""
    pid, key, s = job["id"], job["key"], job["settings"]
    out_dir = Path(job["out_dir"])
    with Image.open(job["source"]) as src:
        src.load()
        im = ImageOps.exif_transpose(src)
        im.info["icc_profile"] = src.info.get("icc_profile")
    im, color_note, warnings = _to_srgb(im, pid)
    src_w, src_h = im.size

    exif = b""
    if job["copyright"]:
        e = Image.Exif()
        # bytes: Pillow would ASCII-encode a str and turn "©" into "?"
        e[EXIF_COPYRIGHT] = job["copyright"].encode("utf-8")
        exif = e.tobytes()

    sizes = []
    for w in sorted(target_widths(src_w, s["widths"]), reverse=True):
        h = round(src_h * w / src_w)
        r = im if w == src_w else im.resize((w, h), Image.Resampling.LANCZOS, reducing_gap=3.0)
        entry = {"w": w, "h": h}
        jpg = out_dir / f"{pid}.{w}.{key}.jpg"
        entry["jpeg"] = {"file": jpg.name, "bytes": _save_atomic(
            r, jpg, "JPEG", quality=s["jpeg_quality"], optimize=True, progressive=True,
            icc_profile=SRGB_ICC, exif=exif)}
        webp = out_dir / f"{pid}.{w}.{key}.webp"
        entry["webp"] = {"file": webp.name, "bytes": _save_atomic(
            r, webp, "WEBP", quality=s["webp_quality"], method=s["webp_method"],
            icc_profile=SRGB_ICC, exif=exif)}
        sizes.append(entry)
    sizes.reverse()

    # placeholders: tiny blurred WebP (inline) and a single dominant color
    tiny = im.copy()
    tiny.thumbnail((24, 24), Image.Resampling.BOX)
    buf = io.BytesIO()
    tiny.save(buf, "WEBP", quality=40, method=6)
    lqip = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    r, g, b = im.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))[:3]

    return {"id": pid, "key": key, "source_hash": job["source_hash"],
            "width": src_w, "height": src_h, "color_note": color_note,
            "sizes": sizes, "lqip": lqip, "color": f"#{r:02x}{g:02x}{b:02x}",
            "warnings": warnings}


def _record_ok(rec: dict | None, key: str, out_dir: Path) -> bool:
    if not rec or rec.get("key") != key:
        return False
    return all((out_dir / s[f]["file"]).exists() for s in rec["sizes"] for f in ("jpeg", "webp"))


def process_images(photos: list, settings, cache_dir: Path, default_copyright: str = "",
                   workers: int | None = None, progress=None) -> ImageResult:
    """Make or reuse derivatives for `photos` (model.Photo objects)."""
    base = Path(cache_dir) / "images"
    out_dir = base / "files"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = base / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        manifest = {}

    fp = settings.fingerprint()
    result = ImageResult(records={})
    jobs = []
    for p in photos:
        copyright = p.meta.copyright or default_copyright
        key = derivative_key(p.source_hash, fp, copyright)
        rec = manifest.get(p.id)
        if _record_ok(rec, key, out_dir):
            result.records[p.id] = rec
            result.warnings += rec.get("warnings", [])
            result.reused += 1
        else:
            jobs.append({"id": p.id, "key": key, "source": str(p.source.path),
                         "source_hash": p.source_hash, "copyright": copyright,
                         "out_dir": str(out_dir), "settings": fp})

    if jobs:
        n = workers or settings.workers or os.cpu_count() or 1
        if n == 1 or len(jobs) == 1:
            done = map(render_photo, jobs)
        else:
            pool = ProcessPoolExecutor(max_workers=min(n, len(jobs)),
                                       mp_context=multiprocessing.get_context("forkserver"))
            done = pool.map(render_photo, jobs)
        try:
            for i, rec in enumerate(done, 1):
                result.records[rec["id"]] = rec
                result.rendered.append(rec["id"])
                result.warnings += rec["warnings"]
                if progress:
                    progress(i, len(jobs), rec["id"])
        finally:
            if n > 1 and len(jobs) > 1:
                pool.shutdown()

    # drop derivatives nothing references (removed photos, old keys)
    keep = {s[f]["file"] for r in result.records.values() for s in r["sizes"] for f in ("jpeg", "webp")}
    for f in out_dir.iterdir():
        if f.name not in keep:
            f.unlink()
            result.removed_files += 1

    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result.records, indent=1, sort_keys=True))
    os.replace(tmp, manifest_path)
    return result


def link_into(records: dict, cache_dir: Path, dest: Path) -> None:
    """Mirror the referenced derivatives into dest (hard links; copy fallback)."""
    src_dir = Path(cache_dir) / "images" / "files"
    dest.mkdir(parents=True, exist_ok=True)
    want = {s[f]["file"] for r in records.values() for s in r["sizes"] for f in ("jpeg", "webp")}
    for f in dest.iterdir():
        if f.name not in want:
            f.unlink()
    for name in want:
        d = dest / name
        if d.exists():
            continue
        try:
            os.link(src_dir / name, d)
        except OSError:
            import shutil
            shutil.copy2(src_dir / name, d)


def size_report(cache_dir: Path) -> str:
    """Average/total derivative bytes per width bucket and format."""
    try:
        records = json.loads((Path(cache_dir) / "images" / "manifest.json").read_text())
    except (OSError, json.JSONDecodeError):
        return "no image manifest yet; run a build first"
    buckets: dict[int, dict] = {}
    for r in records.values():
        for s in r["sizes"]:
            b = buckets.setdefault(s["w"], {"n": 0, "jpeg": 0, "webp": 0})
            b["n"] += 1
            b["jpeg"] += s["jpeg"]["bytes"]
            b["webp"] += s["webp"]["bytes"]
    lines = [f"{'width':>6} {'files':>6} {'avg JPEG':>10} {'avg WebP':>10} {'WebP/JPEG':>10}"]
    tj = tw = 0
    for w in sorted(buckets):
        b = buckets[w]
        tj, tw = tj + b["jpeg"], tw + b["webp"]
        lines.append(f"{w:>6} {b['n']:>6} {b['jpeg'] / b['n'] / 1024:>8.0f}KB "
                     f"{b['webp'] / b['n'] / 1024:>8.0f}KB {b['webp'] / b['jpeg']:>9.0%}")
    lqip = [len(r["lqip"]) for r in records.values()]
    lines.append(f"total: JPEG {tj / 2**20:.1f}MB, WebP {tw / 2**20:.1f}MB for {len(records)} photos")
    lines.append(f"inline placeholder: {min(lqip)}-{max(lqip)} bytes as data URI")
    return "\n".join(lines)
