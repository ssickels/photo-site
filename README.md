# photo-site

Static photography site for stevesickels.com, built from a Lightroom Classic
**Hard Drive publish service** folder. Lightroom is the single source of truth;
`build.py` turns the publish folder into `dist/<target>/`, which gets deployed to
the TCH shared host.

The workflow: drag photos into a theme collection in Lightroom, click Publish,
then run `make deploy`.

## Setup (in the OrbStack VM)

```bash
sudo apt install libimage-exiftool-perl python3-venv
```

```bash
make venv
```

```bash
make test
```

## Commands

| Command | What it does |
|---|---|
| `make build` | Build `dist/production` from the publish folder |
| `make staging` | Build `dist/staging` (noindex, disallow-all robots.txt) |
| `make locations` | Print the place-keyword tree with photo counts (for picking `location_galleries`) |
| `make sizes` | Derivative file sizes per width and format |
| `make test` | Run the test suite against the synthetic fixture |
| `make fixture-site` | Build the fixture site (no real photos needed) |
| `make serve-fixture` | Serve the fixture site at http://localhost:8000 |
| `make serve` | Serve `dist/production` at http://localhost:8000 |

Paths can be overridden: `./build.py --publish /some/folder --out /tmp/out`.

## How it works

- **Themes** are the top-level folders of the publish folder, one per publish
  collection. Names, order, slugs, descriptions, covers, sort and hiding are set
  in `site.yaml`.
- **Photo identity is the filename stem.** The same stem in several theme
  folders is one photo in several themes. The newest copy is used, and an older
  copy whose content differs is reported as an `info:` line, meaning a
  collection still needs re-publishing.
- **Locations** come from hierarchical keywords under `location_root`
  (`Places|usa|maine|...`). `location_galleries` in `site.yaml` is a curated,
  ordered, flat list of tree nodes at any depth. A gallery includes every photo
  at that node or below it.
- **Images:** for each photo, WebP and JPEG at 480/960/1600/2400 px wide. Sizes
  are never upscaled; a source narrower than 2400 (such as a portrait) gets its
  own width as the top size. Output is converted to sRGB (with a warning if the
  source wasn't sRGB) and keeps only the EXIF Copyright tag; GPS is never written.
  Filenames carry a hash of source + settings, so browsers can cache them forever.
- **Incremental:**
  - Metadata (exiftool, one batched call) and file hashes are cached by size and modified time.
  - Derivatives are cached by source hash + settings.
  - An unchanged rebuild doesn't run exiftool or decode any image.
- **Pages:** Jinja2 templates in `templates/`, one stylesheet (`static/css/site.css`,
  all colors, fonts and spacing as custom properties at the top), and two small
  scripts: `gallery.js` lays out justified rows (without JS, a CSS flex layout
  is the fallback) and `photo.js` handles ← → Esc, swipe and prefetching the
  next photo. About and Contact are Markdown files in `content/`.
- **Logo and favicons:** the header logo (`static/img/logo.png`, plus
  `logo-dark.png` for dark mode) and the favicons (`static/favicon.svg`,
  `static/root/favicon.ico`, `static/root/apple-touch-icon.png`) are generated
  from the artwork in `logos/` by `tools/make_logos.py`. Re-run it if the logo
  changes; the generated files are what the site uses.
- **Covers:** the photo on each theme and location card (and the home page) is
  the one tagged `Covers|<name>` in Lightroom, e.g. `Covers|Landscapes`,
  `Covers|Scotland`, `Covers|Home`; otherwise the newest. A `cover:` in
  `site.yaml` overrides the keyword.
- The publish folder is **read-only** to this code.

`.cache/` holds the derivatives and caches; `dist/` holds the builds. Both are
git-ignored and can be deleted at any time; deleting `.cache/` means the next
build re-renders every image.

## Lightroom setup

**Publish Services → Hard Drive → Set Up:**

- Export Location: `~/PhotoSite/publish/` on the Mac (seen from the VM as
  `/mnt/mac/Users/ssickels/PhotoSite/publish/`)
- File Naming: custom template `{Date (YYYYMMDD)}-{Filename}~{Copy Name}`
  - `{Copy Name}` is empty for originals and "Copy 1", "Copy 2"… for virtual
    copies. Without it, a virtual copy published to a different theme than its
    original would have the same name and be merged with the original.
  - The `~` marks where the copy name starts. The copy name is left out of the
    photo's URL unless the original (or another copy) is published too.
  - Sony filenames start over after DSC09999, hence the date prefix.
- File Settings: JPEG, quality 90, **color space sRGB**
- Image Sizing: Long Edge 3000 px, don't enlarge
- Output Sharpening: Screen, Standard
- Metadata: **All Metadata**, with **Remove Person Info** and **Remove
  Location Info** checked (this removes GPS). Check **Write Keywords as
  Lightroom Hierarchy**.
- Watermark: off

**Keywords:** the place hierarchy sits under a top-level keyword `places`, and
cover tags under `covers` (see Covers above). Both root keywords need
**Include on Export** checked. Neither is shown on the site. Changing only a
keyword setting doesn't mark photos for republishing; use **Mark to Republish**
on the collections afterwards.

**Collections:** one publish collection per theme (Landscapes, Wildlife, Plants
and Flowers, The Built Environment). Drag photos in and click Publish. Location
pages need no collections; they're built from keywords. A theme can also be a
*smart* publish collection (e.g. Label = Green AND Keyword contains
"landscape").

## Status

- [x] Phase 1: skeleton, config, fixture, metadata, image pipeline + cache, tests
- [x] Phase 2: templates, pages, CSS, justified gallery, keyboard/swipe
- [x] Phase 3: real-data dry run (sizes → q80, location galleries, `~` copy
  names), plus logo/favicons, cover keywords, linked breadcrumbs, six themes
- [ ] Phase 4: `.htaccess`, FTPS (lftp) deploy with rsync as an option, staging, Lighthouse
