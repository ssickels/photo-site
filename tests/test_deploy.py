"""Deploy helpers: settings, ~/.netrc, cPanel .htaccess blocks, .htaccess output."""
import pytest

from photosite import deploy
from photosite.config import ConfigError


def test_settings_require_host_and_user_and_refuse_passwords(config):
    config.deploy = {"method": "ftps", "staging": {"host": "ftp.example.test"}}
    with pytest.raises(ConfigError, match="user"):
        deploy.settings(config, "staging")
    config.deploy["staging"].update(user="me@example.test", password="x")
    with pytest.raises(ConfigError, match="password"):
        deploy.settings(config, "staging")
    del config.deploy["staging"]["password"]
    s = deploy.settings(config, "staging")
    assert s["remote_dir"] == "/" and s["method"] == "ftps"


def test_password_from_netrc_matches_host_and_user(tmp_path, monkeypatch):
    netrc = tmp_path / ".netrc"
    netrc.write_text("machine h.test login a@x.test password one\n"
                     "machine h.test login 'b@x.test' password 'two words'\n"
                     "machine other.test\n  login a@x.test\n  password three\n")
    monkeypatch.setattr(deploy, "NETRC", netrc)
    monkeypatch.delenv("PHOTOSITE_STAGING_PASSWORD", raising=False)
    assert deploy.password_for("staging", "h.test", "a@x.test") == "one"
    assert deploy.password_for("staging", "h.test", "b@x.test") == "two words"
    assert deploy.password_for("staging", "other.test", "a@x.test") == "three"
    assert deploy.password_for("staging", "h.test", "c@x.test") is None
    monkeypatch.setenv("PHOTOSITE_STAGING_PASSWORD", "env")
    assert deploy.password_for("staging", "h.test", "a@x.test") == "env"


def test_save_credentials_replaces_only_its_own_line(config, tmp_path, monkeypatch):
    netrc = tmp_path / ".netrc"
    netrc.write_text("machine h.test login a@x.test password old\nmachine z.test login q password r\n")
    monkeypatch.setattr(deploy, "NETRC", netrc)
    monkeypatch.setattr(deploy.getpass, "getpass", lambda prompt: 'n"ew pw')
    config.deploy = {"staging": {"host": "h.test", "user": "a@x.test"}}
    assert deploy.save_credentials(config, "staging") == 0
    assert oct(netrc.stat().st_mode & 0o777) == "0o600"
    assert "machine z.test login q password r" in netrc.read_text()
    monkeypatch.delenv("PHOTOSITE_STAGING_PASSWORD", raising=False)
    assert deploy.password_for("staging", "h.test", "a@x.test") == 'n"ew pw'


def test_lftp_quoting():
    assert deploy._q('a"b\\c') == '"a\\"b\\\\c"'


def test_cpanel_blocks_are_found():
    text = ("Options -Indexes\n"
            "# php -- BEGIN cPanel-generated handler, do not edit\n"
            "AddHandler application/x-httpd-ea-php83 .php\n"
            "# php -- END cPanel-generated handler, do not edit\n"
            "# BEGIN cPanel-generated php ini directives, do not edit\n"
            "php_value x 1\n"
            "# END cPanel-generated php ini directives, do not edit\n")
    blocks = deploy.CPANEL_BLOCK.findall(text)
    assert len(blocks) == 2 and "ea-php83" in blocks[0] and "php_value" in blocks[1]


def test_htaccess(config, catalog):
    from photosite.render import Site
    staging = Site(config, catalog, {}, "staging").htaccess()
    prod = Site(config, catalog, {}, "production").htaccess()
    assert "ErrorDocument 404 /404.html" in prod
    assert "X-Robots-Tag" in staging and "X-Robots-Tag" not in prod
    assert "RewriteRule ^ https://example.test%{REQUEST_URI} [R=301,L]" in prod
    assert "!^/\\.well-known/" in prod                    # certificate renewals not redirected


def test_redactor_hides_password_in_every_form():
    pw = "uX9!@&x z"
    clean = deploy.redactor(pw)
    line = ('get -O "ftp://me%40site.test:uX9%21%40%26x%20z@host.test/a b" file:/x\n'
            f"plain {pw} here; ftp://u:{pw.replace(' ', '%20')}@h/")
    out = clean(line)
    assert "uX9" not in out and "%21%40" not in out
    assert "ftp://me%40site.test:***@host.test/a b" in out


def test_keep_protects_other_sites_folders(config):
    import re
    config.deploy = {"production": {"host": "h", "user": "u", "keep": ["new.example.test/"]}}
    pats = deploy.keep_patterns(deploy.settings(config, "production"))
    kept = lambda path: any(re.search(p, path) for p in pats)
    assert kept("new.example.test/") and kept("new.example.test/index.html")
    assert kept(".well-known/acme-challenge/x") and kept("cgi-bin/")
    assert not kept("newxexample.test/") and not kept("themes/new.example.test/")
    assert not kept("index.html") and not kept("img/a.jpg")
    config.deploy["production"]["keep"] = "new.example.test"
    with pytest.raises(ConfigError, match="keep"):
        deploy.settings(config, "production")
