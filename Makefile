PY := .venv/bin/python

.PHONY: setup backend frontend dev test seed build run prices

setup:
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -e "./backend[dev]"
	cd frontend && npm install
	git config core.hooksPath .githooks

backend:
	$(PY) -m uvicorn janitor.main:create_app --factory --reload --host 127.0.0.1 --port 8080

frontend:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 backend frontend

test:
	$(PY) -m pytest backend -q
	$(PY) -m ruff check backend scripts
	$(PY) scripts/check_private.py
	cd frontend && npm run typecheck

seed:
	$(PY) scripts/make_seed.py

build:
	cd frontend && npm run build

run: build
	$(PY) -m uvicorn janitor.main:create_app --factory --host 127.0.0.1 --port 8080

prices:
	$(PY) scripts/fetch_prices.py
