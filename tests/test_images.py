import io
import json
import os
import subprocess

from PIL import Image, ImageCms

from photosite.config import load_config
from photosite.images import target_widths
from photosite.pipeline import build
from tests.conftest import TEST_CONFIG

import make_fixtures


def files_dir(cfg):
    return cfg.cache_dir / "images" / "files"


def test_target_widths_never_upscale():
    W = [480, 960, 1600, 2400]
    assert target_widths(3000, W) == W
    assert target_widths(2400, W) == W
    assert target_widths(2000, W) == [480, 960, 1600, 2000]     # portrait: own width on top
    assert target_widths(1500, W) == [480, 960, 1500]
    assert target_widths(300, W) == [300]


def test_derivatives_sizes_and_names(config):
    res = build(config)
    rec = res.images.records["20200101-img-0001"]                  # 1500px source
    assert [s["w"] for s in rec["sizes"]] == [480, 960, 1500]
    pano = res.images.records["20170303-dsc09999"]                 # 3000x750
    assert [(s["w"], s["h"]) for s in pano["sizes"]][-1] == (2400, 600)
    for s in pano["sizes"]:
        for fmt in ("jpeg", "webp"):
            name = s[fmt]["file"]
            assert name.startswith(f"20170303-dsc09999.{s['w']}.{pano['key']}.")
            with Image.open(files_dir(config) / name) as im:
                assert im.size == (s["w"], s["h"])
    # also mirrored into dist/<target>/img
    assert (config.output_dir / "production" / "img" / pano["sizes"][0]["webp"]["file"]).exists()
    assert len(rec["lqip"]) <= 1024 and rec["color"].startswith("#")


def test_gps_stripped_copyright_kept(config):
    res = build(config)
    out = subprocess.run(["exiftool", "-json", "-G1", "-a", "-r", str(files_dir(config))],
                         capture_output=True, text=True, check=True)
    tags = json.loads(out.stdout)
    assert len(tags) == sum(len(r["sizes"]) * 2 for r in res.images.records.values())
    for t in tags:
        groups = {k.split(":")[0] for k in t if ":" in k}
        assert not any(k.startswith("GPS") or ":GPS" in k for k in t), t["SourceFile"]
        assert not groups & {"XMP-dc", "XMP-lr", "IPTC", "XMP-exif"}, t["SourceFile"]
        assert "IFD0:Copyright" in t, t["SourceFile"]
    by_file = {os.path.basename(t["SourceFile"]): t for t in tags}
    fog = res.images.records["20240615-dsc01234"]["sizes"][0]
    assert by_file[fog["jpeg"]["file"]]["IFD0:Copyright"] == "© Steve Sickels"
    nometa = res.images.records["20200101-img-0001"]["sizes"][0]
    assert by_file[nometa["webp"]["file"]]["IFD0:Copyright"] == "© Test"   # site default


def test_non_srgb_converted_with_warning(config):
    res = build(config)
    rec = res.images.records["20210720-dsc08800"]
    assert rec["color_note"].startswith("converted from ProPhoto")
    assert any("20210720-dsc08800" in w and "not sRGB" in w for w in res.images.warnings)
    with Image.open(files_dir(config) / rec["sizes"][0]["jpeg"]["file"]) as im:
        prof = ImageCms.ImageCmsProfile(io.BytesIO(im.info["icc_profile"]))
        assert "sRGB" in ImageCms.getProfileDescription(prof)
    with Image.open(files_dir(config) / rec["sizes"][0]["webp"]["file"]) as im:
        assert im.info.get("icc_profile")


def _cfg(publish, tmp_path, **images):
    cfg = load_config(TEST_CONFIG, publish=publish, output=tmp_path / "dist", cache=tmp_path / "cache")
    for k, v in images.items():
        setattr(cfg.images, k, v)
    return cfg


def test_cache_rebuilds_only_changed_photo(mutable_publish, tmp_path):
    cfg = _cfg(mutable_publish, tmp_path, widths=[200, 400])
    first = build(cfg).images
    assert len(first.rendered) == 13

    warm = build(cfg)
    assert warm.images.rendered == [] and warm.images.reused == 13
    assert warm.exiftool_reads == 0

    # touching a file (new mtime, same bytes) must not re-render
    p = mutable_publish / "Wildlife" / "20240101-DSC00007.jpg"
    os.utime(p, (2_000_000_000, 2_000_000_000))
    assert build(cfg).images.rendered == []

    # re-publish one photo with new pixels
    old_files = {s[f]["file"] for s in first.records["20240101-dsc00007"]["sizes"] for f in ("jpeg", "webp")}
    make_fixtures.make_image((2250, 3000), seed=999).save(p, "JPEG", quality=90)
    os.utime(p, (2_000_000_100, 2_000_000_100))
    res = build(cfg).images
    assert res.rendered == ["20240101-dsc00007"]
    assert res.reused == 12
    remaining = {f.name for f in files_dir(cfg).iterdir()}
    assert not old_files & remaining
    assert res.removed_files == len(old_files)


def test_settings_change_rebuilds_all(mutable_publish, tmp_path):
    cfg = _cfg(mutable_publish, tmp_path, widths=[200])
    build(cfg)
    cfg.images.jpeg_quality = 70
    assert len(build(cfg).images.rendered) == 13
    cfg.images.workers = 2                       # not a rendering setting
    assert build(cfg).images.rendered == []


def test_removed_source_drops_derivatives(mutable_publish, tmp_path):
    cfg = _cfg(mutable_publish, tmp_path, widths=[200])
    first = build(cfg).images
    gone = {s[f]["file"] for s in first.records["20180505-dsc04444"]["sizes"] for f in ("jpeg", "webp")}
    (mutable_publish / "Plants and Flowers" / "20180505-DSC04444.jpg").unlink()
    res = build(cfg)
    assert "20180505-dsc04444" not in res.images.records
    assert not gone & {f.name for f in files_dir(cfg).iterdir()}
    assert not gone & {f.name for f in (cfg.output_dir / "production" / "img").iterdir()}


def test_publish_folder_untouched(publish_dir, config):
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in publish_dir.rglob("*")}
    build(config)
    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in publish_dir.rglob("*")}
    assert before == after
