from datetime import datetime

from photosite.metadata import location_paths, parse_metadata, read_raw_metadata, scan_publish


def _meta(scanned, stem, folder=None):
    files, raw, _ = scanned
    src = next(f for f in files if f.stem == stem and (folder is None or f.theme_folder == folder))
    return parse_metadata(raw[str(src.path)], src)


def test_scan_finds_theme_folders(publish_dir):
    files, warnings = scan_publish(publish_dir)
    assert len(files) == 15
    assert {f.theme_folder for f in files} == {
        "Landscapes", "Wildlife", "Plants and Flowers", "The Built Environment"}
    assert warnings == []


def test_xmp_title_and_caption_preferred(scanned):
    m = _meta(scanned, "20170303-DSC09999")
    assert m.title == "Cadillac Mountain panorama"
    assert m.caption == "Lowercase root keyword."
    assert m.date == datetime(2017, 3, 3, 7, 0) and m.date_source == "exif"


def test_iptc_fallback(scanned):
    m = _meta(scanned, "20220510-DSC00412")
    assert m.title == "Pont Neuf at dusk"
    assert m.caption == "IPTC-only title and caption."
    assert m.copyright == "© Steve Sickels"


def test_no_metadata_falls_back(scanned):
    m = _meta(scanned, "20200101-IMG_0001")
    assert m.title == "" and m.caption == "" and m.hierarchical == []
    assert m.date == datetime(2020, 1, 1) and m.date_source == "filename"
    assert (m.width, m.height) == (1500, 1000)


def test_keywords_and_rights(scanned):
    m = _meta(scanned, "20240615-DSC01234", "Landscapes")
    assert "fog" in m.keywords
    assert m.copyright == "© Steve Sickels"
    assert "Nature|water" in m.hierarchical


def test_location_paths_deepest_only_and_root_filter():
    h = ["Places", "Places|usa", "Places|usa|new york", "Places|usa|new york|new york city",
         "Nature|water"]
    assert location_paths(h, "Places") == [("usa", "new york", "new york city")]


def test_location_paths_root_case_insensitive_and_multiple():
    assert location_paths(["places|usa|maine|mt desert island"], "Places") == [
        ("usa", "maine", "mt desert island")]
    two = location_paths(["Places|europe|uk|skye", "Places|europe|uk|raasay"], "places")
    assert two == [("europe", "uk", "raasay"), ("europe", "uk", "skye")]


def test_location_paths_other_root():
    assert location_paths(["Locations|usa|maine"], "Places") == []
    assert location_paths(["Locations|usa|maine"], "Locations") == [("usa", "maine")]


def test_metadata_cache_skips_exiftool_when_unchanged(config, publish_dir):
    files, _ = scan_publish(publish_dir)
    _, n1 = read_raw_metadata(files, config.cache_dir)
    _, n2 = read_raw_metadata(files, config.cache_dir)
    assert n1 == 15 and n2 == 0


def test_exiftool_is_called_once_per_batch(config, publish_dir, monkeypatch):
    import photosite.metadata as md
    calls = []
    real = md.subprocess.run
    monkeypatch.setattr(md.subprocess, "run", lambda *a, **k: calls.append(a) or real(*a, **k))
    files, _ = scan_publish(publish_dir)
    read_raw_metadata(files, config.cache_dir)
    assert len(calls) == 1



def test_image_data_hash_ignores_export_stamps(publish_dir, tmp_path):
    import shutil, subprocess
    from photosite.metadata import image_data_hash, sha256_file
    src = next(publish_dir.rglob("*.jpg"))
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    shutil.copy(src, a); shutil.copy(src, b)
    subprocess.run(["exiftool", "-q", "-overwrite_original", "-XMP-xmp:ModifyDate=2030:01:01 00:00:00",
                    "-XMP-xmpMM:InstanceID=xmp.iid:something-else", str(b)], check=True)
    assert sha256_file(a) != sha256_file(b)
    assert image_data_hash(a) == image_data_hash(b)
