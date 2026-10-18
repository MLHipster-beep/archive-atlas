PYTHON ?= python3
PYTHONPATH := src
export PYTHONPATH

.PHONY: test demo clean

test:
	$(PYTHON) -m unittest discover -s tests -t . -v

demo:
	$(PYTHON) -m archive_atlas.cli demo /tmp/archive-atlas-demo
	$(PYTHON) -m archive_atlas.cli index /tmp/archive-atlas-demo -o /tmp/archive-atlas.db --force
	$(PYTHON) -m archive_atlas.cli broken /tmp/archive-atlas.db || true
	$(PYTHON) -m archive_atlas.cli cycles /tmp/archive-atlas.db || true

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf build dist src/*.egg-info
