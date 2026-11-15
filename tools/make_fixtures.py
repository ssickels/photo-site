#!/usr/bin/env python3
"""Generate a synthetic Lightroom-style publish folder for tests.

    python tools/make_fixtures.py [OUTDIR]     (default: tests/fixtures/publish)

Gradients + mild noise at assorted aspect ratios, metadata written with
exiftool the way Lightroom writes it. Deterministic (seeded), so file sizes
are repeatable. Covers: titles/captions (XMP and IPTC-only), place keywords
at different depths (with and without ancestor entries, mixed-case root),
two place paths on one photo, one photo in two themes (identical), one stem
in two themes with different pixels (stale copy), a ProPhoto (non-sRGB)
profile, GPS in a source, a virtual-copy filename with a space, an ambiguous
place name ("georgia"), and one photo with no metadata at all.
"""
from __future__ import annotations

import io
import os
import random
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageCms, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "tests" / "fixtures" / "publish"

L, W, P, B = "Landscapes", "Wildlife", "Plants and Flowers", "The Built Environment"

# stem, size, [(theme, mtime-offset-days, seed)], metadata, profile
PHOTOS = [
    dict(stem="20240615-DSC01234", size=(3000, 2000), copies=[(L, 0, 1), (P, 0, 1)],
         meta={"XMP-dc:Title": "Morning fog, Jordan Pond",
               "XMP-dc:Description": "Fog lifting off the water just after sunrise.",
               "EXIF:DateTimeOriginal": "2024:06:15 06:12:00",
               "XMP-lr:HierarchicalSubject": ["Places|usa|maine|mt desert island", "Nature|water"],
               "XMP-dc:Subject": ["mt desert island", "maine", "usa", "water", "fog"],
               "XMP-dc:Rights": "© Steve Sickels",
               "EXIF:Copyright": "© Steve Sickels",
               "GPS": True}),
    dict(stem="20230902-DSC05501", size=(3000, 1000), copies=[(L, 0, 2)],
         meta={"XMP-dc:Title": "Quiraing ridge",
               "EXIF:DateTimeOriginal": "2023:09:02 17:40:10",
               "XMP-lr:HierarchicalSubject": ["Places|europe|united kingdom|scotland|isle of skye"]}),
    dict(stem="20230904-DSC05620", size=(2000, 3000), copies=[(W, 0, 3), (L, -5, 33)],
         meta={"XMP-dc:Title": "Red deer stag",
               "XMP-dc:Description": "Rutting season, Glen Etive.",
               "EXIF:DateTimeOriginal": "2023:09:04 08:01:00",
               "XMP-lr:HierarchicalSubject": ["Places|europe|united kingdom|scotland"]}),
    dict(stem="20220510-DSC00412", size=(2400, 2400), copies=[(B, 0, 4)],
         meta={"IPTC:ObjectName": "Pont Neuf at dusk",
               "IPTC:Caption-Abstract": "IPTC-only title and caption.",
               "EXIF:DateTimeOriginal": "2022:05:10 21:15:00",
               "XMP-lr:HierarchicalSubject": ["Places|europe|france|paris"],
               "IPTC:CopyrightNotice": "© Steve Sickels"}),
    dict(stem="20210720-DSC08800", size=(3000, 2000), copies=[(L, 0, 5)], profile="prophoto",
         meta={"XMP-dc:Title": "Live oaks",
               "EXIF:DateTimeOriginal": "2021:07:20 10:00:00",
               "XMP-lr:HierarchicalSubject": ["Places|usa|georgia|savannah"]}),
    dict(stem="20200101-IMG_0001", size=(1500, 1000), copies=[(P, 0, 6)], profile=None, meta=None),
    dict(stem="20190812-DSC03333", size=(3000, 2000), copies=[(B, 0, 7)],
         meta={"XMP-dc:Title": "Old town balconies",
               "EXIF:DateTimeOriginal": "2019:08:12 12:30:00",
               "XMP-lr:HierarchicalSubject": ["Places|europe|georgia|tbilisi"]}),
    dict(stem="20240101-DSC00007", size=(2250, 3000), copies=[(W, 0, 8)],
         meta={"XMP-dc:Title": "Snowy owl",
               "EXIF:DateTimeOriginal": "2024:01:01 15:45:00",
               "XMP-lr:HierarchicalSubject": ["Places|usa|maine"]}),
    dict(stem="20180505-DSC04444", size=(3000, 2000), copies=[(P, 0, 9)],
         meta={"XMP-dc:Title": "Tulips",
               "EXIF:DateTimeOriginal": "2018:05:05 09:00:00",
               "XMP-dc:Subject": ["tulip", "flower"]}),
    dict(stem="20221111-DSC06060", size=(3000, 1688), copies=[(B, 0, 10)],
         meta={"XMP-dc:Title": "Chrysler Building",
               "EXIF:DateTimeOriginal": "2022:11:11 16:20:00",
               "XMP-lr:HierarchicalSubject": ["Places", "Places|usa", "Places|usa|new york",
                                              "Places|usa|new york|new york city"]}),
    dict(stem="20230905-DSC05700", size=(3000, 2000), copies=[(L, 0, 11)],
         meta={"XMP-dc:Title": "Raasay from Skye",
               "EXIF:DateTimeOriginal": "2023:09:05 19:05:00",
               "XMP-lr:HierarchicalSubject": ["Places|europe|united kingdom|scotland|isle of skye",
                                              "Places|europe|united kingdom|scotland|isle of raasay"]}),
    dict(stem="20170303-DSC09999", size=(3000, 750), copies=[(L, 0, 12)],
         meta={"XMP-dc:Title": "Cadillac Mountain panorama",
               "IPTC:ObjectName": "IPTC title should lose to XMP",
               "XMP-dc:Description": "Lowercase root keyword.",
               "EXIF:DateTimeOriginal": "2017:03:03 07:00:00",
               "XMP-lr:HierarchicalSubject": ["places|usa|maine|mt desert island"]}),
    dict(stem="20240615-DSC01234Copy 1", size=(2000, 2000), copies=[(W, 0, 13)],
         meta={"XMP-dc:Title": "Morning fog (square crop)",
               "EXIF:DateTimeOriginal": "2024:06:15 06:12:00",
               "XMP-lr:HierarchicalSubject": ["Places|usa|maine|mt desert island"]}),
]

