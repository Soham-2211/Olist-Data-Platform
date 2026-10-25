.PHONY: install fetch land run evaluate all test lint clean

PY := python -m olist_platform.pipeline

install:
	pip install -e ".[dev]"

fetch:      ## download raw files from the pinned commit and verify SHA-256
	$(PY) fetch

land:       ## cut the raw dump into 22 monthly source-system drops
	$(PY) land

run:        ## process every batch: bronze -> silver/gold/ml -> data tests -> train/score
	$(PY) run

evaluate:   ## offline model study + production monitoring + generated docs
	$(PY) evaluate

all:        ## everything from scratch (~6 min on a laptop)
	$(PY) all

test:
	pytest -q

lint:
	ruff check src tests

clean:
	rm -rf data/landing data/warehouse.db* models
