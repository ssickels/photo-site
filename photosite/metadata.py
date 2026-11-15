"""Scan the publish folder and read metadata.

The publish folder is READ-ONLY: nothing in this module writes to it.

Metadata comes from ONE batched `exiftool -json` call covering only files
that are new or changed since the last build (cache keyed on size + mtime),
so a warm build doesn't start exiftool at all.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

JPEG_EXTS = {".jpg", ".jpeg"}

EXIFTOOL_TAGS = [
    "-XMP-dc:Title", "-IPTC:ObjectName",
    "-XMP-dc:Description", "-IPTC:Caption-Abstract",
    "-DateTimeOriginal",
    "-XMP-lr:HierarchicalSubject", "-XMP-dc:Subject", "-IPTC:Keywords",
    "-XMP-dc:Rights", "-IPTC:CopyrightNotice", "-IFD0:Copyright",
    "-ICC_Profile:ProfileDescription",
    "-File:ImageWidth", "-File:ImageHeight",
]
META_CACHE_VERSION = 1


@dataclass
class SourceFile:
    path: Path
    theme_folder: str
    stem: str
    size: int
    mtime_ns: int


@dataclass
class Metadata:
    title: str = ""
    caption: str = ""
    date: datetime | None = None
    date_source: str = ""          # "exif" | "filename" | "mtime"
    hierarchical: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    copyright: str = ""
    icc_description: str = ""
    width: int = 0
    height: int = 0


# ------------------------------------------------------------------ scanning
def scan_publish(publish_dir: Path) -> tuple[list[SourceFile], list[str]]:
    """Each top-level subfolder is a theme. Returns (files, warnings)."""
    publish_dir = Path(publish_dir).resolve()
    if not publish_dir.is_dir():
        raise FileNotFoundError(f"publish folder not found: {publish_dir}")
    files, warnings = [], []
    for theme_dir in sorted(p for p in publish_dir.iterdir() if p.is_dir()):
        if theme_dir.name.startswith("."):
            continue
        for p in sorted(theme_dir.rglob("*")):
            if p.name.startswith(".") or not p.is_file():
                continue
            if p.parent != theme_dir:
                warnings.append(f"ignoring nested file (collection set?): {p.relative_to(publish_dir)}")
                continue
            if p.suffix.lower() not in JPEG_EXTS:
                continue
            st = p.stat()
            files.append(SourceFile(p, theme_dir.name, p.stem, st.st_size, st.st_mtime_ns))
    loose = [p.name for p in publish_dir.iterdir()
             if p.is_file() and p.suffix.lower() in JPEG_EXTS]
    if loose:
        warnings.append(f"{len(loose)} JPEG(s) directly in the publish folder (not in a theme) ignored")
    return files, warnings


# ------------------------------------------------------- stat-keyed caches
class StatCache:
    """JSON cache of per-file values, valid while (size, mtime_ns) match."""

    def __init__(self, path: Path, version: int = 1):
        self.path, self.version = Path(path), version
        self.entries: dict = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if data.get("version") == version:
                    self.entries = data.get("files", {})
            except (json.JSONDecodeError, OSError):
                pass

    def get(self, src: SourceFile):
        e = self.entries.get(str(src.path))
        if e and e["size"] == src.size and e["mtime_ns"] == src.mtime_ns:
            return e["value"]
        return None

    def put(self, src: SourceFile, value) -> None:
        self.entries[str(src.path)] = {"size": src.size, "mtime_ns": src.mtime_ns, "value": value}

    def save(self, keep: set[str] | None = None) -> None:
        if keep is not None:
            self.entries = {k: v for k, v in self.entries.items() if k in keep}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": self.version, "files": self.entries}))
        os.replace(tmp, self.path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def image_data_hash(path: Path) -> str:
    """sha256 of a JPEG's compressed image data (from the first SOS marker on).

    Lightroom stamps every export with new timestamps and document IDs, so two
    exports of the same photo never match byte for byte; this ignores headers.
    Falls back to the whole file for anything that isn't a parseable JPEG.
    """
    data = Path(path).read_bytes()
    i = 2
    if data[:2] == b"\xff\xd8":
        while i + 4 <= len(data) and data[i] == 0xFF:
            marker = data[i + 1]
            if marker == 0xDA:
                return hashlib.sha256(data[i:]).hexdigest()
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return hashlib.sha256(data).hexdigest()


def file_hashes(files: list[SourceFile], cache_dir: Path) -> dict[str, str]:
    """sha256 per source path; only re-reads files whose size/mtime changed."""
    cache = StatCache(Path(cache_dir) / "hashes.json")
    out = {}
    for src in files:
        h = cache.get(src)
        if h is None:
            h = sha256_file(src.path)
            cache.put(src, h)
        out[str(src.path)] = h
    cache.save(keep=set(out))
    return out


# ------------------------------------------------------------------ exiftool
def run_exiftool(paths: list[Path]) -> dict[str, dict]:
    """One exiftool process for all paths. Returns {path: raw tag dict}."""
    if not paths:
        return {}
    with tempfile.NamedTemporaryFile("w", suffix=".args", delete=False, encoding="utf-8") as f:
        f.write("\n".join(str(p) for p in paths) + "\n")
        argfile = f.name
    try:
        proc = subprocess.run(
            ["exiftool", "-json", "-G1", "-charset", "iptc=UTF8", "-charset", "filename=UTF8",
             *EXIFTOOL_TAGS, "-@", argfile],
            capture_output=True, text=True, encoding="utf-8")
    finally:
        os.unlink(argfile)
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        raise RuntimeError(f"exiftool failed: {proc.stderr.strip()}")
    return {d["SourceFile"]: d for d in json.loads(proc.stdout)}


def read_raw_metadata(files: list[SourceFile], cache_dir: Path) -> tuple[dict[str, dict], int]:
    """Raw exiftool dicts per path, using the cache. Returns (raw, n_read)."""
    cache = StatCache(Path(cache_dir) / "metadata.json", META_CACHE_VERSION)
    out, todo = {}, []
    for src in files:
        v = cache.get(src)
        if v is None:
            todo.append(src)
        else:
            out[str(src.path)] = v
    fresh = run_exiftool([s.path for s in todo])
    for src in todo:
        raw = fresh.get(str(src.path), {})
        raw.pop("SourceFile", None)
        cache.put(src, raw)
        out[str(src.path)] = raw
    cache.save(keep=set(out))
    return out, len(todo)


# ------------------------------------------------------------------- parsing
def _first(raw: dict, *keys) -> str:
    for k in keys:
        v = raw.get(k)
        if isinstance(v, list):
            v = v[0] if v else None
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _list(raw: dict, *keys) -> list[str]:
    for k in keys:
        v = raw.get(k)
        if v in (None, "", []):
            continue
        return [str(x) for x in (v if isinstance(v, list) else [v])]
    return []


_FILENAME_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})")


def _parse_exif_date(s: str) -> datetime | None:
    try:
        return datetime.strptime(s[:19], "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def parse_metadata(raw: dict, src: SourceFile) -> Metadata:
    m = Metadata(
        title=_first(raw, "XMP-dc:Title", "IPTC:ObjectName"),
        caption=_first(raw, "XMP-dc:Description", "IPTC:Caption-Abstract"),
        hierarchical=_list(raw, "XMP-lr:HierarchicalSubject"),
        keywords=_list(raw, "XMP-dc:Subject", "IPTC:Keywords"),
        copyright=_first(raw, "XMP-dc:Rights", "IPTC:CopyrightNotice", "IFD0:Copyright"),
        icc_description=_first(raw, "ICC_Profile:ProfileDescription"),
        width=int(raw.get("File:ImageWidth") or 0),
        height=int(raw.get("File:ImageHeight") or 0),
    )
    dto = _first(raw, "ExifIFD:DateTimeOriginal", "XMP-exif:DateTimeOriginal",
                 "XMP-photoshop:DateCreated")
    m.date = _parse_exif_date(dto) if dto else None
    if m.date:
        m.date_source = "exif"
    elif (mt := _FILENAME_DATE.match(src.stem)):
        try:
            m.date, m.date_source = datetime(*map(int, mt.groups())), "filename"
        except ValueError:
            pass
    if m.date is None:
        m.date, m.date_source = datetime.fromtimestamp(src.mtime_ns / 1e9), "mtime"
    return m


def location_paths(hierarchical: list[str], root: str) -> list[tuple[str, ...]]:
    """Deepest place paths under `root`, lowercased, root stripped.

    Lightroom may write ancestor entries too ("Places", "Places|usa", ...);
    any path that is a prefix of another is dropped.
    """
    root = root.lower()
    paths = set()
    for h in hierarchical:
        segs = tuple(s.strip().lower() for s in h.split("|") if s.strip())
        if len(segs) > 1 and segs[0] == root:
            paths.add(segs[1:])
    return sorted(p for p in paths
                  if not any(q != p and q[:len(p)] == p for q in paths))
