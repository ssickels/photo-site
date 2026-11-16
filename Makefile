PY := .venv/bin/python
TEST_CFG := tests/site.yaml

.PHONY: help venv build staging locations trips sizes fixtures test fixture-site serve serve-fixture clean

help:
	@echo "make build        build dist/production from the publish folder"
	@echo "make staging      build dist/staging (noindex)"
	@echo "make locations    print the place-keyword tree with counts"
	@echo "make trips        list likely trips (for Travels pages)"
	@echo "make sizes        derivative file sizes per width/format"
	@echo "make test         run the test suite (synthetic fixture)"
	@echo "make fixture-site build the site from the fixture into dist/"
	@echo "make serve        serve dist/production on http://localhost:8000"
	@echo "make serve-fixture serve the fixture site on http://localhost:8000"
	@echo "make venv         create .venv and install requirements"

venv:
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

build:
	$(PY) build.py

staging:
	$(PY) build.py --target staging

locations:
	$(PY) build.py locations

trips:
	$(PY) build.py trips

sizes:
	$(PY) build.py sizes

fixtures:
	$(PY) tools/make_fixtures.py

test:
	$(PY) -m pytest -q

fixture-site:
	$(PY) build.py --config $(TEST_CFG)

serve:
	$(PY) -m http.server 8000 --directory dist/production

serve-fixture:
	$(PY) -m http.server 8000 --directory dist/fixture/production

clean:
	rm -rf dist .cache
