"""The contact form: config rules, what the build writes, and the PHP handler."""
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
import yaml

from photosite.config import ConfigError, load_config
from photosite.pipeline import build
from tests.conftest import ROOT, TEST_CONFIG

PUBLIC = {"form": True, "mail_from": "noreply@example.test", "subject": "Test contact"}
PRIVATE = {"mail_to": "owner@example.test"}


def write_config(tmp: Path, contact=None, private=None) -> Path:
    data = yaml.safe_load(TEST_CONFIG.read_text())
    data["paths"]["content"] = str(ROOT / "content")
    if contact is not None:
        data["contact"] = contact
    if private is not None:
        (tmp / "site.local.yaml").write_text(yaml.safe_dump({"contact": private}))
    path = tmp / "site.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def load(tmp, publish_dir, **kw):
    return load_config(write_config(tmp, **kw), publish=publish_dir,
                       output=tmp / "dist", cache=tmp / "cache")


# ------------------------------------------------------------------ config
def test_form_is_off_by_default(publish_dir, tmp_path):
    assert load(tmp_path, publish_dir).contact.form is False


def test_private_values_come_from_the_local_file(publish_dir, tmp_path):
    c = load(tmp_path, publish_dir, contact=PUBLIC, private=PRIVATE).contact
    assert c.form and c.mail_to == "owner@example.test" and c.mail_from == "noreply@example.test"


@pytest.mark.parametrize("key", ["mail_to", "turnstile_secret"])
def test_private_values_refused_in_site_yaml(publish_dir, tmp_path, key):
    with pytest.raises(ConfigError, match="private file"):
        load(tmp_path, publish_dir, contact={**PUBLIC, key: "x@example.test"}, private=PRIVATE)


def test_form_needs_a_recipient(publish_dir, tmp_path):
    with pytest.raises(ConfigError, match="mail_to"):
        load(tmp_path, publish_dir, contact=PUBLIC)


def test_turnstile_needs_both_keys(publish_dir, tmp_path):
    with pytest.raises(ConfigError, match="both"):
        load(tmp_path, publish_dir, contact={**PUBLIC, "turnstile_sitekey": "1x00000000000000000000AA"},
             private=PRIVATE)
    with pytest.raises(ConfigError, match="both"):
        load(tmp_path, publish_dir, contact=PUBLIC, private={**PRIVATE, "turnstile_secret": "s"})


# ------------------------------------------------------------------- build
@pytest.fixture(scope="module")
def built(publish_dir, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("contact")
    cfg = load(tmp, publish_dir,
               contact={**PUBLIC, "turnstile_sitekey": "1x00000000000000000000AA"},
               private={**PRIVATE, "turnstile_secret": "1x0000000000000000000000000000000AA"})
    build(cfg, "staging")
    return cfg.output_dir / "staging"


def test_contact_page_has_the_form(built):
    html = (built / "contact" / "index.html").read_text()
    assert 'action="/contact/send.php"' in html and 'name="website"' in html
    assert 'data-sitekey="1x00000000000000000000AA"' in html
    assert "owner@example.test" not in html            # the recipient never reaches a page
    for name in ("send.php", "contact-lib.php", "config.php"):
        assert (built / "contact" / name).exists()


def test_config_php_only_returns_settings(built):
    text = (built / "contact" / "config.php").read_text()
    assert text.startswith("<?php") and "echo" not in text
    blob = re.search(r"json_decode\('(.*)', true\)", text).group(1)
    settings = json.loads(blob.replace("\\'", "'").replace("\\\\", "\\"))
    assert settings["mail_to"] == "owner@example.test"
    assert settings["subject_tag"] == "[staging] Test contact"


def test_turnstile_script_only_on_the_contact_page(built):
    for page in built.rglob("*.html"):
        has = "challenges.cloudflare.com" in page.read_text()
        assert has == (page.relative_to(built).as_posix() == "contact/index.html"), page


def test_no_php_without_the_form(publish_dir, tmp_path):
    cfg = load(tmp_path, publish_dir)
    build(cfg, "production")
    out = cfg.output_dir / "production"
    assert not list(out.rglob("*.php"))
    assert "send.php" not in (out / "contact" / "index.html").read_text()


# --------------------------------------------------------------------- PHP
@pytest.fixture(scope="module")
def php_server(tmp_path_factory):
    """send.php under `php -S`, no captcha, mail written to a file."""
    if not shutil.which("php"):
        pytest.skip("php not installed")
    tmp = tmp_path_factory.mktemp("php")
    docroot, mail, temp = tmp / "www", tmp / "mail.txt", tmp / "temp"
    (docroot / "contact").mkdir(parents=True)
    temp.mkdir()
    for name in ("send.php", "contact-lib.php"):
        shutil.copy2(ROOT / "php" / name, docroot / "contact" / name)
    settings = {"mail_to": "owner@example.test", "mail_from": "noreply@example.test",
                "subject_tag": "Test", "return_page": "/contact/", "rl_max": 3,
                "min_fill_ms": 3000, "site_label": "test"}
    (docroot / "contact" / "config.php").write_text(
        f"<?php return json_decode('{json.dumps(settings)}', true);\n")
    sendmail = tmp / "sendmail.sh"
    sendmail.write_text(f'#!/bin/sh\n{{ echo "ARGS: $*"; cat; echo "=END="; }} >> {mail}\n')
    sendmail.chmod(0o755)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(["php", "-d", f"sendmail_path={sendmail}", "-d", f"sys_temp_dir={temp}",
                             "-S", f"127.0.0.1:{port}", "-t", str(docroot)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/contact/send.php"
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), 0.1).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url, mail
    proc.terminate()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def post(url, **fields):
    data = urllib.parse.urlencode(fields).encode()
    opener = urllib.request.build_opener(NoRedirect)
    try:
        r = opener.open(urllib.request.Request(url, data=data))
        return r.status, r.headers, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode()


def mails(path):
    return path.read_text().split("=END=")[:-1] if path.exists() else []


def test_php_handler(php_server):
    url, mail = php_server
    ok = dict(ajax="1", name="José", email="a@example.test", message="Hi & it's", elapsed="9000")

    assert json.loads(post(url, **ok)[2])["status"] == "success"
    sent = mails(mail)[-1]
    assert "ARGS: -fnoreply@example.test" in sent
    assert "To: owner@example.test" in sent and "Reply-To: a@example.test" in sent
    assert "=?UTF-8?B?" in sent and "Hi & it's" in sent

    # bots are told it worked, but nothing is sent
    n = len(mails(mail))
    assert json.loads(post(url, **{**ok, "website": "x"})[2])["status"] == "success"
    assert json.loads(post(url, **{**ok, "elapsed": "500"})[2])["status"] == "success"
    assert len(mails(mail)) == n

    assert json.loads(post(url, **{**ok, "email": "nope"})[2])["status"] == "error"

    # without JS: a redirect back to the form with a reason
    status, headers, _ = post(url, name="X", email="nope", message="m")
    assert status == 302 and headers["Location"] == "/contact/?status=error&reason=invalid"

    # a newline in the name can't add a header
    post(url, **{**ok, "name": "Eve\r\nBcc: victim@example.test"})
    assert not re.search(r"^Bcc:", mails(mail)[-1], re.M)

    # rate limit (rl_max 3): two sends so far; the 3rd works, the 4th is refused
    assert json.loads(post(url, **ok)[2])["status"] == "success"
    res = json.loads(post(url, **ok)[2])
    assert res["status"] == "error" and "Too many" in res["message"]
