"""Upload dist/<target>/ to the web host.

FTPS (explicit TLS) with `lftp mirror --reverse --delete --only-newer`; the
build keeps unchanged files' dates, so only what changed is uploaded.
rsync over SSH is the alternative (deploy.method: rsync).

Passwords never come from site.yaml: they come from the environment
(PHOTOSITE_<TARGET>_PASSWORD) or from ~/.netrc, an entry matching both the
host and the user. `./build.py credentials <target>` writes that entry.
"""
from __future__ import annotations

import getpass
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from .config import Config, ConfigError

NETRC = Path.home() / ".netrc"

# Server-side things a deploy must never upload over or delete: certificate
# checks, cPanel's folders and files, PHP's error log.
KEEP_ON_SERVER = [r"^\.well-known/", r"^cgi-bin/", r"(^|/)error_log$", r"^\.ftpquota$",
                  r"^\.user\.ini$", r"^php\.ini$"]

# Blocks cPanel writes into .htaccess (e.g. the PHP version). A deploy carries
# them over into the new .htaccess instead of dropping them.
CPANEL_BLOCK = re.compile(r"^# (?:php -- )?BEGIN cPanel-generated.*?^# (?:php -- )?END cPanel-generated[^\n]*\n?",
                          re.M | re.S)


def settings(config: Config, target: str) -> dict:
    t = dict((config.deploy or {}).get(target) or {})
    method = str(t.get("method") or (config.deploy or {}).get("method") or "ftps")
    if method not in ("ftps", "rsync"):
        raise ConfigError(f"deploy.method must be ftps or rsync, not {method!r}")
    for key in ("host", "user"):
        if not t.get(key):
            raise ConfigError(f"deploy.{target}.{key} is missing in site.yaml")
    if t.get("password"):
        raise ConfigError("never put a password in site.yaml; run ./build.py credentials "
                          f"{target}")
    remote = str(t.get("remote_dir") or "/")
    keep = t.get("keep") or []
    if isinstance(keep, str) or not all(isinstance(k, str) and k.strip("/") for k in keep):
        raise ConfigError(f"deploy.{target}.keep must be a list of folder names, e.g. [new.example.com]")
    return {"method": method, "host": str(t["host"]), "user": str(t["user"]),
            "remote_dir": remote if remote.endswith("/") else remote + "/",
            "port": t.get("port"), "keep": [k.strip("/") for k in keep]}


def keep_patterns(s: dict) -> list[str]:
    """lftp --exclude regexes: the server's own files, plus folders in the
    target's `keep:` list (e.g. another site's folder inside this docroot)."""
    return KEEP_ON_SERVER + [rf"^{re.escape(k)}(/|$)" for k in s.get("keep", [])]


# ------------------------------------------------------------------ netrc
def _netrc_entries(text: str) -> list[dict]:
    toks = shlex.split(text, comments=True, posix=True)
    entries, cur, i = [], None, 0
    while i < len(toks):
        tok = toks[i]
        if tok in ("machine", "default"):
            cur = {"machine": toks[i + 1] if tok == "machine" and i + 1 < len(toks) else ""}
            entries.append(cur)
            i += 2 if tok == "machine" else 1
            continue
        if cur is not None and tok in ("login", "password", "account") and i + 1 < len(toks):
            cur[tok] = toks[i + 1]
            i += 2
            continue
        i += 1
    return entries


def password_for(target: str, host: str, user: str) -> str | None:
    env = os.environ.get(f"PHOTOSITE_{target.upper()}_PASSWORD")
    if env:
        return env
    if NETRC.exists():
        for e in _netrc_entries(NETRC.read_text()):
            if e.get("machine") == host and e.get("login") == user:
                return e.get("password")
    return None


