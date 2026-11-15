import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import make_fixtures  # noqa: E402
from photosite.config import load_config  # noqa: E402
from photosite.metadata import file_hashes, read_raw_metadata, scan_publish  # noqa: E402
from photosite.model import build_catalog  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "publish"
TEST_CONFIG = ROOT / "tests" / "site.yaml"


@pytest.fixture(scope="session")
def publish_dir() -> Path:
    """The shared, read-only fixture publish folder (generated if missing)."""
    if not FIXTURE.exists() or sum(1 for _ in FIXTURE.rglob("*.jpg")) != 15:
        make_fixtures.generate(FIXTURE)
    return FIXTURE


@pytest.fixture
def config(publish_dir, tmp_path):
    return load_config(TEST_CONFIG, publish=publish_dir, output=tmp_path / "dist",
                       cache=tmp_path / "cache")


@pytest.fixture
def scanned(config):
    files, _ = scan_publish(config.publish_dir)
    raw, _ = read_raw_metadata(files, config.cache_dir)
    hashes = file_hashes(files, config.cache_dir)
    return files, raw, hashes


@pytest.fixture
def catalog(config, scanned):
    return build_catalog(config, *scanned)


@pytest.fixture
def mutable_publish(publish_dir, tmp_path):
    """A private copy of the fixture that a test may change."""
    dest = tmp_path / "publish"
    shutil.copytree(publish_dir, dest)   # copytree keeps mtimes
    return dest
