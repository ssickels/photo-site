import pytest

from photosite.config import ConfigError
from photosite.model import build_catalog, label, resolve_node, slugify


def by_id(cat, stem):
    return cat.photos[slugify(stem)]


# ------------------------------------------------------------ helpers
def test_slugify():
    assert slugify("Plants and Flowers") == "plants-and-flowers"
    assert slugify("20240615-DSC01234Copy 1") == "20240615-dsc01234copy-1"
    assert slugify("Île-de-France") == "ile-de-france"


@pytest.mark.parametrize("seg,expected", [
    ("scotland", "Scotland"),
    ("mt desert island", "Mt Desert Island"),
    ("isle of skye", "Isle of Skye"),
    ("united kingdom", "United Kingdom"),
    ("usa", "USA"),
    ("the hague", "The Hague"),
    ("aix-en-provence", "Aix-en-Provence"),
])
def test_label(seg, expected):
    assert label(seg, {"usa": "USA"}) == expected


# ------------------------------------------- themes, membership, dedupe
def test_photo_count_and_theme_counts(catalog):
    assert len(catalog.photos) == 13
    assert [(t.name, len(t.photos)) for t in catalog.themes] == [
        ("Landscapes", 6), ("Wildlife", 3), ("Plants and Flowers", 3), ("The Built Environment", 3)]


def test_photo_in_two_themes_is_one_photo(catalog):
    p = by_id(catalog, "20240615-DSC01234")
    assert [t.folder for t in p.themes] == ["Landscapes", "Plants and Flowers"]
    assert p.canonical_theme.slug == "landscapes"
    assert sum(p is q for t in catalog.themes for q in t.photos) == 2


def test_duplicate_stem_uses_newest_copy_and_reports(catalog):
    p = by_id(catalog, "20230904-DSC05620")
    assert p.source.theme_folder == "Wildlife"         # newer mtime
    assert any("20230904-DSC05620" in m and "differs" in m for m in catalog.info)
    # identical copies don't produce a message
    assert not any("DSC01234:" in m for m in catalog.info)


def test_virtual_copy_is_its_own_photo(catalog):
    assert "20240615-dsc01234copy-1" in catalog.photos
    assert by_id(catalog, "20240615-DSC01234Copy 1").stem == "20240615-DSC01234Copy 1"


def test_hidden_theme_drops_photos_only_in_it(config, scanned):
    config.themes["Plants and Flowers"] = {"hidden": True}
    cat = build_catalog(config, *scanned)
    assert "20200101-img-0001" not in cat.photos
    assert "20180505-dsc04444" not in cat.photos
    p = cat.photos["20240615-dsc01234"]
    assert [t.folder for t in p.themes] == ["Landscapes"]
    assert "Plants and Flowers" not in [t.folder for t in cat.themes]


def test_theme_order_config_first_then_alphabetical(config, scanned):
    config.themes = {"Wildlife": {"name": "Animals", "slug": "animals"}}
    cat = build_catalog(config, *scanned)
    assert [t.name for t in cat.themes] == ["Animals", "Landscapes", "Plants and Flowers",
                                             "The Built Environment"]
    assert cat.themes[0].slug == "animals"


def test_theme_sorts(config, scanned):
    stems = lambda t: [p.stem for p in t.photos]  # noqa: E731
    cat = build_catalog(config, *scanned)
    land = cat.themes[0]
    assert stems(land)[0] == "20240615-DSC01234"              # newest first by default
    config.themes["Landscapes"] = {"sort": "date_asc"}
    assert stems(build_catalog(config, *scanned).themes[0])[0] == "20170303-DSC09999"
    config.themes["Landscapes"] = {"sort": "filename"}
    assert stems(build_catalog(config, *scanned).themes[0]) == sorted(stems(land), key=str.lower)
    config.themes["Landscapes"] = {"sort": ["20210720-DSC08800", "nope"], "cover": "20230902-DSC05501"}
    cat = build_catalog(config, *scanned)
    assert stems(cat.themes[0])[0] == "20210720-DSC08800"
    assert stems(cat.themes[0])[1] == "20240615-DSC01234"
    assert cat.themes[0].cover.stem == "20230902-DSC05501"
    assert any("nope" in w for w in cat.warnings)


