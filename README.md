# photo-site

A static photography portfolio built straight from **Lightroom Classic**.
You organize and keyword photos in Lightroom, click Publish, run one command,
and get a fast, self-contained website you can host almost anywhere. There's no
database, no CMS, no monthly portfolio-service fee, and no third-party requests
(no fonts, analytics or CDNs; the one optional exception is a captcha on the
contact form).

It was written to replace a PhotoShelter site ([stevesickels.com](https://stevesickels.com)),
and should suit anyone leaving PhotoShelter, SmugMug, Squarespace, Wix or
similar who already keeps their work organized in Lightroom.

**What you get**

- **Themes:** one gallery per Lightroom publish collection (Landscapes,
  Wildlife, …), including smart collections.
- **Locations:** galleries built from your hierarchical place keywords
  (`places > usa > maine > acadia`), with clickable breadcrumbs on every photo.
- **Cover photos chosen in Lightroom** with a keyword (`covers > landscapes`).
- Justified gallery rows; a photo page with arrow keys, swipe, pinch-zoom, Esc
  to go back, and the title, caption, date, location and themes underneath.
- Responsive images (WebP + JPEG at four widths), converted to sRGB, **GPS
  always removed**, copyright kept.
- Fast rebuilds: only new or changed photos are processed.
- Light and dark mode, keyboard accessible, works without JavaScript.
- A contact form that emails you (a small PHP script), with spam protection:
  a hidden trap field, a rate limit, and optionally a Cloudflare Turnstile
  captcha.
- A staging build that search engines are told to ignore.

## Is it for you? (assumptions)

- **Lightroom Classic** with a **Hard Drive publish service**. Not the
  cloud-based Lightroom, and not Capture One (the code reads standard
  XMP/IPTC metadata from JPEGs, so other tools could be adapted).
- For location pages: **hierarchical keywords** for places, all under one root
  keyword (by default `places`). Without them you still get themes, just no
  location pages.
- Titles and captions in Lightroom's Title and Caption fields; they're shown
  on photo pages.
- Comfort running a few terminal commands (or asking an AI assistant to), with
  Python 3.11+ and [exiftool](https://exiftool.org) installed.
- Any host that serves static files. Deploy is via FTPS or rsync (see Status).
  The contact form also needs PHP, which most shared hosting has.

## Quick start

1. Install exiftool (`brew install exiftool` on a Mac;
   `sudo apt install libimage-exiftool-perl` on Debian/Ubuntu), then:

   ```bash
   make venv
   ```

   ```bash
   make test
   ```

2. Copy the example config and edit it: your name, site URL, the path to your
   publish folder, theme order and location galleries.

   ```bash
   cp site.example.yaml site.yaml
   ```

3. Set up Lightroom as described below and publish a collection or two.

4. See your place keywords with photo counts, to pick location galleries:

   ```bash
   make locations
   ```

5. Build and preview at http://localhost:8000:

   ```bash
   make build
   ```

   ```bash
   make serve
   ```

6. Replace the logo, favicons and the About/Contact text with your own (see
   "Making it yours").

No photos yet? `make fixture-site` and `make serve-fixture` build a demo from
the synthetic test images.

## Lightroom setup

**Publish Services → Hard Drive → Set Up:**

- Export Location: a folder such as `~/PhotoSite/publish/` (set `paths.publish`
  in `site.yaml` to match). The build only ever reads this folder.
- File Naming: custom template `{Date (YYYYMMDD)}-{Filename}~{Copy Name}`
  - The date prefix keeps names unique when the camera's counter wraps
    (DSC09999 → DSC00001).
  - `{Copy Name}` is empty for originals and "Copy 1", "Copy 2"… for virtual
    copies, so a virtual copy isn't mistaken for its original.
  - The `~` marks where the copy name starts. The copy name is left out of the
    photo's web address unless the original (or another copy) is published too.
- File Settings: JPEG, quality 90, **color space sRGB**.
- Image Sizing: long edge 3000 px, don't enlarge.
- Output Sharpening: Screen, Standard.
- Metadata: **All Metadata**, with **Remove Person Info** and **Remove Location
  Info** checked (removes GPS). Check **Write Keywords as Lightroom Hierarchy**.
- Watermark: off.

**Collections:** one publish collection per theme. Drag photos in and click
Publish. A smart publish collection works too (for example, Keywords contains
"b&w" for a Black & White theme). A photo in several collections is one photo
shown in several themes.

**Keywords:**

- Places go under a top-level keyword (default `places`; set `location_root`).
  `site.yaml` lists which places get a gallery and in what order.
- Cover photos: a top-level keyword `covers`, with children named after a theme
  or location gallery (`covers > landscapes`, `covers > scotland`), plus
  `covers > home` for the home page. Tag one photo for each.
- Both root keywords need **Include on Export** checked. Neither is shown on
  the site.
- Changing only a keyword setting doesn't mark photos for republishing in
  Lightroom; use **Mark to Republish** on the collections afterwards.

## Commands

| Command | What it does |
|---|---|
| `make build` | Build `dist/production` from the publish folder |
| `make staging` | Build `dist/staging` (noindex, disallow-all robots.txt) |
| `make locations` | Print the place-keyword tree with photo counts |
| `make sizes` | Image file sizes per width and format |
| `make serve` | Serve `dist/production` at http://localhost:8000 |
| `make test` | Run the test suite against the synthetic fixture |
| `make fixture-site` / `make serve-fixture` | Build and serve a demo from the fixture |

Paths can be overridden: `./build.py --publish /some/folder --out /tmp/out`.

The build prints `warning:` lines for things to fix (a location gallery with no
photos, a cover tag that matches nothing, a photo that isn't sRGB) and `info:`
lines for things worth knowing (a collection that needs republishing).

## Making it yours

- **`site.yaml`:** site title, URLs, theme names/order/descriptions, location
  galleries and their display names, image sizes and quality. Every option is
  commented.
- **Logo:** put your logo at `static/img/logo.png` (shown 53 px tall; make it
  about 160 px tall for sharp screens), and optionally `logo-dark.png` for dark
  mode. With no logo file, the site title is shown as text.
  `tools/make_logos.py` is how this site made its own logo files; adapt it or
  use any image editor.
- **Favicons:** `static/favicon.svg`, `static/root/favicon.ico` and
  `static/root/apple-touch-icon.png`.
- **About and Contact:** Markdown files in `content/`. About appears in the
  menu and Contact in the footer; any other `.md` file there becomes a page at
  `/<name>/` that you can link to. `menu_pages` in `site.yaml` picks which go
  in the top menu.
- **Photos on those pages:** put the image file in `content/` next to the
  `.md` file, and write it on a line of its own, optionally with an italic
  caption on the next line:

  ```markdown
  ![Description for screen readers](print.jpg)
  *A print on matte paper. [See the photo](/landscapes/some-photo/).*
  ```

  The build converts it to sRGB, removes all metadata (GPS included) and
  makes resized WebP and JPEG versions.
- **Contact form:** see below.
- **Look:** one stylesheet, `static/css/site.css`; colors, fonts and spacing are
  custom properties at the top. Templates are Jinja2, in `templates/`.

## Contact form

With `contact.form: true` in `site.yaml`, `/contact/` shows the text of
`content/contact.md` followed by a form (name, email, message). The build puts
a small PHP handler next to it (`contact/send.php`, from `php/`), which emails
the message to you with the visitor's address as Reply-To.

- **Private settings** go in `site.local.yaml` (gitignored), never in
  `site.yaml`; the build refuses to run if they're in the wrong file:

  ```yaml
  contact:
    mail_to: you@example.com
    turnstile_secret: "0x4AAAA..."      # only if you use Turnstile
  ```

  The build writes them into `contact/config.php`, a PHP file that only
  returns its settings, so requesting it in a browser shows nothing.
- **Delivery:** `mail_from` should be on your own domain, and that domain's SPF
  DNS record must list your web server, or messages may go to spam. If your
  email is hosted elsewhere (Fastmail, Google, …), add the server to the
  existing record, e.g. `v=spf1 include:spf.messagingengine.com a:your-server.example ?all`.
  On cPanel, also set Email Routing for the domain to **Remote Mail Exchanger**.
- **Spam protection:** a hidden field that only bots fill in, a check that the
  form wasn't filled faster than a person could, and at most 5 messages per
  hour from one IP address. Optionally, a free
  [Cloudflare Turnstile](https://www.cloudflare.com/products/turnstile/) widget:
  put its site key in `site.yaml` and its secret in `site.local.yaml`, and add
  your domain to the widget's allowed hostnames.
- Staging messages have `[staging]` at the start of the subject.
- Without JavaScript the form still posts, and the visitor is sent back to the
  page.

## How it works

- **Themes** are the top-level folders of the publish folder, one per publish
  collection.
- **Photo identity is the filename.** The same file in several theme folders is
  one photo in several themes. If two copies differ (in the image or in the
  metadata the site uses), the newer is used and an `info:` line says a
  collection needs republishing.
- **Locations:** a gallery includes every photo at that place or anywhere below
  it. Every place in the hierarchy also gets a page (so breadcrumbs always
  link), but only the galleries listed in `site.yaml` appear on the Locations
  page.
- **Images:** WebP and JPEG at 480/960/1600/2400 px wide, never upscaled. Only
  the copyright tag is kept in the files. Filenames include a hash, so browsers
  can cache them forever.
- **Incremental:** metadata (one batched exiftool call) and images are cached
  in `.cache/`. An unchanged rebuild takes well under a second. `.cache/` and
  `dist/` can be deleted at any time.
- **JavaScript** (small, optional): justified gallery rows, the photo page's
  keys/swipe/zoom/prefetch, and a header that hides while you scroll down.

## Status

Working: everything above, tested against a real Lightroom library of about
400 published photos and a synthetic fixture (`make test`; the contact form's
PHP is tested too when `php` is installed).

Not built yet:

- `make deploy`: FTPS upload via `lftp mirror --reverse --delete`, with
  rsync-over-SSH as an option (`deploy:` in `site.yaml`). Credentials will come
  from `~/.netrc` or environment variables, never from the repo. Until then,
  upload `dist/production/` with any FTP client.
- An `.htaccess` with caching headers for Apache hosts.

## License

The code is MIT licensed (see [LICENSE](LICENSE)). The logo, favicons, the text
in `content/` and all photographs are © Steve Sickels and not covered by that
license.