def save_credentials(config: Config, target: str) -> int:
    """Ask for the FTP password (not echoed) and store it in ~/.netrc (mode 600)."""
    s = settings(config, target)
    print(f"Saving the password for {s['user']} on {s['host']} in {NETRC}.")
    pw = getpass.getpass("FTP password (typing won't show): ")
    if not pw:
        print("Nothing entered; nothing saved.")
        return 1
    if any(c in pw for c in "\n\r"):
        print("A password can't contain a line break.")
        return 1
    line = f"machine {s['host']} login {shlex.quote(s['user'])} password {shlex.quote(pw)}\n"
    old = NETRC.read_text().splitlines(keepends=True) if NETRC.exists() else []
    prefix = re.compile(rf"^machine\s+{re.escape(s['host'])}\s+login\s+['\"]?{re.escape(s['user'])}['\"]?\s")
    kept = [l for l in old if not prefix.match(l)]
    fd = os.open(NETRC, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.writelines(kept + [line])
    os.chmod(NETRC, 0o600)
    print("Saved. Check it with:  ./build.py --deploy " + target + " --dry-run")
    return 0


# ------------------------------------------------------------------ lftp
def _q(s: str) -> str:
    """Quote for lftp's command parser."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def redactor(password: str):
    """lftp writes the login, password included, into URLs it prints (dry
    runs, errors). Everything lftp says passes through this first."""
    secrets = sorted({password, urllib.parse.quote(password, safe=""),
                      urllib.parse.quote(password)}, key=len, reverse=True)
    url_login = re.compile(r"(\w+://[^/\s:@]*):[^@\s/]*@")

    def clean(text: str) -> str:
        for sec in secrets:
            if sec:
                text = text.replace(sec, "***")
        return url_login.sub(r"\1:***@", text)
    return clean


def _lftp(script: str, password: str, echo: bool = False) -> tuple[int, str]:
    """Run lftp; return (exit code, redacted output). With echo, also print the
    redacted output line by line as it comes."""
    if not shutil.which("lftp"):
        raise ConfigError("lftp isn't installed (sudo apt install lftp)")
    clean = redactor(password)
    # The password goes in the environment, never on a command line.
    env = {**os.environ, "LFTP_PASSWORD": password}
    proc = subprocess.Popen(["lftp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
    proc.stdin.write(script)
    proc.stdin.close()
    lines = []
    for line in proc.stdout:
        line = clean(line)
        lines.append(line)
        if echo:
            print(line, end="", flush=True)
    return proc.wait(), "".join(lines)


def _session(s: dict, password: str) -> str:
    port = f":{s['port']}" if s.get("port") else ""
    return "\n".join([
        "set cmd:fail-exit yes",
        "set ftp:ssl-force yes",               # explicit TLS (AUTH TLS) or nothing
        "set ftp:ssl-protect-data yes",
        "set ftp:ssl-protect-list yes",
        "set ssl:verify-certificate yes",
        "set ssl:check-hostname yes",
        "set ftp:passive-mode yes",
        "set net:timeout 30",
        "set net:max-retries 3",
        "set net:reconnect-interval-base 5",
        # The password reaches lftp in LFTP_PASSWORD (see _lftp), so no
        # character in it can be misread by lftp's command parser.
        f"open --env-password -u {_q(s['user'])} ftp://{s['host']}{port}",
    ])


def _merge_cpanel_blocks(s: dict, password: str, local_htaccess: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        script = _session(s, password).replace("set cmd:fail-exit yes", "set cmd:fail-exit no")
        script += f"\nget -O {_q(tmp)} {_q(s['remote_dir'] + '.htaccess')}\n"
        _lftp(script, password)
        remote = Path(tmp) / ".htaccess"
        if not remote.exists():
            return
        blocks = CPANEL_BLOCK.findall(remote.read_text(errors="replace"))
    if not blocks or not local_htaccess.exists():
        return
    text = CPANEL_BLOCK.sub("", local_htaccess.read_text())
    local_htaccess.write_text("".join(b if b.endswith("\n") else b + "\n" for b in blocks)
                              + "\n" + text)
    print(f"deploy: kept {len(blocks)} cPanel block(s) from the server's .htaccess")


def deploy(config: Config, target: str, dry_run: bool = False) -> int:
    s = settings(config, target)
    local = (config.output_dir / target).resolve()
    if not (local / "index.html").exists():
        raise ConfigError(f"nothing to deploy: {local} has no index.html")
    if s["method"] == "rsync":
        return _deploy_rsync(s, local, dry_run)

    password = password_for(target, s["host"], s["user"])
    if not password:
        raise ConfigError(f"no password for {s['user']} on {s['host']}: run "
                          f"./build.py credentials {target}")

    excludes = " ".join(f"--exclude {_q(x)}" for x in keep_patterns(s))
    mirror = f"mirror --reverse --only-newer --no-perms --parallel=3 {excludes}"
    remote, src = s["remote_dir"], str(local)
    print(f"deploy: {local} -> ftps://{s['user']}@{s['host']}{remote}"
          + ("  (dry run: nothing is changed)" if dry_run else ""))

    if dry_run:
        script = _session(s, password) + f"\n{mirror} --delete --dry-run {_q(src)} {_q(remote)}\n"
        rc, out = _lftp(script, password)
        if rc:
            print(out.strip(), file=sys.stderr)
            return rc
        return _summarize(out, s["host"])

    _merge_cpanel_blocks(s, password, local / ".htaccess")
    # Images and static files first, then everything else with --delete, so a
    # page never goes up before the files it refers to.
    script = "\n".join([
        _session(s, password),
        f"{mirror} --verbose=1 {_q(src + '/img')} {_q(remote + 'img')}",
        f"{mirror} --verbose=1 {_q(src + '/static')} {_q(remote + 'static')}",
        f"{mirror} --delete --verbose=1 {_q(src)} {_q(remote)}",
        "",
    ])
    rc, _ = _lftp(script, password, echo=True)
    if rc:
        print("deploy: lftp failed (see above)", file=sys.stderr)
        return rc
    return _smoke(config, target)


def _summarize(out: str, host: str) -> int:
    """lftp's dry run prints commands with full URLs; show just paths."""
    url = re.compile(r'"?\w+://[^/\s]*' + re.escape(host) + r'(/[^"\s]*)"?')
    lines = [url.sub(lambda m: m.group(1), l) for l in out.splitlines()]
    ups = [l for l in lines if l.startswith(("put ", "get "))]
    rms = [l for l in lines if l.startswith(("rm ", "rmdir "))]
    print(f"would upload {len(ups)} files and delete {len(rms)} on the server")
    for l in rms[:40]:
        print("  delete " + l.split(None, 1)[-1])
    if len(rms) > 40:
        print(f"  ... and {len(rms) - 40} more")
    return 0


def _smoke(config: Config, target: str) -> int:
    base = config.target(target)["base_url"]
    bad = 0
    for path in ("/", "/robots.txt", "/contact/"):
        try:
            with urllib.request.urlopen(base + path, timeout=20) as r:
                print(f"check: {base}{path} -> {r.status}")
        except Exception as e:          # noqa: BLE001
            print(f"check: {base}{path} -> {e}")
            bad += 1
    return 1 if bad else 0


def _deploy_rsync(s: dict, local: Path, dry_run: bool) -> int:
    if not shutil.which("rsync"):
        raise ConfigError("rsync isn't installed")
    port = ["-e", f"ssh -p {s['port']}"] if s.get("port") else []
    cmd = ["rsync", "-rlt", "--delete", "--checksum", "--itemize-changes", *port,
           *[f"--exclude={x}" for x in ("/.well-known/", "/cgi-bin/", "error_log",
                                        "/.ftpquota", "/.user.ini", "/php.ini",
                                        *(f"/{k}/" for k in s.get("keep", [])))],
           *(["--dry-run"] if dry_run else []),
           f"{local}/", f"{s['user']}@{s['host']}:{s['remote_dir']}"]
    return subprocess.run(cmd).returncode