def test_reserved_and_duplicate_theme_slugs(config, scanned):
    config.themes["Wildlife"] = {"slug": "locations"}
    with pytest.raises(ConfigError, match="reserved"):
        build_catalog(config, *scanned)
    config.themes["Wildlife"] = {"slug": "landscapes"}
    with pytest.raises(ConfigError, match="both have slug"):
        build_catalog(config, *scanned)


def test_hero_defaults_to_newest(catalog, config, scanned):
    assert catalog.hero.stem in ("20240615-DSC01234", "20240615-DSC01234Copy 1")
    config.home = {"hero": "20230902-DSC05501"}
    assert build_catalog(config, *scanned).hero.stem == "20230902-DSC05501"


# -------------------------------------------------------- location tree
def node(cat, *path):
    n = cat.tree
    for s in path:
        n = n.children[s]
    return n


def test_location_tree_counts(catalog):
    assert len(node(catalog, "europe", "united kingdom", "scotland").direct) == 1
    assert len(node(catalog, "europe", "united kingdom", "scotland").all_photos) == 3
    assert len(node(catalog, "europe").all_photos) == 5
    assert len(node(catalog, "usa").all_photos) == 6
    assert len(node(catalog, "usa", "maine").direct) == 1
    assert len(node(catalog, "usa", "maine").all_photos) == 4
    assert node(catalog, "usa", "maine", "mt desert island").name == "Mt Desert Island"


def test_photo_with_two_places_counted_once_per_ancestor(catalog):
    skye = node(catalog, "europe", "united kingdom", "scotland", "isle of skye")
    raasay = node(catalog, "europe", "united kingdom", "scotland", "isle of raasay")
    assert "20230905-dsc05700" in {p.id for p in skye.direct} & {p.id for p in raasay.direct}
    ids = [p.id for p in node(catalog, "europe").all_photos]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------- location galleries
def test_galleries_in_config_order_with_descendants(catalog):
    assert [g.name for g in catalog.galleries] == [
        "Europe", "Scotland", "Maine", "Acadia / Mount Desert Island", "Georgia"]
    europe, scotland = catalog.galleries[0], catalog.galleries[1]
    assert {p.id for p in scotland.photos} <= {p.id for p in europe.photos}
    assert len(scotland.photos) == 3 and len(europe.photos) == 5
    assert scotland.slug == "scotland"
    assert scotland.context == ["Europe", "United Kingdom"]
    assert catalog.galleries[3].slug == "acadia-mount-desert-island"


def test_resolve_node_forms(catalog, config):
    root = config.location_root
    t = catalog.tree
    assert resolve_node("maine", t, root).path == ("usa", "maine")
    assert resolve_node("Places|usa|maine", t, root).path == ("usa", "maine")
    assert resolve_node("United Kingdom|Scotland", t, root).path == ("europe", "united kingdom", "scotland")
    assert resolve_node("europe", t, root).path == ("europe",)
    assert resolve_node("narnia", t, root) is None


def test_ambiguous_shorthand_lists_matches(catalog, config):
    with pytest.raises(ConfigError) as e:
        resolve_node("georgia", catalog.tree, config.location_root)
    msg = str(e.value)
    assert "europe|georgia" in msg and "usa|georgia" in msg


def test_ambiguous_gallery_fails_build(config, scanned):
    config.location_galleries = [{"node": "georgia"}]
    with pytest.raises(ConfigError, match="ambiguous"):
        build_catalog(config, *scanned)


def test_zero_match_gallery_warns_and_is_skipped(config, scanned):
    config.location_galleries = [{"node": "narnia"}, {"node": "france"}]
    cat = build_catalog(config, *scanned)
    assert [g.name for g in cat.galleries] == ["France"]
    assert any("narnia" in w for w in cat.warnings)