BASE_MTIME = 1_730_000_000  # fixed so builds are reproducible


# --------------------------------------------------------------- ICC profile
def _s15(v: float) -> bytes:
    return struct.pack(">i", round(v * 65536))


def matrix_profile(desc: str, red, green, blue, white, gamma: float) -> bytes:
    """Minimal ICC v2 RGB matrix/TRC display profile."""
    def xyz(v):
        return b"XYZ " + b"\0" * 4 + b"".join(_s15(c) for c in v)

    ascii_desc = desc.encode("ascii") + b"\0"
    tags = [
        (b"desc", b"desc" + b"\0" * 4 + struct.pack(">I", len(ascii_desc)) + ascii_desc
         + b"\0" * 8 + b"\0" * 3 + b"\0" * 67),
        (b"cprt", b"text" + b"\0" * 4 + b"Public domain test profile\0"),
        (b"wtpt", xyz(white)),
        (b"rXYZ", xyz(red)), (b"gXYZ", xyz(green)), (b"bXYZ", xyz(blue)),
        (b"rTRC", b"curv" + b"\0" * 4 + struct.pack(">IH", 1, round(gamma * 256)) + b"\0\0"),
    ]
    tags += [(b"gTRC", tags[-1][1]), (b"bTRC", tags[-1][1])]

    table_len = 4 + 12 * len(tags)
    offset = 128 + table_len
    table, data = [struct.pack(">I", len(tags))], b""
    for sig, body in tags:
        while len(body) % 4:
            body += b"\0"
        table.append(sig + struct.pack(">II", offset + len(data), len(body)))
        data += body
    size = offset + len(data)
    header = (struct.pack(">I", size) + b"lcms" + bytes([2, 0x10, 0, 0]) + b"mntr"
              + b"RGB " + b"XYZ " + b"\0" * 12 + b"acsp" + b"\0" * 24
              + struct.pack(">I", 0) + b"".join(_s15(c) for c in (0.9642, 1.0, 0.8249))
              + b"\0" * 48)
    assert len(header) == 128
    return header + b"".join(table) + data


PROPHOTO_ICC = matrix_profile(
    "ProPhoto RGB (test fixture)",
    red=(0.7977, 0.2880, 0.0000), green=(0.1352, 0.7119, 0.0000),
    blue=(0.0313, 0.0001, 0.8249), white=(0.9642, 1.0, 0.8249), gamma=1.8)
SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


# -------------------------------------------------------------------- pixels
def make_image(size: tuple[int, int], seed: int) -> Image.Image:
    rnd = random.Random(seed)
    w, h = size
    def grad(angle):
        g = Image.linear_gradient("L").rotate(angle, resample=Image.BICUBIC, expand=False)
        return g.resize((w, h), Image.BICUBIC)
    r, g, b = (grad(rnd.choice([0, 45, 90, 135, 180, 270])) for _ in range(3))
    img = Image.merge("RGB", (r, g, b))
    tint = Image.new("RGB", (w, h), tuple(rnd.randrange(40, 220) for _ in range(3)))
    img = Image.blend(img, tint, 0.45)
    # photo-ish texture: blurred random noise, mixed in lightly
    nw, nh = max(1, w // 2), max(1, h // 2)
    noise = Image.frombytes("L", (nw, nh), rnd.randbytes(nw * nh))
    noise = noise.filter(ImageFilter.GaussianBlur(1.2)).resize((w, h), Image.BILINEAR)
    return Image.blend(img, Image.merge("RGB", (noise, noise, noise)), 0.12)


def write_metadata(path: Path, meta: dict) -> None:
    args = ["exiftool", "-q", "-overwrite_original", "-charset", "iptc=UTF8",
            "-IPTC:CodedCharacterSet=UTF8"]
    for tag, value in meta.items():
        if tag == "GPS":
            args += ["-GPSLatitude=44.3206", "-GPSLatitudeRef=N",
                     "-GPSLongitude=68.2539", "-GPSLongitudeRef=W"]
        elif isinstance(value, list):
            args += [f"-{tag}={v}" for v in value]
        else:
            args.append(f"-{tag}={value}")
    subprocess.run(args + [str(path)], check=True)


def generate(out: Path) -> Path:
    if out.exists():
        shutil.rmtree(out)
    for spec in PHOTOS:
        profile = spec.get("profile", "srgb")
        for theme, days, seed in spec["copies"]:
            folder = out / theme
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{spec['stem']}.jpg"
            img = make_image(spec["size"], seed)
            kw = {"quality": 90}
            if profile == "srgb":
                kw["icc_profile"] = SRGB_ICC
            elif profile == "prophoto":
                kw["icc_profile"] = PROPHOTO_ICC
            buf = io.BytesIO()
            img.save(buf, "JPEG", **kw)
            path.write_bytes(buf.getvalue())
            if spec["meta"]:
                write_metadata(path, spec["meta"])
            t = BASE_MTIME + days * 86400
            os.utime(path, (t, t))
    return out


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    generate(out)
    n = sum(1 for _ in out.rglob("*.jpg"))
    print(f"wrote {n} files to {out}")