def test_breadcrumbs_link_only_configured_nodes(catalog):
    trail, = catalog.breadcrumbs(by_id(catalog, "20240615-DSC01234"))
    assert [name for name, _ in trail] == ["USA", "Maine", "Mt Desert Island"]
    assert [g.name if g else None for _, g in trail] == [None, "Maine", "Acadia / Mount Desert Island"]
    assert len(catalog.breadcrumbs(by_id(catalog, "20230905-DSC05700"))) == 2
    assert catalog.breadcrumbs(by_id(catalog, "20200101-IMG_0001")) == []


def test_label_initials():
    from photosite.model import label
    assert label("washington d.c.", {}) == "Washington D.C."
    assert label("c&o canal", {}) == "C&O Canal"
    assert label("lochs & bays", {}) == "Lochs & Bays"


def test_assign_ids_strips_copy_names_after_tilde():
    from photosite.model import assign_ids
    ids = assign_ids(["20221001-_DSC9119-Edit~Copyright 2022",       # copy alone: plain id
                      "20120719-_MG_9716~", "20120719-_MG_9716~Copy 1",  # original + copy
                      "20140326-_MG_6955~Copy 2", "20140326-_MG_6955~Copy 3",  # two copies
                      "20160805-DSC00606Copy 1"])                      # old style, no ~
    assert ids == {
        "20221001-_DSC9119-Edit~Copyright 2022": "20221001-dsc9119-edit",
        "20120719-_MG_9716~": "20120719-mg-9716",
        "20120719-_MG_9716~Copy 1": "20120719-mg-9716-copy-1",
        "20140326-_MG_6955~Copy 2": "20140326-mg-6955-copy-2",
        "20140326-_MG_6955~Copy 3": "20140326-mg-6955-copy-3",
        "20160805-DSC00606Copy 1": "20160805-dsc00606copy-1",
    }


# ------------------------------------------------------------ cover keywords
def _tag(scanned, stem, *keywords):
    """A copy of the scanned data with extra hierarchical keywords on one photo."""
    files, raw, hashes = scanned
    raw = {k: dict(v) for k, v in raw.items()}
    for f in files:
        if f.stem == stem:
            r = raw[str(f.path)]
            old = r.get("XMP-lr:HierarchicalSubject") or []
            r["XMP-lr:HierarchicalSubject"] = ([old] if isinstance(old, str) else list(old)) + list(keywords)
    return files, raw, hashes


def test_cover_keywords_pick_theme_location_and_home_covers(config, scanned):
    # DSC05700 is in Landscapes and under scotland; not the newest in either
    data = _tag(scanned, "20230905-DSC05700", "covers|landscapes", "Covers|Scotland", "covers|home")
    cat = build_catalog(config, *data)
    land = next(t for t in cat.themes if t.folder == "Landscapes")
    scot = next(g for g in cat.galleries if g.node.name == "Scotland")
    assert land.cover.stem == scot.cover.stem == cat.hero.stem == "20230905-DSC05700"
    assert not [w for w in cat.warnings if "covers" in w.lower()]


def test_cover_keyword_warnings(config, scanned):
    data = _tag(scanned, "20230905-DSC05700", "covers|wildlife", "covers|nowhere")
    cat = build_catalog(config, *data)
    wild = next(t for t in cat.themes if t.folder == "Wildlife")
    assert wild.cover.stem != "20230905-DSC05700"              # not in Wildlife: ignored
    assert any("covers|wildlife" in w.lower() and "isn't in it" in w for w in cat.warnings)
    assert any("covers|nowhere" in w.lower() for w in cat.warnings)


def test_site_yaml_cover_beats_keyword(config, scanned):
    data = _tag(scanned, "20230905-DSC05700", "covers|landscapes")
    config.themes["Landscapes"] = {"cover": "20230902-DSC05501"}
    land = next(t for t in build_catalog(config, *data).themes if t.folder == "Landscapes")
    assert land.cover.stem == "20230902-DSC05501"
